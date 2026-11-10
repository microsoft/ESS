import hashlib
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from build_v23_release_package import (
    MODEL_RELATIVE_DIR,
    PACKAGE_NAME,
    build_release,
)


class BuildV23ReleasePackageTests(unittest.TestCase):
    def create_fixture(self, root: Path) -> tuple[Path, Path]:
        source = root / "source"
        model = root / "model"
        source.mkdir()
        model.mkdir()
        (source / "README.md").write_text("customer package\n", encoding="utf-8")
        manifest_dir = source / MODEL_RELATIVE_DIR
        manifest_dir.mkdir(parents=True)
        (manifest_dir / "LICENSE").write_text("MIT\n", encoding="utf-8")
        files = {}
        for name, payload in (
            ("model_quint8_avx2.onnx", b"verified-model"),
            ("tokenizer.json", b'{"verified":true}'),
        ):
            (model / name).write_bytes(payload)
            files[name] = {
                "size": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
            }
        (manifest_dir / "model-manifest.json").write_text(
            json.dumps(
                {
                    "model_id": "intfloat/multilingual-e5-small",
                    "revision": (
                        "614241f622f53c4eeff9890bdc4f31cfecc418b3"
                    ),
                    "files": files,
                }
            ),
            encoding="utf-8",
        )
        return source, model

    def test_builds_model_complete_deterministic_zip(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, model = self.create_fixture(root)
            output = root / "release.zip"
            first = build_release(source, model, output)
            first_bytes = output.read_bytes()
            second = build_release(source, model, output)

            self.assertEqual(first["sha256"], second["sha256"])
            self.assertEqual(output.read_bytes(), first_bytes)
            with zipfile.ZipFile(output) as archive:
                self.assertIsNone(archive.testzip())
                names = set(archive.namelist())
                self.assertIn(f"{PACKAGE_NAME}/README.md", names)
                self.assertIn(
                    f"{PACKAGE_NAME}/models/multilingual-e5-small/"
                    "model_quint8_avx2.onnx",
                    names,
                )
                self.assertIn(
                    f"{PACKAGE_NAME}/models/multilingual-e5-small/"
                    "tokenizer.json",
                    names,
                )

    def test_rejects_customer_specific_artifacts(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, model = self.create_fixture(root)
            (source / "semantic-conversation-topics.json").write_text(
                "[]",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "cannot enter"):
                build_release(source, model, root / "release.zip")


if __name__ == "__main__":
    unittest.main()
