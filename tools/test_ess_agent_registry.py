import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from agent_registry import active_agent_keys, load_registry, resolve_alias
from update_agent_registry import MEASURE_NAMES, patch_pbit


class AgentRegistryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.repo = Path(__file__).resolve().parents[1]

    def test_sample_registry_resolves_all_identity_types(self) -> None:
        rows = load_registry(self.repo / "SampleData/agent-registry.csv")
        self.assertEqual({"ess-synthetic"}, active_agent_keys(rows, "ESS Safe"))
        self.assertEqual({"ess-synthetic"}, active_agent_keys(rows, "Selected Agents"))
        for alias_type, value in (
            ("TranscriptId", "F1D40245-F319-4E2D-8023-9E7B6F6456AC"),
            ("CreditId", "P_f1d40245-f319-4e2d-8023-9e7b6f6456ac"),
            ("M365Title", "t_SYNTHETIC-ESS-AGENT"),
        ):
            match = resolve_alias(rows, alias_type, value, {"ess-synthetic"})
            self.assertIsNotNone(match)
            self.assertEqual("ess-synthetic", match["AgentKey"])

    def test_direct_pbit_patch_is_idempotent_and_canonical(self) -> None:
        names = (
            "ESS Dashboard - Dynamic Topics (CSV) V18.pbit",
            "ESS Dashboard - Dynamic Topics (Dataverse) V19.pbit",
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            first = temp / "first"
            second = temp / "second"
            for name in names:
                patch_pbit(self.repo / name, first / name)
                patch_pbit(first / name, second / name)
                with zipfile.ZipFile(first / name) as archive:
                    first_schema_raw = archive.read("DataModelSchema")
                    first_unapplied_raw = archive.read("UnappliedChanges")
                    schema = json.loads(first_schema_raw.decode("utf-16-le"))
                    unapplied = json.loads(first_unapplied_raw.decode("utf-16-le"))
                with zipfile.ZipFile(second / name) as archive:
                    self.assertEqual(first_schema_raw, archive.read("DataModelSchema"))
                    self.assertEqual(first_unapplied_raw, archive.read("UnappliedChanges"))

                model = schema["model"]
                expressions = [item["name"] for item in model["expressions"]]
                self.assertEqual(len(expressions), len(set(expressions)))
                for expected in ("Agent Scope Mode", "Agent Registry JSON", "AgentRegistry"):
                    self.assertEqual(1, expressions.count(expected))

                tables = {table["name"]: table for table in model["tables"]}
                for table_name in ("Agent Performance", "AgentCredits", "ConversationFeedback"):
                    columns = [column["name"] for column in tables[table_name]["columns"]]
                    self.assertEqual(1, columns.count("AgentKey"))
                    self.assertEqual(1, columns.count("AgentLabel"))

                bridge_expression = tables["Agent Bridge"]["partitions"][0]["source"]["expression"]
                bridge_text = (
                    "\n".join(bridge_expression)
                    if isinstance(bridge_expression, list)
                    else bridge_expression
                )
                self.assertIn("ConversationFeedback[AgentKey]", bridge_text)

                relationships = model["relationships"]
                endpoints = {
                    (
                        item["fromTable"],
                        item["fromColumn"],
                        item["toTable"],
                        item["toColumn"],
                    )
                    for item in relationships
                }
                self.assertIn(
                    ("Agent Performance", "AgentKey", "Agent Bridge", "AgentKey"),
                    endpoints,
                )
                self.assertIn(
                    ("AgentCredits", "AgentKey", "Agent Bridge", "AgentKey"),
                    endpoints,
                )
                self.assertIn(
                    ("ConversationFeedback", "AgentKey", "Agent Bridge", "AgentKey"),
                    endpoints,
                )

                measures = {
                    (table["name"], measure["name"]): measure["expression"]
                    for table in model["tables"]
                    for measure in table.get("measures", [])
                }
                for key in MEASURE_NAMES:
                    expression = measures[key]
                    text = "\n".join(expression) if isinstance(expression, list) else expression
                    self.assertNotIn("'Agent Performance'[BotId]", text)
                    self.assertNotIn("AgentCredits[AgentGUID]", text)

                query_names = [query["name"] for query in unapplied["queries"]]
                self.assertEqual(len(query_names), len(set(query_names)))
                queries = {
                    query["name"]: (
                        "\n".join(query["text"])
                        if isinstance(query["text"], list)
                        else query["text"]
                    )
                    for query in unapplied["queries"]
                }
                self.assertIn("Agent registry scope: begin", queries["Agent Performance"])
                self.assertIn("Agent registry scope: begin", queries["AgentCredits"])
                self.assertIn(
                    "Agent registry feedback resolution", queries["ConversationFeedback"]
                )
                self.assertIn(
                    'resolvedAgentKey = if matched then [MatchedAgentKey] else registryAgentKey',
                    queries["ConversationFeedback"],
                )
                self.assertNotIn("raw:feedback:", queries["ConversationFeedback"])
                self.assertIn(
                    'AliasType] = "TranscriptSchema"',
                    queries["Agent Performance"],
                )
                self.assertIn("BotSchemaName", queries["Agent Performance"])
                self.assertIn(
                    "No credit agents matched the selected Agent Registry scope",
                    queries["AgentCredits"],
                )
                registry_query = queries["AgentRegistry"]
                empty_schema = registry_query.split("SourceValue =", 1)[0]
                self.assertNotIn("AliasValueNormalized", empty_schema)
                self.assertEqual(
                    1,
                    registry_query.count(
                        '"AliasValueNormalized",\n        each NormalizeAlias'
                    ),
                )
                response_rate = next(
                    measure
                    for measure in tables["Agent Performance"]["measures"]
                    if measure["name"] == "Feedback Response Rate"
                )
                response_expression = response_rate["expression"]
                self.assertIn("Native transcript", response_expression)
                self.assertIn("Exact conversation match", response_expression)
                self.assertIn("DISTINCTCOUNT", response_expression)
                self.assertNotIn("No conversation identifier", response_expression)


if __name__ == "__main__":
    unittest.main()
