import hashlib
import json
import os
import shutil
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy

import local_semantic_topic_classifier as local
from local_semantic_topic_classifier import (
    LocalSemanticConfig,
    classify_local_batch,
)


MODEL_ID = "intfloat/multilingual-e5-small"
MODEL_REVISION = "614241f622f53c4eeff9890bdc4f31cfecc418b3"


class _Encoding:
    def __init__(self, code: int, length: int):
        self.ids = [code, code, *([99] * (length - 2))]
        self.attention_mask = [1, 1, *([0] * (length - 2))]
        self.type_ids = [0] * length


class _Tokenizer:
    def __init__(self):
        self.texts = []
        self.length = None

    def token_to_id(self, token):
        return 0 if token == "[PAD]" else None

    def enable_truncation(self, *, max_length):
        self.length = max_length

    def enable_padding(self, *, length, pad_id, pad_token):
        self.length = length
        if pad_id != 0 or pad_token != "[PAD]":
            raise AssertionError("Unexpected padding configuration")

    def encode_batch(self, texts, *, add_special_tokens):
        self.texts.extend(texts)
        if not add_special_tokens:
            raise AssertionError("Special tokens must be enabled")
        encodings = []
        for text in texts:
            lowered = text.lower()
            if "opposite" in lowered:
                code = 44
            elif "ambiguous" in lowered:
                code = 33
            elif any(
                word in lowered
                for word in ("benefits", "retirement", "medical", "hr:")
            ):
                code = 11
            elif any(word in lowered for word in ("device", "laptop", "it:")):
                code = 22
            else:
                code = 33
            encodings.append(_Encoding(code, self.length))
        return encodings


class _Node:
    def __init__(self, name, tensor_type, shape):
        self.name = name
        self.type = tensor_type
        self.shape = shape


class _Session:
    def __init__(self, *, token_types=False, nonfinite=False, bad_shape=False):
        names = ["input_ids", "attention_mask"]
        if token_types:
            names.append("token_type_ids")
        self.inputs = [
            _Node(name, "tensor(int64)", ["batch", "sequence"])
            for name in names
        ]
        self.outputs = [
            _Node(
                "last_hidden_state",
                "tensor(float)",
                ["batch", "sequence", 2],
            )
        ]
        self.nonfinite = nonfinite
        self.bad_shape = bad_shape
        self.last_feeds = None

    def get_providers(self):
        return ["CPUExecutionProvider"]

    def get_inputs(self):
        return self.inputs

    def get_outputs(self):
        return self.outputs

    def run(self, output_names, feeds):
        self.last_feeds = feeds
        self.assert_int64(feeds)
        values = {
            11: numpy.array([2.0, 0.0]),
            22: numpy.array([0.0, 2.0]),
            33: numpy.array([1.0, 1.0]),
            44: numpy.array([-1.0, -1.0]),
            99: numpy.array([100.0, 100.0]),
        }
        embeddings = numpy.asarray(
            [
                [values[int(token)] for token in row]
                for row in feeds["input_ids"]
            ],
            dtype=numpy.float32,
        )
        if self.nonfinite:
            embeddings[0, 0, 0] = numpy.nan
        if self.bad_shape:
            embeddings = embeddings[:, 0, :]
        return [embeddings]

    @staticmethod
    def assert_int64(feeds):
        for name, value in feeds.items():
            if value.dtype != numpy.int64:
                raise AssertionError(f"{name} was not int64")


class LocalSemanticTopicClassifierTests(unittest.TestCase):
    def setUp(self):
        self.model_dir = Path(__file__).with_name(
            ".local-semantic-topic-classifier-tests"
        )
        shutil.rmtree(self.model_dir, ignore_errors=True)
        self.model_dir.mkdir()
        (self.model_dir / "model_quint8_avx2.onnx").write_bytes(b"onnx-model")
        (self.model_dir / "tokenizer.json").write_bytes(b'{"tokenizer":true}')
        self._write_manifest()
        self.catalog = [
            {
                "topic": "Benefits & Retirement",
                "vertical": "HR",
                "examples": ["medical plan", "retirement contribution"],
            },
            {
                "topic": "Device & Hardware",
                "vertical": "IT",
                "examples": ["broken laptop", "company device"],
            },
        ]
        self.config = LocalSemanticConfig(
            model_dir=self.model_dir,
            min_similarity=0.6,
            min_margin=0.1,
            max_length=4,
        )
        with local._CACHE_LOCK:
            local._RUNTIME_CACHE.clear()
            local._CATALOG_CACHE.clear()

    def tearDown(self):
        shutil.rmtree(self.model_dir, ignore_errors=True)

    def _write_manifest(self, *, model_id=MODEL_ID, revision=MODEL_REVISION):
        files = {}
        for name in ("model_quint8_avx2.onnx", "tokenizer.json"):
            content = (self.model_dir / name).read_bytes()
            files[name] = {
                "size": len(content),
                "sha256": hashlib.sha256(content).hexdigest(),
            }
        (self.model_dir / "model-manifest.json").write_text(
            json.dumps(
                {
                    "model_id": model_id,
                    "revision": revision,
                    "files": files,
                }
            ),
            encoding="utf-8",
        )

    def _runtime(self, *, token_types=False, nonfinite=False, bad_shape=False):
        tokenizer = _Tokenizer()
        session = _Session(
            token_types=token_types,
            nonfinite=nonfinite,
            bad_shape=bad_shape,
        )
        return local._Runtime(
            tokenizer=tokenizer,
            session=session,
            numpy=numpy,
            input_names=frozenset(node.name for node in session.inputs),
            output_name="last_hidden_state",
            fingerprint=(str(self.model_dir.resolve()), self.id()),
            lock=local.threading.RLock(),
        )

    def test_manifest_identity_size_and_hash_are_enforced(self):
        self._write_manifest(model_id="wrong/model")
        with self.assertRaisesRegex(ValueError, "manifest mismatch"):
            local._validate_model(self.model_dir)

        self._write_manifest()
        manifest_path = self.model_dir / "model-manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["files"]["tokenizer.json"]["size"] += 1
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "size mismatch"):
            local._validate_model(self.model_dir)

        self._write_manifest()
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["files"]["tokenizer.json"]["sha256"] = "0" * 64
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "SHA-256 mismatch"):
            local._validate_model(self.model_dir)

    def test_cpu_provider_only_and_tokenizer_from_file(self):
        validated = local._validate_model(self.model_dir)
        tokenizer = _Tokenizer()
        from_file = Mock(return_value=tokenizer)
        inference_session = Mock(return_value=_Session())
        modules = {
            "numpy": numpy,
            "tokenizers": SimpleNamespace(
                Tokenizer=SimpleNamespace(from_file=from_file)
            ),
            "onnxruntime": SimpleNamespace(InferenceSession=inference_session),
        }
        with patch.object(
            local.importlib,
            "import_module",
            side_effect=lambda name: modules[name],
        ):
            runtime = local._load_runtime(validated)

        from_file.assert_called_once_with(str(validated.tokenizer_path))
        inference_session.assert_called_once_with(
            str(validated.model_path),
            providers=["CPUExecutionProvider"],
        )
        self.assertEqual(
            runtime.input_names,
            frozenset({"input_ids", "attention_mask"}),
        )

    def test_query_prefix_pooling_normalization_ranking_and_order(self):
        runtime = self._runtime(token_types=True)
        with patch.object(local, "_get_runtime", return_value=runtime):
            results = classify_local_batch(
                [
                    {"id": "m2", "text": "broken laptop"},
                    {"id": "empty", "text": "   "},
                    {"id": "m1", "text": "medical coverage"},
                ],
                self.catalog,
                self.config,
            )

        self.assertEqual([row["id"] for row in results], ["m2", "empty", "m1"])
        self.assertEqual(results[0]["topic"], "Device & Hardware")
        self.assertEqual(results[0]["vertical"], "IT")
        self.assertEqual(results[1]["topic"], None)
        self.assertEqual(results[1]["confidence"], 0.0)
        self.assertEqual(results[2]["topic"], "Benefits & Retirement")
        self.assertEqual(
            results[2]["candidates"][0]["topic"],
            "Benefits & Retirement",
        )
        self.assertLessEqual(len(results[2]["candidates"]), 5)
        self.assertAlmostEqual(results[0]["confidence"], 1.0, places=6)
        self.assertGreater(results[0]["margin"], 0)
        self.assertTrue(runtime.tokenizer.texts)
        self.assertTrue(
            all(text.startswith("query: ") for text in runtime.tokenizer.texts)
        )
        self.assertGreaterEqual(
            sum("Benefits & Retirement" in text for text in runtime.tokenizer.texts),
            3,
        )
        self.assertIn("token_type_ids", runtime.session.last_feeds)

    def test_similarity_and_margin_thresholds_abstain(self):
        runtime = self._runtime()
        with patch.object(local, "_get_runtime", return_value=runtime):
            low_similarity = classify_local_batch(
                [{"id": "low", "text": "ambiguous request"}],
                self.catalog,
                LocalSemanticConfig(self.model_dir, 0.8, 0.0, 4),
            )
        self.assertIsNone(low_similarity[0]["topic"])
        self.assertAlmostEqual(
            low_similarity[0]["confidence"],
            2**-0.5,
            places=6,
        )

        runtime = self._runtime()
        with patch.object(local, "_get_runtime", return_value=runtime):
            low_margin = classify_local_batch(
                [{"id": "margin", "text": "ambiguous request"}],
                self.catalog,
                LocalSemanticConfig(self.model_dir, 0.5, 0.1, 4),
            )
        self.assertIsNone(low_margin[0]["topic"])
        self.assertEqual(low_margin[0]["margin"], 0.0)

        runtime = self._runtime()
        with patch.object(local, "_get_runtime", return_value=runtime):
            negative = classify_local_batch(
                [{"id": "negative", "text": "opposite request"}],
                self.catalog,
                LocalSemanticConfig(self.model_dir, 0.0, 0.0, 4),
            )
        self.assertEqual(negative[0]["confidence"], 0.0)
        self.assertGreaterEqual(negative[0]["margin"], 0.0)

    def test_token_type_ids_are_omitted_unless_model_declares_them(self):
        runtime = self._runtime(token_types=False)
        with patch.object(local, "_get_runtime", return_value=runtime):
            classify_local_batch(
                [{"id": "m1", "text": "medical plan"}],
                self.catalog,
                self.config,
            )
        self.assertNotIn("token_type_ids", runtime.session.last_feeds)
        self.assertEqual(
            set(runtime.session.last_feeds),
            {"input_ids", "attention_mask"},
        )

    def test_changed_artifact_is_revalidated_before_cached_runtime(self):
        runtime = self._runtime()
        with patch.object(local, "_get_runtime", return_value=runtime) as loader:
            classify_local_batch(
                [{"id": "m1", "text": "medical plan"}],
                self.catalog,
                self.config,
            )
            tokenizer_path = self.model_dir / "tokenizer.json"
            original_size = tokenizer_path.stat().st_size
            tokenizer_path.write_bytes(b"x" * original_size)
            with self.assertRaisesRegex(ValueError, "SHA-256 mismatch"):
                classify_local_batch(
                    [{"id": "m2", "text": "laptop"}],
                    self.catalog,
                    self.config,
                )
        loader.assert_called_once()

    def test_missing_dependencies_are_reported_clearly(self):
        validated = local._validate_model(self.model_dir)
        with patch.object(
            local.importlib,
            "import_module",
            side_effect=ImportError("not installed"),
        ):
            with self.assertRaisesRegex(ValueError, "optional dependencies"):
                local._load_runtime(validated)

    @unittest.skipUnless(
        os.environ.get("ESS_LOCAL_MODEL_DIR"),
        "Set ESS_LOCAL_MODEL_DIR to run the real local-model test.",
    )
    def test_real_model_classifies_multilingual_ess_examples(self):
        model_dir = Path(os.environ["ESS_LOCAL_MODEL_DIR"])
        catalog = [
            {
                "topic": "Room & Desk Booking",
                "vertical": "Facilities",
                "examples": [
                    "book a room",
                    "reserve a room",
                    "reservar una sala",
                    "预订会议室",
                ],
            },
            {
                "topic": "Network & Connectivity",
                "vertical": "IT",
                "examples": [
                    "vpn",
                    "remote access",
                    "problema de red",
                    "虚拟专用网络",
                ],
            },
            {
                "topic": "Expenses & Reimbursement",
                "vertical": "Finance",
                "examples": [
                    "expense report",
                    "reimbursement",
                    "informe de gastos",
                    "费用报销",
                ],
            },
        ]
        results = classify_local_batch(
            [
                {
                    "id": "en",
                    "text": "Reserve a conference room for tomorrow.",
                },
                {
                    "id": "es",
                    "text": "No puedo conectarme a la red corporativa.",
                },
                {
                    "id": "zh",
                    "text": "如何提交费用报销和收据？",
                },
            ],
            catalog,
            LocalSemanticConfig(model_dir, 0.82, 0.01, 256),
        )
        self.assertEqual(
            [row["topic"] for row in results],
            [
                "Room & Desk Booking",
                "Network & Connectivity",
                "Expenses & Reimbursement",
            ],
        )

    def test_nonfinite_and_bad_output_shapes_are_rejected(self):
        for runtime, message in (
            (self._runtime(nonfinite=True), "non-finite embeddings"),
            (self._runtime(bad_shape=True), "unexpected token-embedding shape"),
        ):
            with self.subTest(message=message), patch.object(
                local,
                "_get_runtime",
                return_value=runtime,
            ):
                with self.assertRaisesRegex(ValueError, message):
                    classify_local_batch(
                        [{"id": "m1", "text": "medical plan"}],
                        self.catalog,
                        self.config,
                    )

    def test_malformed_inputs_catalog_and_thresholds_are_rejected(self):
        bad_cases = (
            (
                [{"id": "same", "text": "a"}, {"id": "same", "text": "b"}],
                self.catalog,
                self.config,
                "duplicate ID",
            ),
            (
                [{"id": "", "text": "a"}],
                self.catalog,
                self.config,
                "unknown or invalid ID",
            ),
            (
                [{"id": "a", "text": "a"}],
                [{"topic": "A", "vertical": "V", "examples": "not-a-list"}],
                self.config,
                "examples must be a list",
            ),
            (
                [{"id": "a", "text": "a"}],
                [
                    {"topic": "A", "vertical": "V", "examples": []},
                    {"topic": "A", "vertical": "V", "examples": []},
                ],
                self.config,
                "duplicate topic",
            ),
            (
                [{"id": "a", "text": "a"}],
                self.catalog,
                LocalSemanticConfig(self.model_dir, float("nan"), 0.1),
                "min_similarity",
            ),
            (
                [{"id": "a", "text": "a"}],
                self.catalog,
                LocalSemanticConfig(self.model_dir, 0.1, 1.1),
                "min_margin",
            ),
        )
        for items, catalog, config, message in bad_cases:
            with self.subTest(message=message):
                with self.assertRaisesRegex(ValueError, message):
                    classify_local_batch(items, catalog, config)


if __name__ == "__main__":
    unittest.main()
