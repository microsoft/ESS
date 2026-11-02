import json
import re
import unittest
import zipfile
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = {
    "ESS - Fabric V2.pbit": 247,
    "ESS Dashboard - Dynamic Topics (CSV) V18.pbit": 349,
    "ESS Dashboard - Dynamic Topics (Dataverse) V21 - Power BI Service - PUBLISH THIS.pbit": 349,
}
PUBLISHABLE_TEMPLATES = {
    "ESS Dashboard - Dynamic Topics (Dataverse) V21 - Power BI Service - PUBLISH THIS.pbit",
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
CUSTOMER_TEMPLATE_NAMES = (
    "ESS Dashboard - Dynamic Topics (Dataverse) V21 - Power BI Service - PUBLISH THIS.pbit",
)
FORBIDDEN_CUSTOMER_MARKERS = (
    "ess-synthetic",
    "qa payroll help",
    "orgfdba31c9",
    "savedqa.crm",
    "ess-full-python-qa",
    "qa-full-python",
    "how2demo-full-python",
    "20261102",
)
CUSTOMER_DATA_PATTERNS = (
    re.compile(r"https://[a-z0-9][a-z0-9-]*\.crm\d*\.dynamics\.com", re.IGNORECASE),
    re.compile(r"[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}", re.IGNORECASE),
    re.compile(r"[a-z]:\\Users\\", re.IGNORECASE),
    re.compile(r"\b(?:synthetic|fabricated)\b", re.IGNORECASE),
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
    def test_customer_templates_contain_no_loaded_or_synthetic_customer_data(self):
        for file_name in CUSTOMER_TEMPLATE_NAMES:
            with self.subTest(file_name=file_name), zipfile.ZipFile(ROOT / file_name) as package:
                names = package.namelist()
                self.assertNotIn("DataModel", names)
                decoded = []
                for name in names:
                    payload = package.read(name)
                    lowered = payload.lower()
                    for marker in FORBIDDEN_CUSTOMER_MARKERS:
                        self.assertNotIn(marker.encode("utf-8"), lowered, (name, marker))
                        self.assertNotIn(marker.encode("utf-16-le"), lowered, (name, marker))
                    if name in {"DataModelSchema", "UnappliedChanges"}:
                        decoded.append(payload.decode("utf-16-le"))
                    elif (
                        name.startswith("Report/definition/")
                        and name.endswith(".json")
                    ):
                        decoded.append(payload.decode("utf-8-sig"))
                searchable_text = "\n".join(decoded)
                for pattern in CUSTOMER_DATA_PATTERNS:
                    self.assertIsNone(pattern.search(searchable_text), pattern.pattern)

    def test_metric_glossary_preserves_rows_and_uses_valid_page_specific_sort(self):
        visual_path = (
            "Report/definition/pages/glossary001aabbcc06/visuals/"
            "glossary_table_001/visual.json"
        )
        for file_name in CUSTOMER_TEMPLATE_NAMES:
            with self.subTest(file_name=file_name), zipfile.ZipFile(ROOT / file_name) as package:
                schema = json.loads(package.read("DataModelSchema").decode("utf-16-le"))
                visual = json.loads(package.read(visual_path).decode("utf-8-sig"))

                glossary = next(
                    table
                    for table in schema["model"]["tables"]
                    if "glossary" in table["name"].casefold()
                )
                metric = next(column for column in glossary["columns"] if column["name"] == "Metric")
                self.assertNotIn("sortByColumn", metric)
                expression = glossary["partitions"][0]["source"]["expression"]
                lines = expression if isinstance(expression, list) else expression.splitlines()
                row_pattern = re.compile(
                    r'^\s*\{"(?:""|[^"])*", "(?:""|[^"])*", '
                    r'"(?:""|[^"])*", \d+, \d+\},?\s*$'
                )
                self.assertEqual(sum(bool(row_pattern.match(line)) for line in lines), 143)
                sort_fields = [
                    item["field"]["Column"]["Property"]
                    for item in visual["visual"]["query"]["sortDefinition"]["sort"]
                ]
                self.assertEqual(sort_fields, ["PageOrder", "MetricOrder"])
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
                    if file_name in PUBLISHABLE_TEMPLATES:
                        self.assertNotIn("UnappliedChanges", names)
                    else:
                        self.assertIn("UnappliedChanges", names)
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
            "ESS Dashboard - Dynamic Topics (Dataverse) V21 - Power BI Service - PUBLISH THIS.pbit",
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
            / "ESS Dashboard - Dynamic Topics (Dataverse) V21 - Power BI Service - PUBLISH THIS.pbit"
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
            / "ESS Dashboard - Dynamic Topics (Dataverse) V21 - Power BI Service - PUBLISH THIS.pbit"
        )
        with zipfile.ZipFile(path) as package:
            schema = json.loads(
                package.read("DataModelSchema").decode("utf-16-le")
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
        self.assertNotIn('"raw:transcript:"', transcript_text)
        self.assertIn("AgentKey", credits_text)
        self.assertIn("AgentLabel", credits_text)
        self.assertNotIn("File.Contents", credits_text)

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
            / "ESS Dashboard - Dynamic Topics (Dataverse) V21 - Power BI Service - PUBLISH THIS.pbit"
        )
        with zipfile.ZipFile(path) as package:
            schema = json.loads(
                package.read("DataModelSchema").decode("utf-16-le")
            )

        table = next(
            item
            for item in schema["model"]["tables"]
            if item["name"] == "Agent Performance"
        )
        schema_expression = table["partitions"][0]["source"]["expression"]
        parameterized_source = (
            'Cds.Entities('
            '#"Dataverse Environment URL (required)", null)'
        )
        text = (
            "\n".join(schema_expression)
            if isinstance(schema_expression, list)
            else schema_expression
        )
        self.assertEqual(text.count(parameterized_source), 1)
        self.assertNotIn("Cds.Entities(_EnvUrl, null)", text)


if __name__ == "__main__":
    unittest.main()
