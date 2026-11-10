from __future__ import annotations

import hashlib
import importlib
import json
import math
import re
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any


LOCAL_PROVIDER_VERSION = "ESS-SEMANTIC-LOCAL-E5-ONNX-V1"
_MODEL_ID = "intfloat/multilingual-e5-small"
_MODEL_REVISION = "614241f622f53c4eeff9890bdc4f31cfecc418b3"
_MODEL_FILE = "model_quint8_avx2.onnx"
_TOKENIZER_FILE = "tokenizer.json"
_MANIFEST_FILE = "model-manifest.json"
_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")


@dataclass(frozen=True)
class LocalSemanticConfig:
    model_dir: Path
    min_similarity: float
    min_margin: float
    max_length: int = 256


@dataclass(frozen=True)
class _ValidatedModel:
    model_dir: Path
    model_path: Path
    tokenizer_path: Path
    fingerprint: tuple[str, ...]


@dataclass
class _Runtime:
    tokenizer: Any
    session: Any
    numpy: Any
    input_names: frozenset[str]
    output_name: str
    fingerprint: tuple[str, ...]
    lock: threading.RLock


@dataclass(frozen=True)
class _Catalog:
    topics: tuple[str, ...]
    verticals: tuple[str, ...]
    prototypes: tuple[tuple[str, ...], ...]
    cache_key: tuple[Any, ...]


_CACHE_LOCK = threading.RLock()
_RUNTIME_CACHE: dict[tuple[str, ...], _Runtime] = {}
_CATALOG_CACHE: dict[tuple[Any, ...], Any] = {}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _manifest_identity(manifest: dict[str, Any]) -> tuple[Any, Any]:
    model = manifest.get("model")
    nested = model if isinstance(model, dict) else {}
    model_id = manifest.get("model_id", manifest.get("modelId", nested.get("id")))
    revision = manifest.get("revision", nested.get("revision"))
    return model_id, revision


def _manifest_files(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    files = manifest.get("files")
    if isinstance(files, dict):
        return {
            str(name): metadata
            for name, metadata in files.items()
            if isinstance(metadata, dict)
        }
    if isinstance(files, list):
        result = {}
        for entry in files:
            if not isinstance(entry, dict):
                raise ValueError("Local model manifest has a malformed files list.")
            name = entry.get("name", entry.get("path"))
            if not isinstance(name, str) or not name:
                raise ValueError("Local model manifest has a file without a valid name.")
            if name in result:
                raise ValueError(
                    f"Local model manifest contains duplicate file {name!r}."
                )
            result[name] = entry
        return result
    raise ValueError("Local model manifest must contain a files object or list.")


def _file_metadata(
    files: dict[str, dict[str, Any]], filename: str
) -> tuple[int, str]:
    metadata = files.get(filename)
    if metadata is None:
        raise ValueError(f"Local model manifest is missing {filename!r}.")
    size = metadata.get(
        "size",
        metadata.get("size_bytes", metadata.get("sizeBytes")),
    )
    expected_hash = metadata.get("sha256", metadata.get("sha_256"))
    if isinstance(size, bool) or not isinstance(size, int) or size < 0:
        raise ValueError(
            f"Local model manifest has an invalid size for {filename!r}."
        )
    if not isinstance(expected_hash, str) or not _SHA256_RE.fullmatch(
        expected_hash
    ):
        raise ValueError(
            f"Local model manifest has an invalid SHA-256 for {filename!r}."
        )
    return size, expected_hash.lower()


def _validate_model(model_dir: Path) -> _ValidatedModel:
    try:
        resolved_dir = model_dir.expanduser().resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise ValueError(f"Local model directory does not exist: {model_dir}.") from error
    if not resolved_dir.is_dir():
        raise ValueError(f"Local model path is not a directory: {model_dir}.")

    manifest_path = resolved_dir / _MANIFEST_FILE
    try:
        manifest_bytes = manifest_path.read_bytes()
    except OSError as error:
        raise ValueError(
            f"Local model directory is missing {_MANIFEST_FILE!r}."
        ) from error
    try:
        manifest = json.loads(manifest_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("Local model manifest is not valid UTF-8 JSON.") from error
    if not isinstance(manifest, dict):
        raise ValueError("Local model manifest must be a JSON object.")

    model_id, revision = _manifest_identity(manifest)
    if model_id != _MODEL_ID or revision != _MODEL_REVISION:
        raise ValueError(
            "Local model manifest mismatch: expected model "
            f"{_MODEL_ID!r} at revision {_MODEL_REVISION!r}."
        )
    files = _manifest_files(manifest)

    validated: list[tuple[Path, str, int, int]] = []
    for filename in (_MODEL_FILE, _TOKENIZER_FILE):
        expected_size, expected_hash = _file_metadata(files, filename)
        path = resolved_dir / filename
        try:
            before = path.stat()
        except OSError as error:
            raise ValueError(
                f"Local model directory is missing required file {filename!r}."
            ) from error
        if not path.is_file():
            raise ValueError(f"Local model artifact {filename!r} is not a file.")
        if before.st_size != expected_size:
            raise ValueError(
                f"Local model artifact size mismatch for {filename!r}: "
                f"expected {expected_size}, found {before.st_size}."
            )
        try:
            actual_hash = _sha256(path)
        except OSError as error:
            raise ValueError(
                f"Local model artifact {filename!r} changed during validation."
            ) from error
        try:
            after = path.stat()
        except OSError as error:
            raise ValueError(
                f"Local model artifact {filename!r} changed during validation."
            ) from error
        if (
            before.st_size != after.st_size
            or before.st_mtime_ns != after.st_mtime_ns
        ):
            raise ValueError(
                f"Local model artifact {filename!r} changed during validation."
            )
        if actual_hash != expected_hash:
            raise ValueError(
                f"Local model artifact SHA-256 mismatch for {filename!r}."
            )
        validated.append((path, actual_hash, after.st_size, after.st_mtime_ns))

    manifest_hash = hashlib.sha256(manifest_bytes).hexdigest()
    fingerprint = (
        str(resolved_dir),
        manifest_hash,
        *(
            value
            for path, actual_hash, size, modified in validated
            for value in (path.name, actual_hash, str(size), str(modified))
        ),
    )
    return _ValidatedModel(
        model_dir=resolved_dir,
        model_path=resolved_dir / _MODEL_FILE,
        tokenizer_path=resolved_dir / _TOKENIZER_FILE,
        fingerprint=fingerprint,
    )


def _check_tensor_input(node: Any) -> None:
    if getattr(node, "type", None) != "tensor(int64)":
        raise ValueError(
            f"Local semantic model input {getattr(node, 'name', '')!r} "
            "must be an int64 tensor."
        )
    shape = getattr(node, "shape", None)
    if not isinstance(shape, (list, tuple)) or len(shape) != 2:
        raise ValueError(
            f"Local semantic model input {getattr(node, 'name', '')!r} "
            "must have rank 2."
        )


def _load_runtime(validated: _ValidatedModel) -> _Runtime:
    try:
        numpy = importlib.import_module("numpy")
        onnxruntime = importlib.import_module("onnxruntime")
        tokenizers = importlib.import_module("tokenizers")
    except ImportError as error:
        raise ValueError(
            "Local semantic inference requires the optional dependencies "
            "numpy, onnxruntime, and tokenizers."
        ) from error

    try:
        tokenizer = tokenizers.Tokenizer.from_file(str(validated.tokenizer_path))
    except Exception as error:
        raise ValueError("Local semantic tokenizer could not be loaded.") from error
    try:
        session = onnxruntime.InferenceSession(
            str(validated.model_path),
            providers=["CPUExecutionProvider"],
        )
    except Exception as error:
        raise ValueError("Local semantic ONNX model could not be loaded.") from error

    try:
        providers = session.get_providers()
        inputs = session.get_inputs()
        outputs = session.get_outputs()
    except Exception as error:
        raise ValueError("Local semantic model metadata could not be read.") from error
    if providers != ["CPUExecutionProvider"]:
        raise ValueError(
            "Local semantic model must run with CPUExecutionProvider only."
        )
    if not isinstance(inputs, list) or not inputs:
        raise ValueError("Local semantic model declares no inputs.")
    input_by_name = {
        getattr(node, "name", None): node
        for node in inputs
        if isinstance(getattr(node, "name", None), str)
    }
    allowed_inputs = {"input_ids", "attention_mask", "token_type_ids"}
    if set(input_by_name) not in (
        {"input_ids", "attention_mask"},
        allowed_inputs,
    ) or len(input_by_name) != len(inputs):
        raise ValueError(
            "Local semantic model must declare input_ids, attention_mask, "
            "and optionally token_type_ids only."
        )
    for node in inputs:
        _check_tensor_input(node)

    if not isinstance(outputs, list) or len(outputs) != 1:
        raise ValueError(
            "Local semantic model must declare exactly one token-embedding output."
        )
    output = outputs[0]
    output_type = getattr(output, "type", None)
    output_shape = getattr(output, "shape", None)
    if output_type not in {
        "tensor(float)",
        "tensor(float16)",
        "tensor(double)",
    } or not isinstance(output_shape, (list, tuple)) or len(output_shape) != 3:
        raise ValueError(
            "Local semantic model output must be a rank-3 floating-point "
            "token-embedding tensor."
        )
    output_name = getattr(output, "name", None)
    if not isinstance(output_name, str) or not output_name:
        raise ValueError("Local semantic model output has no valid name.")

    return _Runtime(
        tokenizer=tokenizer,
        session=session,
        numpy=numpy,
        input_names=frozenset(input_by_name),
        output_name=output_name,
        fingerprint=validated.fingerprint,
        lock=threading.RLock(),
    )


def _get_runtime(validated: _ValidatedModel) -> _Runtime:
    with _CACHE_LOCK:
        cached = _RUNTIME_CACHE.get(validated.fingerprint)
        if cached is not None:
            return cached
    runtime = _load_runtime(validated)
    with _CACHE_LOCK:
        cached = _RUNTIME_CACHE.get(validated.fingerprint)
        if cached is not None:
            return cached
        directory = str(validated.model_dir)
        for key in list(_RUNTIME_CACHE):
            if key[0] == directory:
                del _RUNTIME_CACHE[key]
        for key in list(_CATALOG_CACHE):
            if key[0] == directory:
                del _CATALOG_CACHE[key]
        _RUNTIME_CACHE[validated.fingerprint] = runtime
        return runtime


def _validate_threshold(name: str, value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a finite number from 0 to 1.")
    number = float(value)
    if not math.isfinite(number) or not 0 <= number <= 1:
        raise ValueError(f"{name} must be a finite number from 0 to 1.")
    return number


def _validate_config(config: LocalSemanticConfig) -> None:
    if not isinstance(config, LocalSemanticConfig):
        raise ValueError("config must be a LocalSemanticConfig instance.")
    if not isinstance(config.model_dir, Path):
        raise ValueError("Local semantic model_dir must be a pathlib.Path.")
    _validate_threshold("min_similarity", config.min_similarity)
    _validate_threshold("min_margin", config.min_margin)
    if (
        isinstance(config.max_length, bool)
        or not isinstance(config.max_length, int)
        or config.max_length < 1
    ):
        raise ValueError("Local semantic max_length must be a positive integer.")


def _validate_items(items: Any) -> list[tuple[str, str]]:
    if not isinstance(items, list):
        raise ValueError("Local semantic items must be a list.")
    result = []
    seen = set()
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            raise ValueError(
                f"Local semantic item at index {index} must be an object."
            )
        item_id = item.get("id")
        if not isinstance(item_id, str) or not item_id.strip():
            raise ValueError(
                f"Local semantic item at index {index} has an unknown or invalid ID."
            )
        if item_id in seen:
            raise ValueError(f"Local semantic batch has duplicate ID {item_id!r}.")
        if "text" not in item:
            raise ValueError(
                f"Local semantic item {item_id!r} is missing message text."
            )
        text = item["text"]
        if text is None:
            text = ""
        if not isinstance(text, str):
            raise ValueError(
                f"Local semantic item {item_id!r} has non-string message text."
            )
        seen.add(item_id)
        result.append((item_id, text))
    return result


def _clean_catalog_text(value: Any, field: str, index: int) -> str:
    if not isinstance(value, str) or not " ".join(value.split()):
        raise ValueError(
            f"Local semantic catalog entry {index} has an invalid {field}."
        )
    return " ".join(value.split())


def _validate_catalog(topic_catalog: Any) -> _Catalog:
    if not isinstance(topic_catalog, list) or not topic_catalog:
        raise ValueError("Local semantic classification requires a non-empty catalog.")
    topics: list[str] = []
    verticals: list[str] = []
    all_prototypes: list[tuple[str, ...]] = []
    seen = set()
    for index, entry in enumerate(topic_catalog):
        if not isinstance(entry, dict):
            raise ValueError(
                f"Local semantic catalog entry {index} must be an object."
            )
        topic = _clean_catalog_text(entry.get("topic"), "topic", index)
        vertical = _clean_catalog_text(entry.get("vertical"), "vertical", index)
        examples = entry.get("examples")
        if not isinstance(examples, list):
            raise ValueError(
                f"Local semantic catalog entry {index} examples must be a list."
            )
        if topic in seen:
            raise ValueError(
                f"Local semantic catalog contains duplicate topic {topic!r}."
            )
        clean_examples = []
        example_seen = set()
        for example_index, example in enumerate(examples):
            if not isinstance(example, str) or not " ".join(example.split()):
                raise ValueError(
                    f"Local semantic catalog entry {index} has invalid example "
                    f"{example_index}."
                )
            clean = " ".join(example.split())
            if clean not in example_seen:
                clean_examples.append(clean)
                example_seen.add(clean)

        prototype_texts = [
            f"query: {topic}",
            f"query: {vertical}: {topic}",
        ]
        prototype_texts.extend(
            f"query: {vertical}: {topic}. {example}"
            for example in clean_examples
        )
        seen.add(topic)
        topics.append(topic)
        verticals.append(vertical)
        all_prototypes.append(tuple(prototype_texts))

    cache_key = tuple(
        (topic, vertical, prototypes)
        for topic, vertical, prototypes in zip(
            topics, verticals, all_prototypes, strict=True
        )
    )
    return _Catalog(
        topics=tuple(topics),
        verticals=tuple(verticals),
        prototypes=tuple(all_prototypes),
        cache_key=cache_key,
    )


def _encode(runtime: _Runtime, texts: list[str], max_length: int) -> Any:
    numpy = runtime.numpy
    if not texts:
        raise ValueError("Local semantic embedding batch must not be empty.")
    try:
        pad_token = next(
            (
                token
                for token in ("[PAD]", "<pad>")
                if isinstance(runtime.tokenizer.token_to_id(token), int)
            ),
            None,
        )
        pad_id = (
            runtime.tokenizer.token_to_id(pad_token)
            if pad_token is not None
            else None
        )
        if not isinstance(pad_id, int):
            raise ValueError("Tokenizer does not declare a supported padding token.")
        runtime.tokenizer.enable_truncation(max_length=max_length)
        runtime.tokenizer.enable_padding(
            length=max_length,
            pad_id=pad_id,
            pad_token=pad_token,
        )
        encodings = runtime.tokenizer.encode_batch(
            texts,
            add_special_tokens=True,
        )
    except ValueError:
        raise
    except Exception as error:
        raise ValueError("Local semantic tokenizer failed to encode text.") from error
    if not isinstance(encodings, list) or len(encodings) != len(texts):
        raise ValueError(
            "Local semantic tokenizer returned an unexpected batch shape."
        )
    try:
        input_ids = numpy.asarray(
            [encoding.ids for encoding in encodings],
            dtype=numpy.int64,
        )
        attention_mask = numpy.asarray(
            [encoding.attention_mask for encoding in encodings],
            dtype=numpy.int64,
        )
    except Exception as error:
        raise ValueError(
            "Local semantic tokenizer returned malformed encodings."
        ) from error
    expected_shape = (len(texts), max_length)
    if input_ids.shape != expected_shape or attention_mask.shape != expected_shape:
        raise ValueError(
            "Local semantic tokenizer did not apply fixed padding and truncation."
        )
    if not numpy.all((attention_mask == 0) | (attention_mask == 1)):
        raise ValueError("Local semantic tokenizer returned an invalid attention mask.")
    feeds = {
        "input_ids": input_ids,
        "attention_mask": attention_mask,
    }
    if "token_type_ids" in runtime.input_names:
        try:
            token_type_ids = numpy.asarray(
                [encoding.type_ids for encoding in encodings],
                dtype=numpy.int64,
            )
        except Exception as error:
            raise ValueError(
                "Local semantic tokenizer did not provide token_type_ids."
            ) from error
        if token_type_ids.shape != expected_shape:
            raise ValueError(
                "Local semantic tokenizer returned invalid token_type_ids."
            )
        feeds["token_type_ids"] = token_type_ids

    try:
        outputs = runtime.session.run([runtime.output_name], feeds)
    except Exception as error:
        raise ValueError("Local semantic ONNX inference failed.") from error
    if not isinstance(outputs, list) or len(outputs) != 1:
        raise ValueError(
            "Local semantic model returned an unexpected number of outputs."
        )
    token_embeddings = numpy.asarray(outputs[0])
    if (
        token_embeddings.ndim != 3
        or token_embeddings.shape[:2] != expected_shape
        or token_embeddings.shape[2] < 1
        or token_embeddings.dtype.kind not in "fc"
    ):
        raise ValueError(
            "Local semantic model returned an unexpected token-embedding shape."
        )
    if not numpy.all(numpy.isfinite(token_embeddings)):
        raise ValueError("Local semantic model returned non-finite embeddings.")

    mask = attention_mask[..., None]
    counts = mask.sum(axis=1)
    if numpy.any(counts <= 0):
        raise ValueError("Local semantic tokenizer produced an empty attention mask.")
    pooled = (token_embeddings * mask).sum(axis=1) / counts
    if not numpy.all(numpy.isfinite(pooled)):
        raise ValueError("Local semantic mean pooling produced non-finite embeddings.")
    norms = numpy.linalg.norm(pooled, axis=1, keepdims=True)
    if not numpy.all(numpy.isfinite(norms)) or numpy.any(norms <= 0):
        raise ValueError(
            "Local semantic model returned zero or non-finite embeddings."
        )
    normalized = pooled / norms
    if not numpy.all(numpy.isfinite(normalized)):
        raise ValueError("Local semantic normalization produced non-finite embeddings.")
    return normalized


def _catalog_embeddings(
    runtime: _Runtime,
    catalog: _Catalog,
    max_length: int,
) -> Any:
    cache_key = (
        runtime.fingerprint[0],
        runtime.fingerprint,
        max_length,
        catalog.cache_key,
    )
    with _CACHE_LOCK:
        cached = _CATALOG_CACHE.get(cache_key)
        if cached is not None:
            return cached

    flat = [
        prototype
        for topic_prototypes in catalog.prototypes
        for prototype in topic_prototypes
    ]
    normalized_prototypes = _encode(runtime, flat, max_length)
    numpy = runtime.numpy
    topic_embeddings = []
    offset = 0
    for prototypes in catalog.prototypes:
        topic_average = normalized_prototypes[
            offset : offset + len(prototypes)
        ].mean(axis=0)
        offset += len(prototypes)
        norm = float(numpy.linalg.norm(topic_average))
        if not math.isfinite(norm) or norm <= 0:
            raise ValueError(
                "Local semantic topic prototypes produced a zero or non-finite embedding."
            )
        topic_embeddings.append(topic_average / norm)
    matrix = numpy.asarray(topic_embeddings)
    if not numpy.all(numpy.isfinite(matrix)):
        raise ValueError("Local semantic catalog contains non-finite embeddings.")
    matrix.setflags(write=False)

    with _CACHE_LOCK:
        existing = _CATALOG_CACHE.get(cache_key)
        if existing is not None:
            return existing
        _CATALOG_CACHE[cache_key] = matrix
    return matrix


def classify_local_batch(
    items: list[dict],
    topic_catalog: list[dict],
    config: LocalSemanticConfig,
) -> list[dict]:
    validated_items = _validate_items(items)
    if not validated_items:
        return []
    _validate_config(config)
    catalog = _validate_catalog(topic_catalog)

    # Validation intentionally occurs on every call, before consulting either cache.
    validated_model = _validate_model(config.model_dir)
    runtime = _get_runtime(validated_model)
    numpy = runtime.numpy

    with runtime.lock:
        topic_embeddings = _catalog_embeddings(
            runtime,
            catalog,
            config.max_length,
        )
        nonempty = [
            (index, text.strip())
            for index, (_item_id, text) in enumerate(validated_items)
            if text.strip()
        ]
        message_embeddings = (
            _encode(
                runtime,
                [f"query: {text}" for _index, text in nonempty],
                config.max_length,
            )
            if nonempty
            else None
        )

    results = [
        {
            "id": item_id,
            "topic": None,
            "vertical": "",
            "confidence": 0.0,
            "margin": 0.0,
            "candidates": [],
        }
        for item_id, _text in validated_items
    ]
    if message_embeddings is None:
        return results

    similarities = message_embeddings @ topic_embeddings.T
    if similarities.shape != (len(nonempty), len(catalog.topics)):
        raise ValueError("Local semantic similarity matrix has an unexpected shape.")
    if not numpy.all(numpy.isfinite(similarities)):
        raise ValueError("Local semantic similarities contain non-finite values.")

    min_similarity = float(config.min_similarity)
    min_margin = float(config.min_margin)
    for row_index, (result_index, _text) in enumerate(nonempty):
        scores = similarities[row_index]
        ranking = numpy.argsort(-scores, kind="stable")
        best_index = int(ranking[0])
        top = float(scores[best_index])
        second = float(scores[int(ranking[1])]) if len(ranking) > 1 else 0.0
        confidence = min(1.0, max(0.0, top))
        margin = max(0.0, top - second)
        accepted = confidence >= min_similarity and margin >= min_margin
        candidates = [
            {
                "topic": catalog.topics[int(candidate_index)],
                "vertical": catalog.verticals[int(candidate_index)],
                "similarity": min(
                    1.0,
                    max(0.0, float(scores[int(candidate_index)])),
                ),
            }
            for candidate_index in ranking[:5]
        ]
        results[result_index] = {
            "id": validated_items[result_index][0],
            "topic": catalog.topics[best_index] if accepted else None,
            "vertical": catalog.verticals[best_index] if accepted else "",
            "confidence": confidence,
            "margin": margin,
            "candidates": candidates,
        }
    return results
