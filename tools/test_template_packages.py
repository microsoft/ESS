import json
import unittest
import zipfile
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = {
    "ESS - Fabric V2.pbit": 247,
    "ESS Dashboard - Dynamic Topics (CSV) V18.pbit": 349,
    "ESS Dashboard - Dynamic Topics (Dataverse) V20.pbit": 350,
}
VISUAL_PATHS = (
    "Report/definition/pages/bizimpact001aabbcc03/visuals/"
    "bi_scatter_roi/visual.json",
    "Report/definition/pages/bizimpact001aabbcc03/visuals/"
    "bi_trend_value/visual.json",
)
BOOKMARK_PATH = (
    "Report/definition/bookmarks/"
    "0a1b2c3d4e5f60718294.bookmark.json"
)


def find_misplaced_display(value, path="$"):
    hits = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            if key == "display" and not path.endswith(".singleVisual"):
                hits.append(child_path)
            hits.extend(find_misplaced_display(child, child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            hits.extend(
                find_misplaced_display(child, f"{path}[{index}]")
            )
    return hits


class TemplatePackageTests(unittest.TestCase):
    def test_packages_are_valid_data_free_templates(self):
        for file_name, expected_entries in TEMPLATES.items():
            with self.subTest(file_name=file_name):
                with zipfile.ZipFile(ROOT / file_name) as package:
                    names = package.namelist()
                    self.assertIsNone(package.testzip())
                    self.assertEqual(len(names), expected_entries)
                    self.assertFalse(
                        [
                            name
                            for name, count in Counter(names).items()
                            if count > 1
                        ]
                    )
                    self.assertNotIn("DataModel", names)
                    self.assertFalse(
                        [
                            name
                            for name in names
                            if name.lower().endswith((".pbir", ".pbism"))
                            or "identity" in name.lower()
                        ]
                    )
                    json.loads(
                        package.read("DataModelSchema").decode(
                            "utf-16-le"
                        )
                    )
                    json.loads(
                        package.read("UnappliedChanges").decode(
                            "utf-16-le"
                        )
                    )
                    for name in names:
                        if (
                            name.startswith("Report/definition/")
                            and name.endswith(".json")
                        ):
                            json.loads(
                                package.read(name).decode("utf-8-sig")
                            )

    def test_report_json_has_no_misplaced_display_properties(self):
        for file_name in TEMPLATES:
            with self.subTest(file_name=file_name):
                with zipfile.ZipFile(ROOT / file_name) as package:
                    hits = []
                    for name in package.namelist():
                        if (
                            name.startswith("Report/definition/")
                            and name.endswith(".json")
                        ):
                            value = json.loads(
                                package.read(name).decode("utf-8-sig")
                            )
                            hits.extend(
                                f"{name}: {path}"
                                for path in find_misplaced_display(value)
                            )
                    self.assertEqual(hits, [])

    def test_hidden_visual_and_bookmark_state_is_preserved(self):
        for file_name in (
            "ESS Dashboard - Dynamic Topics (CSV) V18.pbit",
            "ESS Dashboard - Dynamic Topics (Dataverse) V20.pbit",
        ):
            with self.subTest(file_name=file_name):
                with zipfile.ZipFile(ROOT / file_name) as package:
                    for name in VISUAL_PATHS:
                        value = json.loads(
                            package.read(name).decode("utf-8-sig")
                        )
                        self.assertTrue(value["isHidden"])
                        self.assertNotIn("display", value["visual"])

        with zipfile.ZipFile(
            ROOT
            / "ESS Dashboard - Dynamic Topics (Dataverse) V20.pbit"
        ) as package:
            bookmark = json.loads(
                package.read(BOOKMARK_PATH).decode("utf-8-sig")
            )
        container = bookmark["explorationState"]["sections"][
            "improveopp001aabbcc07"
        ]["visualContainers"]["improve_slicer_agent"]
        self.assertNotIn("display", container)
        self.assertEqual(
            container["singleVisual"]["display"],
            {"mode": "hidden"},
        )


if __name__ == "__main__":
    unittest.main()
