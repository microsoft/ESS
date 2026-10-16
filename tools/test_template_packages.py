import json
import unittest
import zipfile
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = {
    "ESS - Fabric V2.pbit": 247,
    "ESS Dashboard - Dynamic Topics (CSV) V18.pbit": 349,
    "ESS Dashboard - Dynamic Topics (Dataverse) V21.pbit": 350,
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
            "ESS Dashboard - Dynamic Topics (Dataverse) V21.pbit",
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
            / "ESS Dashboard - Dynamic Topics (Dataverse) V21.pbit"
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

    def test_v21_uses_agent_filter_without_registry_parameters(self):
        path = (
            ROOT
            / "ESS Dashboard - Dynamic Topics (Dataverse) V21.pbit"
        )
        with zipfile.ZipFile(path) as package:
            schema = json.loads(
                package.read("DataModelSchema").decode("utf-16-le")
            )
            unapplied = json.loads(
                package.read("UnappliedChanges").decode("utf-16-le")
            )
            report_json = {
                name: json.loads(
                    package.read(name).decode("utf-8-sig")
                )
                for name in package.namelist()
                if name.startswith("Report/definition/pages/")
                and "/visuals/" in name
                and name.endswith("/visual.json")
            }

        expressions = {
            item["name"]: item
            for item in schema["model"]["expressions"]
        }
        self.assertEqual(
            expressions["Agent Scope Mode"]["expression"],
            '"All Agents"',
        )
        self.assertEqual(
            expressions["Agent Registry JSON"]["expression"],
            "null",
        )
        self.assertNotIn(
            "IsParameterQuery=true",
            expressions["Agent Scope Mode"]["expression"],
        )
        self.assertNotIn(
            "IsParameterQuery=true",
            expressions["Agent Registry JSON"]["expression"],
        )

        queries = {
            item["name"]: item
            for item in unapplied["queries"]
        }
        self.assertTrue(queries["Agent Scope Mode"]["isHidden"])
        self.assertTrue(queries["Agent Registry JSON"]["isHidden"])

        tables = {
            table["name"]: table
            for table in schema["model"]["tables"]
        }
        transcript_query = tables["Agent Performance"][
            "partitions"
        ][0]["source"]["expression"]
        transcript_text = (
            "\n".join(transcript_query)
            if isinstance(transcript_query, list)
            else transcript_query
        )
        credits_query = tables["AgentCredits"]["partitions"][0][
            "source"
        ]["expression"]
        credits_text = (
            "\n".join(credits_query)
            if isinstance(credits_query, list)
            else credits_query
        )
        self.assertIn('"raw:agent:"', transcript_text)
        self.assertIn('"raw:agent:"', credits_text)
        self.assertNotIn('"raw:transcript:"', transcript_text)
        self.assertNotIn('"raw:credit:"', credits_text)

        agent_slicers = []
        for value in report_json.values():
            visual = value.get("visual", {})
            if (
                visual.get("visualType") == "slicer"
                and "Agent Bridge.AgentLabel"
                in json.dumps(value)
            ):
                agent_slicers.append(visual)
        self.assertEqual(len(agent_slicers), 8)
        self.assertEqual(
            {
                visual["syncGroup"]["groupName"]
                for visual in agent_slicers
            },
            {"BotFriendlyName"},
        )
        self.assertTrue(
            all(
                visual["syncGroup"]["filterChanges"]
                for visual in agent_slicers
            )
        )

    def test_v21_dataverse_source_uses_required_parameter_directly(self):
        path = (
            ROOT
            / "ESS Dashboard - Dynamic Topics (Dataverse) V21.pbit"
        )
        with zipfile.ZipFile(path) as package:
            schema = json.loads(
                package.read("DataModelSchema").decode("utf-16-le")
            )
            unapplied = json.loads(
                package.read("UnappliedChanges").decode("utf-16-le")
            )

        table = next(
            item
            for item in schema["model"]["tables"]
            if item["name"] == "Agent Performance"
        )
        schema_expression = table["partitions"][0]["source"]["expression"]
        unapplied_expression = next(
            item["text"]
            for item in unapplied["queries"]
            if item["name"] == "Agent Performance"
        )
        parameterized_source = (
            'Cds.Entities('
            '#"Dataverse Environment URL (required)", null)'
        )
        for expression in (schema_expression, unapplied_expression):
            text = (
                "\n".join(expression)
                if isinstance(expression, list)
                else expression
            )
            self.assertEqual(text.count(parameterized_source), 1)
            self.assertNotIn("Cds.Entities(_EnvUrl, null)", text)


if __name__ == "__main__":
    unittest.main()
