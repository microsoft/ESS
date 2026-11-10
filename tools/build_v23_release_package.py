#!/usr/bin/env python3
"""Build a model-complete, customer-safe V23 release ZIP."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import zipfile
from pathlib import Path


PACKAGE_NAME = "ESS-039417f-optional-fixes-V23.2"
MODEL_RELATIVE_DIR = Path("models") / "multilingual-e5-small"
MODEL_FILES = ("model_quint8_avx2.onnx", "tokenizer.json")
EXCLUDED_PARTS = {
    ".git",
    ".cache",
    ".idea",
    ".vscode",
    "__pycache__",
    "Generated Templates",
    "Topic-Tuner-Validation",
}
EXCLUDED_SUFFIXES = {".pyc", ".pyo", ".pbix"}
FORBIDDEN_NAMES = {
    "dataverse-setup.json",
    "semantic-conversation-topics.json",
    "semantic-review-evidence.json",
    "semantic-review-integrity.key",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_model(source_root: Path, model_dir: Path) -> dict:
    manifest_path = source_root / MODEL_RELATIVE_DIR / "model-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if (
        manifest.get("model_id") != "intfloat/multilingual-e5-small"
        or manifest.get("revision")
        != "614241f622f53c4eeff9890bdc4f31cfecc418b3"
    ):
        raise ValueError("The checked-in local model manifest is not pinned.")
    for name in MODEL_FILES:
        metadata = manifest["files"][name]
        path = model_dir / name
        if not path.is_file():
            raise ValueError(f"Local model pack is missing {name}.")
        if path.stat().st_size != metadata["size"]:
            raise ValueError(f"Local model pack size mismatch for {name}.")
        if sha256(path) != metadata["sha256"]:
            raise ValueError(f"Local model pack SHA-256 mismatch for {name}.")
    return manifest


def _git_files(source_root: Path) -> list[Path]:
    environment = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("GIT_CONFIG_")
    }
    status = subprocess.run(
        [
            "git",
            "-C",
            str(source_root),
            "status",
            "--porcelain",
            "--untracked-files=all",
        ],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )
    if status.returncode:
        raise ValueError(
            "Cannot inspect release source state: " + status.stderr.strip()
        )
    if status.stdout.strip():
        raise ValueError(
            "Release packaging requires a clean Git worktree. Commit or remove "
            "all modified, staged, and untracked files first."
        )
    completed = subprocess.run(
        [
            "git",
            "-C",
            str(source_root),
            "ls-files",
            "--cached",
            "-z",
        ],
        check=False,
        capture_output=True,
        env=environment,
    )
    if completed.returncode:
        raise ValueError(
            "Cannot enumerate release files from Git: "
            + completed.stderr.decode("utf-8", errors="replace").strip()
        )
    return [
        source_root / value.decode("utf-8")
        for value in completed.stdout.split(b"\0")
        if value
    ]


def release_files(source_root: Path) -> list[Path]:
    if not (source_root / ".git").exists():
        raise ValueError("Release packaging requires a Git working tree.")
    candidates = _git_files(source_root)
    files = []
    for path in candidates:
        if not path.is_file():
            continue
        relative = path.relative_to(source_root)
        if any(part in EXCLUDED_PARTS for part in relative.parts):
            continue
        if path.suffix.lower() in EXCLUDED_SUFFIXES:
            continue
        if path.name in FORBIDDEN_NAMES:
            raise ValueError(
                f"Customer-specific artifact cannot enter the release: {relative}"
            )
        files.append(path)
    return sorted(files, key=lambda path: path.relative_to(source_root).as_posix())


def _write_entry(
    archive: zipfile.ZipFile,
    source: Path,
    target: str,
) -> None:
    info = zipfile.ZipInfo(target, date_time=(2020, 1, 1, 0, 0, 0))
    info.compress_type = (
        zipfile.ZIP_STORED
        if source.suffix.lower() == ".onnx"
        else zipfile.ZIP_DEFLATED
    )
    info.external_attr = 0o644 << 16
    with source.open("rb") as handle, archive.open(info, "w") as output:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            output.write(chunk)


def build_release(
    source_root: Path,
    model_dir: Path,
    output_zip: Path,
) -> dict:
    source_root = source_root.resolve()
    model_dir = model_dir.resolve()
    validate_model(source_root, model_dir)
    files = release_files(source_root)
    virtual_files = {
        (
            Path(PACKAGE_NAME)
            / path.relative_to(source_root)
        ).as_posix(): path
        for path in files
    }
    for name in MODEL_FILES:
        target = (
            Path(PACKAGE_NAME)
            / MODEL_RELATIVE_DIR
            / name
        ).as_posix()
        if target in virtual_files:
            raise ValueError(f"Duplicate release path: {target}")
        virtual_files[target] = model_dir / name

    output_zip.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_zip.with_suffix(output_zip.suffix + ".tmp")
    temporary.unlink(missing_ok=True)
    try:
        with zipfile.ZipFile(
            temporary,
            "w",
            allowZip64=True,
        ) as archive:
            for target, source in sorted(virtual_files.items()):
                _write_entry(archive, source, target)
        with zipfile.ZipFile(temporary, "r") as archive:
            if archive.testzip() is not None:
                raise ValueError("The release ZIP failed integrity validation.")
            if len(archive.namelist()) != len(set(archive.namelist())):
                raise ValueError("The release ZIP contains duplicate paths.")
        os.replace(temporary, output_zip)
    finally:
        temporary.unlink(missing_ok=True)
    digest = sha256(output_zip)
    checksum = output_zip.with_suffix(output_zip.suffix + ".sha256")
    checksum.write_text(
        f"{digest}  {output_zip.name}\n",
        encoding="ascii",
    )
    return {
        "zip": str(output_zip),
        "sha256": digest,
        "bytes": output_zip.stat().st_size,
        "files": len(virtual_files),
        "checksum": str(checksum),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--source-root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
    )
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(
        json.dumps(
            build_release(
                args.source_root,
                args.model_dir,
                args.output,
            ),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
