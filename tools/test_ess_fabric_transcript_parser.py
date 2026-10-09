import json
import re
import unittest
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from update_fabric_agent_registry import (
    IDENTITY_COLUMNS,
    catalogue_query,
    patch_feedback_query,
    patch_m_ensured,
)


class FabricTranscriptParserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.repo = Path(__file__).resolve().parents[1]
        cls.notebook = json.loads(
            (
                cls.repo
                / "Fabric/notebooks/Copilot_Agent_Transcript_Parser.ipynb"
            ).read_text(encoding="utf-8")
        )
        cls.cells = {
            index: "".join(cell.get("source", []))
            for index, cell in enumerate(cls.notebook["cells"])
        }

        runtime = cls.cells[8]
        start = runtime.index("# === AGENT REGISTRY RUNTIME (generated) ===")
        end = runtime.index(
            "AGENT_REGISTRY_ROWS = load_agent_registry", start
        )
        cls.registry_scope = {
            "pd": pd,
            "re": re,
            "json": json,
            "_AGENT_SCOPE_MODES": {
                "ESS Safe",
                "Selected Agents",
                "All Agents",
            },
        }
        exec(runtime[start:end], cls.registry_scope)

        feedback = cls.cells[27]
        start = feedback.index("# --- Unified feedback events:")
        end = feedback.index(
            "user_feedback, user_feedback_quarantine =", start
        )
        cls.feedback_source = feedback[start:end]

    @staticmethod
    def registry_row(
        key: str,
        alias_type: str,
        alias_value: str,
        *,
        is_ess: bool,
        selected: bool,
        environment: str,
        environment_url: str,
        label: str | None = None,
    ) -> dict:
        return {
            "RegistryVersion": "1",
            "AgentKey": key,
            "AgentLabel": label or key,
            "IsEss": is_ess,
            "Selected": selected,
            "Enabled": True,
            "EnvironmentKey": environment,
            "EnvironmentName": environment,
            "EnvironmentUrl": environment_url,
            "AliasType": alias_type,
            "AliasValue": alias_value,
            "AliasValueNormalized": (
                str(alias_value).strip().strip("{}").casefold()
            ),
        }

    @classmethod
    def mixed_registry(cls) -> list[dict]:
        return [
            cls.registry_row(
                "ess-agent",
                "TranscriptId",
                "11111111-1111-1111-1111-111111111111",
                is_ess=True,
                selected=False,
                environment="env-ess",
                environment_url="https://ess.example.invalid",
                label="ESS Agent",
            ),
            cls.registry_row(
                "selected-agent",
                "TranscriptId",
                "22222222-2222-2222-2222-222222222222",
                is_ess=False,
                selected=True,
                environment="env-selected",
                environment_url="https://selected.example.invalid",
                label="Selected Agent",
            ),
            cls.registry_row(
                "ess-agent",
                "M365Title",
                "T_ess-title",
                is_ess=True,
                selected=False,
                environment="env-ess",
                environment_url="https://ess.example.invalid",
                label="ESS Agent",
            ),
        ]

    @staticmethod
    def transcript_frame() -> pd.DataFrame:
        return pd.DataFrame(
            [
                {
                    "conversationtranscriptid": "same-conversation",
                    "agent_schema_hint": "schema_ess",
                    "botid": "{11111111-1111-1111-1111-111111111111}",
                    "bot_name": "ESS Raw",
                    "SourceEnvironment": "https://ess.example.invalid",
                    "content_json": {"activities": []},
                },
                {
                    "conversationtranscriptid": "same-conversation",
                    "agent_schema_hint": "schema_selected",
                    "botid": "22222222-2222-2222-2222-222222222222",
                    "bot_name": "Selected Raw",
                    "SourceEnvironment": "https://selected.example.invalid",
                    "content_json": {"activities": []},
                },
                {
                    "conversationtranscriptid": "unmapped-conversation",
                    "agent_schema_hint": "schema_unmapped",
                    "botid": "33333333-3333-3333-3333-333333333333",
                    "bot_name": "Unmapped Raw",
                    "SourceEnvironment": "https://unmapped.example.invalid",
                    "content_json": {"activities": []},
                },
            ]
        )

    def test_incremental_and_registry_defaults(self) -> None:
        config = self.cells[3]
        scope = {}
        exec(config, scope)
        self.assertEqual("merge", scope["WRITE_MODE"])
        self.assertEqual(7, scope["LOOKBACK_DAYS"])
        self.assertEqual("", scope["OUTPUT_PREFIX"])
        self.assertEqual("conversationtranscripts_raw", scope["RAW_TABLE"])
        self.assertEqual(
            "/lakehouse/default/Files/config/agent-registry.csv",
            scope["AGENT_REGISTRY_FILE"],
        )
        self.assertEqual("ESS Safe", scope["AGENT_SCOPE_MODE"])

        invalid = config.replace(
            "AGENT_SCOPE_MODE = 'ESS Safe'",
            "AGENT_SCOPE_MODE = 'unsafe'",
            1,
        )
        with self.assertRaisesRegex(ValueError, "must be exactly one of"):
            exec(invalid, {})

        unsafe = config.replace(
            "WRITE_MODE    = 'merge'", "WRITE_MODE    = 'overwrite'", 1
        )
        with self.assertRaisesRegex(ValueError, "Unsafe configuration"):
            exec(unsafe, {})

    def test_all_scope_modes_and_mixed_agents(self) -> None:
        scope_rows = self.registry_scope["scope_transcript_rows"]
        registry = self.mixed_registry()
        frame = self.transcript_frame()

        safe, _ = scope_rows(frame, registry, "ESS Safe")
        selected, _ = scope_rows(frame, registry, "Selected Agents")
        all_agents, _ = scope_rows(frame, registry, "All Agents")

        self.assertEqual(["ess-agent"], safe["canonical_agent_key"].tolist())
        self.assertEqual(
            ["selected-agent"], selected["canonical_agent_key"].tolist()
        )
        self.assertEqual(3, len(all_agents))
        self.assertEqual(
            1,
            int(
                (
                    all_agents["agent_mapping_status"] == "RawAllAgents"
                ).sum()
            ),
        )
        raw_key = all_agents.loc[
            all_agents["agent_mapping_status"] == "RawAllAgents",
            "canonical_agent_key",
        ].iloc[0]
        self.assertRegex(raw_key, r"^raw:transcriptid:[0-9a-f]{24}$")

    def test_csv_metadata_resolves_transcript_agent(self) -> None:
        frame = pd.DataFrame(
            [
                {
                    "conversationtranscriptid": "metadata-conversation",
                    "metadata": json.dumps(
                        {
                            "BotId": "11111111-1111-1111-1111-111111111111",
                            "BotName": "ESS Metadata Agent",
                        }
                    ),
                    "agent_schema_hint": None,
                    "SourceEnvironment": "",
                    "content_json": {"activities": []},
                }
            ]
        )
        scoped, _ = self.registry_scope["scope_transcript_rows"](
            frame, self.mixed_registry(), "ESS Safe"
        )
        self.assertEqual(["ess-agent"], scoped["canonical_agent_key"].tolist())
        self.assertEqual(
            ["11111111-1111-1111-1111-111111111111"],
            scoped["raw_agent_id"].tolist(),
        )

    def test_safe_and_selected_fail_closed_without_matches(self) -> None:
        scope_rows = self.registry_scope["scope_transcript_rows"]
        registry = self.mixed_registry()
        unmapped = self.transcript_frame().iloc[[2]].copy()
        for mode in ("ESS Safe", "Selected Agents"):
            with self.assertRaisesRegex(ValueError, "No transcript agents matched"):
                scope_rows(unmapped, registry, mode)

    def test_empty_source_is_safe_in_every_scope(self) -> None:
        scope_rows = self.registry_scope["scope_transcript_rows"]
        empty = self.transcript_frame().iloc[0:0].copy()
        for mode in ("ESS Safe", "Selected Agents", "All Agents"):
            scoped, active = scope_rows(empty, self.mixed_registry(), mode)
            self.assertTrue(scoped.empty)
            self.assertGreaterEqual(len(active), 1)

    def test_duplicate_conversation_ids_are_environment_aware(self) -> None:
        scope_rows = self.registry_scope["scope_transcript_rows"]
        scoped, _ = scope_rows(
            self.transcript_frame().iloc[:2],
            self.mixed_registry(),
            "All Agents",
        )
        self.assertEqual(2, scoped["conversation_natural_key"].nunique())
        self.assertEqual(
            {
                "env-ess|same-conversation",
                "env-selected|same-conversation",
            },
            set(scoped["conversation_natural_key"]),
        )

        duplicate = pd.concat(
            [
                self.transcript_frame().iloc[[0]],
                self.transcript_frame().iloc[[0]],
            ],
            ignore_index=True,
        )
        with self.assertRaisesRegex(
            ValueError, "duplicate environment-aware conversation keys"
        ):
            scope_rows(duplicate, self.mixed_registry(), "All Agents")

    def test_scoped_identity_reaches_every_transcript_fact(self) -> None:
        parsed, active = self.registry_scope["scope_transcript_rows"](
            self.transcript_frame().iloc[:2],
            self.mixed_registry(),
            "All Agents",
        )
        scope = dict(self.registry_scope)
        scope.update(
            {
                "datetime": datetime,
                "timezone": timezone,
                "json": json,
                "TEXT_TRUNCATE": 500,
                "parsed": parsed,
                "AGENT_REGISTRY_ROWS": self.mixed_registry(),
                "ACTIVE_AGENT_KEYS": active,
                "_clean_schema": lambda value: str(value).strip() if value else None,
            }
        )
        for index in (10, 12, 14, 16, 18, 20, 25):
            exec(self.cells[index], scope)
        for frame_name in (
            "sessions",
            "turns",
            "errors",
            "subagents",
            "agent_performance",
        ):
            frame = scope[frame_name]
            for column in (
                "conversation_natural_key",
                "canonical_agent_key",
                "canonical_agent_name",
                "canonical_environment_key",
                "raw_agent_id",
                "raw_agent_schema",
                "raw_agent_name",
            ):
                self.assertIn(column, frame.columns, (frame_name, column))
        self.assertEqual(2, len(scope["sessions"]))
        self.assertEqual(2, scope["sessions"]["conversation_natural_key"].nunique())
        self.assertEqual(2, len(scope["agent_performance"]))
        self.assertEqual(
            {"ess-agent", "selected-agent"},
            set(scope["agent_dim"]["canonical_agent_key"]),
        )

    def test_m365_title_and_existing_canonical_feedback_resolution(self) -> None:
        scope = dict(self.registry_scope)
        scope.update(
            {
                "AGENT_REGISTRY_ROWS": self.mixed_registry(),
                "ACTIVE_AGENT_KEYS": {"ess-agent"},
            }
        )
        exec(self.feedback_source, scope)
        resolve = scope["resolve_external_feedback_agent"]
        sessions = pd.DataFrame(
            columns=[
                "conversation_id",
                "canonical_agent_key",
                "canonical_environment_key",
                "agent_mapping_status",
                "source_environment",
            ]
        )
        for raw_id in ("T_ESS-TITLE", "ess-agent"):
            identity, _ = resolve(
                pd.Series(
                    {
                        "AgentId": raw_id,
                        "AgentName": "Raw title",
                        "ConversationId": "",
                    }
                ),
                sessions,
                self.mixed_registry(),
                {"ess-agent"},
            )
            self.assertEqual("ess-agent", identity["canonical_agent_key"])
            self.assertEqual("RegistryMapped", identity["agent_mapping_status"])

    def test_unmapped_feedback_is_identifier_only_quarantine(self) -> None:
        scope = dict(self.registry_scope)
        scope.update(
            {
                "AGENT_REGISTRY_ROWS": self.mixed_registry(),
                "ACTIVE_AGENT_KEYS": {"ess-agent"},
            }
        )
        exec(self.feedback_source, scope)
        build = scope["build_user_feedback"]
        sessions = pd.DataFrame(
            columns=[
                "conversation_id",
                "feedback_verdict",
                "agent_mapping_status",
            ]
        )
        external = pd.DataFrame(
            [
                {
                    "FeedbackEventId": "mapped",
                    "ConversationId": "",
                    "AgentId": "T_ess-title",
                    "AgentName": "Raw title",
                    "Channel": "Microsoft 365 Copilot Chat",
                    "FeedbackSource": "Product Feedback",
                    "FeedbackVerdict": "Thumbs Up",
                    "FeedbackComment": "private comment",
                    "SubmittedUtc": "2026-01-01T00:00:00Z",
                    "UserId": "user-1",
                    "UserEmail": "person@example.invalid",
                    "Prompt": "private prompt",
                    "Response": "private response",
                    "App": "Microsoft 365 Copilot",
                    "AppLanguage": "en-US",
                    "Platform": "Copilot Chat",
                    "SourceType": "Product Feedback",
                    "AdditionalMetadata": "",
                    "MatchStatus": "",
                },
                {
                    "FeedbackEventId": "unmapped",
                    "ConversationId": "unknown-conversation",
                    "AgentId": "T_unknown",
                    "AgentName": "Unknown",
                    "Channel": "Microsoft 365 Copilot Chat",
                    "FeedbackSource": "Product Feedback",
                    "FeedbackVerdict": "Thumbs Down",
                    "FeedbackComment": "must not leak",
                    "SubmittedUtc": "2026-01-02T00:00:00Z",
                    "UserId": "user-2",
                    "UserEmail": "other@example.invalid",
                    "Prompt": "must not leak",
                    "Response": "must not leak",
                    "App": "Microsoft 365 Copilot",
                    "AppLanguage": "en-US",
                    "Platform": "Copilot Chat",
                    "SourceType": "Product Feedback",
                    "AdditionalMetadata": "",
                    "MatchStatus": "",
                },
            ]
        )
        existing = self.repo / "SampleData/feedback-events.csv"
        with patch.object(pd, "read_csv", return_value=external):
            feedback, quarantine = build(sessions, str(existing))
        self.assertEqual(["ess-agent"], feedback["canonical_agent_key"].tolist())
        self.assertEqual(["External|unmapped"], quarantine["Feedback Event Key"].tolist())
        self.assertEqual(
            "UnmappedQuarantined",
            quarantine.iloc[0]["agent_mapping_status"],
        )
        for sensitive in ("Comment", "Prompt", "Response", "User Id", "User Email"):
            self.assertNotIn(sensitive, quarantine.columns)

    def test_feedback_dedup_is_environment_and_agent_aware(self) -> None:
        scope = dict(self.registry_scope)
        scope.update(
            {
                "AGENT_REGISTRY_ROWS": self.mixed_registry(),
                "ACTIVE_AGENT_KEYS": {"ess-agent", "selected-agent"},
            }
        )
        exec(self.feedback_source, scope)
        sessions = pd.DataFrame(
            [
                {
                    "conversation_id": "shared-id",
                    "conversation_natural_key": "env-ess|shared-id",
                    "feedback_verdict": "Positive",
                    "feedback_comment": "",
                    "canonical_agent_key": "ess-agent",
                    "canonical_agent_name": "ESS Agent",
                    "canonical_environment_key": "env-ess",
                    "agent_mapping_status": "RegistryMapped",
                    "source_environment": "https://ess.example.invalid",
                    "session_start_utc": "2026-01-01T00:00:00Z",
                    "locale": "en-US",
                    "user_id_hash": "u1",
                    "first_user_prompt": "",
                    "raw_agent_id": "a1",
                    "raw_agent_schema": "",
                    "raw_agent_name": "ESS Agent",
                },
                {
                    "conversation_id": "shared-id",
                    "conversation_natural_key": "env-selected|shared-id",
                    "feedback_verdict": "Positive",
                    "feedback_comment": "",
                    "canonical_agent_key": "selected-agent",
                    "canonical_agent_name": "Selected Agent",
                    "canonical_environment_key": "env-selected",
                    "agent_mapping_status": "RegistryMapped",
                    "source_environment": "https://selected.example.invalid",
                    "session_start_utc": "2026-01-01T00:00:00Z",
                    "locale": "en-US",
                    "user_id_hash": "u2",
                    "first_user_prompt": "",
                    "raw_agent_id": "a2",
                    "raw_agent_schema": "",
                    "raw_agent_name": "Selected Agent",
                },
            ]
        )
        external = pd.DataFrame(
            [
                {
                    "FeedbackEventId": "external-1",
                    "ConversationId": "shared-id",
                    "AgentId": "T_ess-title",
                    "AgentName": "ESS Agent",
                    "Channel": "Microsoft 365 Copilot Chat",
                    "FeedbackSource": "Product Feedback",
                    "FeedbackVerdict": "Thumbs Up",
                    "FeedbackComment": "",
                    "SubmittedUtc": "2026-01-01T00:01:00Z",
                    "UserId": "",
                    "UserEmail": "",
                    "Prompt": "",
                    "Response": "",
                    "App": "Microsoft 365 Copilot",
                    "AppLanguage": "en-US",
                    "Platform": "Copilot Chat",
                    "SourceType": "Product Feedback",
                    "AdditionalMetadata": "",
                    "MatchStatus": "",
                }
            ]
        )
        with patch.object(pd, "read_csv", return_value=external):
            feedback, quarantine = scope["build_user_feedback"](
                sessions, str(self.repo / "SampleData/feedback-events.csv")
            )
        self.assertEqual(2, len(feedback))
        self.assertEqual(
            {"ess-agent", "selected-agent"},
            set(feedback["canonical_agent_key"]),
        )
        self.assertEqual(
            1,
            int(
                (
                    feedback["Feedback Source"] == "Conversation Transcript"
                ).sum()
            ),
        )
        self.assertEqual(0, len(quarantine))

    def test_canonical_feedback_does_not_choose_arbitrary_environment(self) -> None:
        same_agent_registry = [
            self.registry_row(
                "same-agent",
                "TranscriptId",
                "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
                is_ess=True,
                selected=True,
                environment="env-a",
                environment_url="https://a.example.invalid",
                label="Same Agent",
            ),
            self.registry_row(
                "same-agent",
                "TranscriptId",
                "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
                is_ess=True,
                selected=True,
                environment="env-b",
                environment_url="https://b.example.invalid",
                label="Same Agent",
            ),
        ]
        scope = dict(self.registry_scope)
        scope.update(
            {
                "AGENT_REGISTRY_ROWS": same_agent_registry,
                "ACTIVE_AGENT_KEYS": {"same-agent"},
            }
        )
        exec(self.feedback_source, scope)
        sessions = pd.DataFrame(
            [
                {
                    "conversation_id": "conv-a",
                    "conversation_natural_key": "env-a|conv-a",
                    "canonical_agent_key": "same-agent",
                    "canonical_environment_key": "env-a",
                    "agent_mapping_status": "RegistryMapped",
                    "source_environment": "https://a.example.invalid",
                },
                {
                    "conversation_id": "conv-b",
                    "conversation_natural_key": "env-b|conv-b",
                    "canonical_agent_key": "same-agent",
                    "canonical_environment_key": "env-b",
                    "agent_mapping_status": "RegistryMapped",
                    "source_environment": "https://b.example.invalid",
                },
            ]
        )
        identity, matched = scope["resolve_external_feedback_agent"](
            pd.Series(
                {
                    "AgentId": "same-agent",
                    "AgentName": "Same Agent",
                    "ConversationId": "conv-a",
                }
            ),
            sessions,
            same_agent_registry,
            {"same-agent"},
        )
        self.assertIsNotNone(matched)
        self.assertEqual("env-a|conv-a", matched["conversation_natural_key"])
        self.assertEqual("env-a", identity["canonical_environment_key"])

        identity, matched = scope["resolve_external_feedback_agent"](
            pd.Series(
                {
                    "AgentId": "same-agent",
                    "AgentName": "Same Agent",
                    "ConversationId": "",
                }
            ),
            sessions,
            same_agent_registry,
            {"same-agent"},
        )
        self.assertIsNone(matched)
        self.assertEqual("", identity["canonical_environment_key"])

        neutral_plus_scoped = [
            {**same_agent_registry[0], "EnvironmentKey": ""},
            same_agent_registry[0],
        ]
        identity, matched = scope["resolve_external_feedback_agent"](
            pd.Series(
                {
                    "AgentId": "same-agent",
                    "AgentName": "Same Agent",
                    "ConversationId": "conv-b",
                }
            ),
            sessions,
            neutral_plus_scoped,
            {"same-agent"},
        )
        self.assertIsNotNone(matched)
        self.assertEqual("env-b|conv-b", matched["conversation_natural_key"])
        self.assertEqual("env-b", identity["canonical_environment_key"])

    def test_environment_aware_merge_keys_and_full_batch_validation(self) -> None:
        writes = self.cells[27]
        self.assertIn(
            "'agent_sessions':             ['conversation_natural_key']",
            writes,
        )
        self.assertIn(
            "'agent_turns':                ['conversation_natural_key', 'turn_id']",
            writes,
        )
        self.assertIn(
            "'agent_performance':          ['conversation_natural_key']",
            writes,
        )
        self.assertIn("_validate_full_incoming(pdf, name)", writes)
        self.assertLess(
            writes.index("_validate_full_incoming(pdf, name)"),
            writes.index("for _i in range(0, len(_pdf_str), _chunk_rows)"),
        )
        self.assertNotIn("_conv_env = dict(", writes)

    def test_empty_first_load_keeps_explicit_schema(self) -> None:
        writes = self.cells[27]
        self.assertIn(
            "if len(_pdf_str) == 0 and not spark.catalog.tableExists(table)",
            writes,
        )
        self.assertIn("append(empty-first-load)", writes)
        self.assertIn(
            "schema = StructType([StructField(c, StringType(), True)",
            writes,
        )
        self.assertIn("'user_feedback_quarantine'", writes)

    def test_hard_coded_ess_substring_filter_is_removed(self) -> None:
        self.assertNotIn("_ess_marker", self.cells[20])
        self.assertNotIn(
            "primary_agent_schema'].fillna('').str.lower().str.contains",
            self.cells[20],
        )
        self.assertIn("scope already applied", self.cells[20])

    def test_pbit_canonical_columns_and_relationships(self) -> None:
        with zipfile.ZipFile(self.repo / "ESS - Fabric V2.pbit") as archive:
            schema = json.loads(
                archive.read("DataModelSchema").decode("utf-16-le")
            )
        tables = {table["name"]: table for table in schema["model"]["tables"]}
        expected_tables = (
            "Agent Sessions",
            "Agent Performance",
            "ProductFeedback",
            "Agent Catalogue",
            "Credit Consumption (Agent)",
            "Credit Consumption (User)",
        )
        for name in expected_tables:
            columns = {
                column["name"]: column["dataType"]
                for column in tables[name]["columns"]
            }
            self.assertEqual("string", columns["canonical_agent_key"])
            self.assertEqual("string", columns["canonical_agent_name"])
            self.assertEqual("string", columns["canonical_environment_key"])
            self.assertEqual("string", columns["agent_mapping_status"])

        endpoints = {
            (
                relationship["fromTable"],
                relationship["fromColumn"],
                relationship["toTable"],
                relationship["toColumn"],
            )
            for relationship in schema["model"]["relationships"]
        }
        for fact in (
            "Agent Sessions",
            "Agent Performance",
            "ProductFeedback",
            "Credit Consumption (Agent)",
            "Credit Consumption (User)",
        ):
            self.assertIn(
                (
                    fact,
                    "canonical_agent_key",
                    "Agent Catalogue",
                    "canonical_agent_key",
                ),
                endpoints,
            )
        self.assertNotIn(
            (
                "Credit Consumption (Agent)",
                "Agent_Id_Normalized",
                "Consumption Agent",
                "Agent Id",
            ),
            endpoints,
        )
        for fact in (
            "Agent Turns",
            "Agent Errors",
            "Agent Sub-Agent Calls",
            "Agent Performance",
            "Agent Variables",
            "Knowledge Citations",
            "Activity Events",
        ):
            self.assertIn(
                (
                    fact,
                    "conversation_natural_key",
                    "Agent Sessions",
                    "conversation_natural_key",
                ),
                endpoints,
            )
            self.assertIn(
                "conversation_natural_key",
                {column["name"] for column in tables[fact]["columns"]},
            )
        variables_expression = tables["Agent Variables"]["partitions"][0]["source"][
            "expression"
        ]
        variables_text = (
            "\n".join(variables_expression)
            if isinstance(variables_expression, list)
            else variables_expression
        )
        self.assertIn("UnambiguousSessionKeys", variables_text)
        self.assertIn("occur in multiple environments", variables_text)
        self.assertIn("if not NeedsNaturalKeyBackfill then", variables_text)

    def test_pbit_queries_have_typed_empty_fallbacks(self) -> None:
        with zipfile.ZipFile(self.repo / "ESS - Fabric V2.pbit") as archive:
            schema = json.loads(
                archive.read("DataModelSchema").decode("utf-16-le")
            )
        tables = {table["name"]: table for table in schema["model"]["tables"]}
        for name in (
            "Agent Sessions",
            "Agent Performance",
            "ProductFeedback",
            "Agent Catalogue",
            "Credit Consumption (Agent)",
            "Credit Consumption (User)",
        ):
            expression = tables[name]["partitions"][0]["source"]["expression"]
            expression = (
                "\n".join(expression)
                if isinstance(expression, list)
                else expression
            )
            self.assertIn("canonical_agent_key", expression)
            self.assertRegex(expression, r"type text|RegistryEnsured")
        product = tables["ProductFeedback"]["partitions"][0]["source"][
            "expression"
        ]
        product = "\n".join(product) if isinstance(product, list) else product
        self.assertIn('"agent_mapping_status"', product)
        selected = product.rsplit("Selected =", 1)[1]
        self.assertIn('"raw_agent_schema"', selected)

        glossary = tables["📖 Metric Glossary"]
        metric = next(
            column for column in glossary["columns"] if column["name"] == "Metric"
        )
        self.assertNotIn("sortByColumn", metric)

    def test_power_query_transforms_are_idempotent(self) -> None:
        sample = """let
    Promoted = EmptyTable({"conversation_id"}),
    Ensured = Promoted,
    Typed = Table.TransformColumnTypes(Ensured, {{"conversation_id", type text}})
in
    Typed
"""
        once = patch_m_ensured(sample, "Ensured", "Typed", IDENTITY_COLUMNS)
        self.assertEqual(
            once,
            patch_m_ensured(once, "Ensured", "Typed", IDENTITY_COLUMNS),
        )
        feedback = (
            'let\n'
            '    Headers = EmptyTable({"Match Status"}),\n'
            '    Renamed = Table.RenameColumns(Headers, {}),\n'
            '    Selected = Table.SelectColumns(Renamed, {"MatchStatus"}, MissingField.UseNull)\n'
            'in\n    Selected\n'
        )
        once_feedback = patch_feedback_query(feedback)
        self.assertEqual(once_feedback, patch_feedback_query(once_feedback))
        selected = once_feedback.rsplit("Selected =", 1)[1]
        for column in (
            "canonical_agent_key",
            "canonical_agent_name",
            "canonical_environment_key",
            "agent_mapping_status",
            "raw_agent_id",
            "raw_agent_schema",
            "raw_agent_name",
            "source_environment",
        ):
            self.assertEqual(1, selected.count(f'"{column}"'))
        once_catalogue = catalogue_query("")
        self.assertEqual(once_catalogue, catalogue_query(once_catalogue))

    def test_dynamic_format_and_agent_link_fixes_survive(self) -> None:
        with zipfile.ZipFile(self.repo / "ESS - Fabric V2.pbit") as archive:
            schema = json.loads(
                archive.read("DataModelSchema").decode("utf-16-le")
            )
        conflicts = [
            f"{table['name']}[{measure['name']}]"
            for table in schema["model"]["tables"]
            for measure in table.get("measures", [])
            if "formatString" in measure and "formatStringDefinition" in measure
        ]
        self.assertEqual([], conflicts)
        table = next(
            table
            for table in schema["model"]["tables"]
            if table["name"] == "Chat + Agent Interactions (Audit Logs)"
        )
        expression = table["partitions"][0]["source"]["expression"]
        expression = (
            "\n".join(expression)
            if isinstance(expression, list)
            else expression
        )
        self.assertIn(
            '__linkBase = Table.RemoveColumns(__xN, {"Agent_LinkID"}, MissingField.Ignore)',
            expression,
        )
        self.assertIn(
            '__link = Table.AddColumn(__linkBase, "Agent_LinkID", each',
            expression,
        )


if __name__ == "__main__":
    unittest.main()
