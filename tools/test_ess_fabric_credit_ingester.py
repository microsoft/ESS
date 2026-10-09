import csv
import hashlib
import json
import re
import unittest
import zipfile
from pathlib import Path


class FabricCreditIngesterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.repo = Path(__file__).resolve().parents[1]
        cls.notebook = json.loads(
            (
                cls.repo
                / "Fabric/notebooks/Copilot_Credit_Consumption_Ingester.ipynb"
            ).read_text(encoding="utf-8")
        )
        cls.cells = {
            index: "".join(cell.get("source", []))
            for index, cell in enumerate(cls.notebook["cells"])
        }
        helpers = cls.cells[5]
        start = helpers.index("def normalize_agent_alias")
        end = helpers.index("AGENT_REGISTRY_ROWS = load_agent_registry", start)
        cls.scope = {
            "re": re,
            "csv": csv,
            "hashlib": hashlib,
            "_SCOPE_MODES": {
                "ESS Safe",
                "Selected Agents",
                "All Agents",
            },
        }
        exec(helpers[start:end], cls.scope)

    @staticmethod
    def row(
        key: str,
        alias: str,
        *,
        is_ess: bool,
        selected: bool,
        environment: str,
        label: str | None = None,
    ) -> dict:
        normalized = str(alias).strip().strip("{}")
        if normalized.casefold().startswith("p_"):
            normalized = normalized[2:]
        return {
            "RegistryVersion": "1",
            "AgentKey": key,
            "AgentLabel": label or key,
            "IsEss": is_ess,
            "Selected": selected,
            "Enabled": True,
            "EnvironmentKey": environment,
            "EnvironmentName": environment,
            "EnvironmentUrl": "",
            "AliasType": "CreditId",
            "AliasValue": alias,
            "AliasValueNormalized": normalized.casefold(),
        }

    def test_default_scope_and_blank_output_prefix(self) -> None:
        scope = {}
        exec(self.cells[3], scope)
        self.assertEqual("ESS Safe", scope["AGENT_SCOPE_MODE"])
        self.assertEqual("", scope["OUTPUT_PREFIX"])
        self.assertEqual("overwrite", scope["WRITE_MODE"])
        self.assertNotIn("dbo.credit_consumption_agent", scope["REPORTS"])
        self.assertIn(
            "return f'{OUTPUT_PREFIX}.{name}' if OUTPUT_PREFIX else name",
            self.cells[5],
        )

    def test_credit_id_mapping_for_all_scope_modes(self) -> None:
        resolve = self.scope["resolve_credit_agent"]
        active = self.scope["active_agent_keys"]
        rows = [
            self.row(
                "ess-agent",
                "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
                is_ess=True,
                selected=False,
                environment="env-a",
                label="ESS Agent",
            ),
            self.row(
                "selected-agent",
                "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
                is_ess=False,
                selected=True,
                environment="env-b",
                label="Selected Agent",
            ),
        ]

        safe = resolve(
            "{AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}",
            "env-a",
            "",
            rows,
            active(rows, "ESS Safe"),
            "ESS Safe",
        )
        selected = resolve(
            "P_bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
            "env-b",
            "",
            rows,
            active(rows, "Selected Agents"),
            "Selected Agents",
        )
        raw = resolve(
            "cccccccc-cccc-cccc-cccc-cccccccccccc",
            "env-c",
            "",
            rows,
            active(rows, "All Agents"),
            "All Agents",
        )
        excluded = resolve(
            "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
            "env-b",
            "",
            rows,
            active(rows, "ESS Safe"),
            "ESS Safe",
        )

        self.assertEqual("ess-agent", safe["canonical_agent_key"])
        self.assertEqual("selected-agent", selected["canonical_agent_key"])
        self.assertEqual("RegistryMapped", selected["agent_mapping_status"])
        self.assertRegex(
            raw["canonical_agent_key"], r"^raw:creditid:[0-9a-f]{24}$"
        )
        self.assertEqual("RawAllAgents", raw["agent_mapping_status"])
        self.assertEqual("UnmappedQuarantined", excluded["agent_mapping_status"])

    def test_user_credit_mapping_never_infers_environment(self) -> None:
        resolve = self.scope["resolve_credit_agent"]
        active = self.scope["active_agent_keys"]
        shared = "dddddddd-dddd-dddd-dddd-dddddddddddd"
        rows = [
            self.row(
                "agent-a",
                shared,
                is_ess=True,
                selected=True,
                environment="env-a",
            ),
            self.row(
                "agent-b",
                shared,
                is_ess=True,
                selected=True,
                environment="env-b",
            ),
        ]
        with self.assertRaisesRegex(
            ValueError, "ambiguous without an environment"
        ):
            resolve(
                shared,
                "",
                "",
                rows,
                active(rows, "ESS Safe"),
                "ESS Safe",
            )
        unique = resolve(
            "eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee",
            "",
            "",
            [
                self.row(
                    "agent-unique",
                    "eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee",
                    is_ess=True,
                    selected=True,
                    environment="env-only-in-registry",
                )
            ],
            {"agent-unique"},
            "ESS Safe",
        )
        self.assertEqual("agent-unique", unique["canonical_agent_key"])
        self.assertEqual("", unique["canonical_environment_key"])
        self.assertNotIn("MAXX", self.cells[7])
        self.assertNotIn("Agent_Name", self.cells[5].split("def resolve_credit_agent", 1)[1])

    def test_decimals_and_overlapping_snapshot_protections(self) -> None:
        ingest = self.cells[7]
        self.assertIn("DecimalType(38, 6)", ingest)
        self.assertIn(
            "F.col(column).cast(DecimalType(38, 6))",
            ingest,
        )
        self.assertNotIn("cast('double')", ingest)
        self.assertIn("if len(matches) > 1:", ingest)
        self.assertIn("overlapping", ingest)
        self.assertIn("no existing delta", ingest.lower())
        self.assertIn("table was changed", ingest.lower())
        self.assertIn("and df.limit(1).count() > 0", ingest)
        self.assertNotIn("has headers but no data rows", ingest)

    def test_credit_quarantine_is_identifier_only(self) -> None:
        ingest = self.cells[7]
        quarantine_section = ingest[
            ingest.index("quarantine = (")
            : ingest.index("curated = mapped.filter", ingest.index("quarantine = ("))
        ]
        for sensitive in ("User_Id", "User_Email", "Agent_Name"):
            self.assertNotIn(f"'{sensitive}'", quarantine_section)
        for expected in (
            "raw_agent_id",
            "raw_environment_id",
            "raw_environment_name",
            "agent_mapping_status",
        ):
            self.assertIn(expected, quarantine_section)
        self.assertIn("credit_consumption_quarantine", ingest)

    def test_credit_pbit_columns_and_types(self) -> None:
        with zipfile.ZipFile(self.repo / "ESS - Fabric V2.pbit") as archive:
            schema = json.loads(
                archive.read("DataModelSchema").decode("utf-16-le")
            )
        tables = {table["name"]: table for table in schema["model"]["tables"]}
        for name in (
            "Credit Consumption (Agent)",
            "Credit Consumption (User)",
        ):
            table = tables[name]
            columns = {
                column["name"]: column["dataType"]
                for column in table["columns"]
            }
            self.assertEqual("string", columns["canonical_agent_key"])
            self.assertEqual("string", columns["canonical_environment_key"])
            expression = table["partitions"][0]["source"]["expression"]
            expression = (
                "\n".join(expression)
                if isinstance(expression, list)
                else expression
            )
            self.assertIn('{"canonical_agent_key", type text}', expression)
            self.assertIn('otherwise EmptyTable(Columns)', expression)
            self.assertIn(
                '{"Billed_credit", type number}'
                if name.endswith("(Agent)")
                else '{"Credits_used", type number}',
                expression,
            )

    def test_notebook_code_cells_compile(self) -> None:
        for index, cell in enumerate(self.notebook["cells"]):
            if cell.get("cell_type") == "code":
                compile(
                    "".join(cell.get("source", [])),
                    f"credit-cell-{index}",
                    "exec",
                )


if __name__ == "__main__":
    unittest.main()
