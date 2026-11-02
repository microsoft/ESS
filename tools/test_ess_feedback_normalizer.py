import csv
import json
import subprocess
import sys
import tempfile
import unittest
import zipfile
from collections import Counter
from pathlib import Path

from agent_registry import active_agent_keys, load_registry, validate_registry
from ess_feedback_normalizer import normalize_files
from update_agent_registry import patch_conversation_feedback_query
from update_feedback_ingestion import build_conversation_feedback_query, patch_direct_pbit


class FeedbackNormalizerTests(unittest.TestCase):
    def test_mixed_repeated_feedback_preserves_events_and_removes_only_true_duplicates(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "monitor-reactions.csv"
            with source.open("w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=(
                        "Reaction Id",
                        "Conversation ID",
                        "Reaction",
                        "Comment",
                        "Timestamp",
                    ),
                )
                writer.writeheader()
                writer.writerows(
                    (
                        {
                            "Reaction Id": "up-1",
                            "Conversation ID": "conversation-1",
                            "Reaction": "Like",
                            "Comment": "First up",
                            "Timestamp": "2026-10-30T10:00:00Z",
                        },
                        {
                            "Reaction Id": "down-1",
                            "Conversation ID": "conversation-1",
                            "Reaction": "Dislike",
                            "Comment": "One down",
                            "Timestamp": "2026-10-30T10:01:00Z",
                        },
                        {
                            "Reaction Id": "up-2",
                            "Conversation ID": "conversation-1",
                            "Reaction": "Like",
                            "Comment": "Second up",
                            "Timestamp": "2026-10-30T10:02:00Z",
                        },
                        {
                            "Reaction Id": "up-1",
                            "Conversation ID": "conversation-1",
                            "Reaction": "Like",
                            "Comment": "Duplicate export row",
                            "Timestamp": "2026-10-30T10:00:00Z",
                        },
                    )
                )

            events, audit = normalize_files([source])

        self.assertEqual(len(events), 3)
        self.assertEqual(audit["duplicatesRemoved"], 1)
        self.assertEqual(audit["verdictCounts"], {"Thumbs Down": 1, "Thumbs Up": 2})
        self.assertEqual(
            {event["FeedbackComment"] for event in events},
            {"First up", "One down", "Second up"},
        )

    def test_conversation_feedback_matches_event_identity_before_count_fallback(self) -> None:
        query = build_conversation_feedback_query()

        self.assertIn('Table.ExpandListColumn(TranscriptListed, "_nativeEvent")', query)
        self.assertIn('Table.Distinct(Table.Buffer(TranscriptEvents), {"FeedbackEventKey"})', query)
        self.assertIn('"_EventIdentityKey"', query)
        self.assertIn('"_HasNativeIdentityMatch"', query)
        self.assertIn("ExternalExactIdentityKeys", query)
        self.assertIn("ExternalFallbackCounts", query)
        self.assertIn('each not [_HasNativeIdentityMatch] and [_ConversationVerdictKey] <> null', query)
        self.assertIn('each [_PairOrdinal] >= (if [_ExternalPairCount] = null then 0', query)
        self.assertNotIn("ExternalPairCounts", query)
        self.assertNotIn("ExternalPairKeys", query)

        native = [
            {"conversation": "conversation-1", "verdict": "Thumbs Up", "event": "A", "comment": "native A"},
            {"conversation": "conversation-1", "verdict": "Thumbs Up", "event": "B", "comment": "native B"},
        ]
        external = [
            {"conversation": "conversation-1", "verdict": "Thumbs Up", "event": "B", "comment": "external B"},
        ]
        native_identities = {
            (row["conversation"].casefold(), row["verdict"].casefold(), row["event"].casefold())
            for row in native
        }
        exact_external = {
            (row["conversation"].casefold(), row["verdict"].casefold(), row["event"].casefold())
            for row in external
            if (row["conversation"].casefold(), row["verdict"].casefold(), row["event"].casefold())
            in native_identities
        }
        remaining_native = [
            row
            for row in native
            if (row["conversation"].casefold(), row["verdict"].casefold(), row["event"].casefold())
            not in exact_external
        ]
        fallback_counts = Counter(
            (row["conversation"].casefold(), row["verdict"].casefold())
            for row in external
            if (row["conversation"].casefold(), row["verdict"].casefold(), row["event"].casefold())
            not in native_identities
        )
        retained_native = []
        seen_pairs = Counter()
        for row in remaining_native:
            pair = (row["conversation"].casefold(), row["verdict"].casefold())
            if seen_pairs[pair] >= fallback_counts[pair]:
                retained_native.append(row)
            seen_pairs[pair] += 1
        reconciled = [*external, *retained_native]

        self.assertEqual(len(reconciled), 2)
        self.assertEqual({row["event"] for row in reconciled}, {"A", "B"})
        self.assertEqual({row["comment"] for row in reconciled}, {"native A", "external B"})

    def test_agent_registry_patch_preserves_event_identity_reconciliation(self) -> None:
        query = patch_conversation_feedback_query(build_conversation_feedback_query())

        self.assertIn(
            "resolvedAgentKey = if matched then [MatchedAgentKey] else registryAgentKey",
            query,
        )
        self.assertIn("sourceEventId = if [FeedbackEventId] = null", query)
        self.assertIn("ExternalExactIdentityKeys", query)
        self.assertIn("ExternalFallbackCounts", query)

    def test_feedback_package_patch_preserves_registry_and_identity_composition(self) -> None:
        repo = Path(__file__).resolve().parents[1]
        source = (
            repo
            / "ESS Dashboard - Dynamic Topics (Dataverse) V21 - Power BI Service - PUBLISH THIS.pbit"
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            destination = Path(temp_dir) / source.name
            patch_direct_pbit(source, destination)
            with zipfile.ZipFile(destination) as package:
                schema = json.loads(package.read("DataModelSchema").decode("utf-16-le"))
                unapplied = (
                    json.loads(package.read("UnappliedChanges").decode("utf-16-le"))
                    if "UnappliedChanges" in package.namelist()
                    else None
                )

        table = next(
            item
            for item in schema["model"]["tables"]
            if item["name"] == "ConversationFeedback"
        )
        model_expression = table["partitions"][0]["source"]["expression"]
        model_text = (
            "\n".join(model_expression)
            if isinstance(model_expression, list)
            else model_expression
        )
        expressions = [model_text]
        if unapplied is not None:
            query = next(
                item
                for item in unapplied["queries"]
                if item["name"] == "ConversationFeedback"
            )
            expressions.append(
                "\n".join(query["text"])
                if isinstance(query["text"], list)
                else query["text"]
            )
        for expression in expressions:
            self.assertIn(
                "resolvedAgentKey = if matched then [MatchedAgentKey] else registryAgentKey",
                expression,
            )
            self.assertIn("ExternalExactIdentityKeys", expression)
            self.assertIn("ExternalFallbackCounts", expression)
            self.assertNotIn("ExternalPairCounts", expression)

    def test_product_feedback_and_monitor_exports_normalize_and_deduplicate(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            product = temp / "product-feedback.csv"
            monitor = temp / "monitor-reactions.csv"
            with product.open("w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=(
                        "Feedback Id",
                        "Feedback Type",
                        "Comment",
                        "Date Submitted UTC",
                        "App",
                        "Platform",
                        "Microsoft Response Status",
                        "Agent ID",
                        "Additional Metadata",
                    ),
                )
                writer.writeheader()
                metadata = json.dumps(
                    {
                        "conversationId": "conversation-1",
                        "essAgentId": "agent-1",
                        "copilotType": "m365",
                    }
                )
                row = {
                    "Feedback Id": "feedback-1",
                    "Feedback Type": "CopilotThumbsUp",
                    "Comment": "Helpful",
                    "Date Submitted UTC": "2026-10-08T12:00:00Z",
                    "App": "Microsoft 365 Copilot",
                    "Platform": "Copilot Chat",
                    "Microsoft Response Status": "Open",
                    "Agent ID": json.dumps(["T_agent-1"]),
                    "Additional Metadata": metadata,
                }
                writer.writerow(row)
                writer.writerow(row)
                writer.writerow(
                    {
                        **row,
                        "Feedback Id": "feedback-other-agent",
                        "Agent ID": json.dumps(["T_other-agent"]),
                    }
                )
                writer.writerow(
                    {
                        **row,
                        "Feedback Id": "feedback-unattributed",
                        "Agent ID": "",
                    }
                )
            with monitor.open("w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=("Reaction Id", "Conversation ID", "Reaction", "Timestamp", "Channel", "Agent Name"),
                )
                writer.writeheader()
                writer.writerow(
                    {
                        "Reaction Id": "reaction-2",
                        "Conversation ID": "conversation-2",
                        "Reaction": "thumbs down",
                        "Timestamp": "2026-10-08T12:05:00Z",
                        "Channel": "Microsoft Teams",
                        "Agent Name": "ESS Agent",
                    }
                )

            with self.assertRaisesRegex(ValueError, "--agent-id"):
                normalize_files([product, monitor])
            with self.assertRaisesRegex(ValueError, "matched the supplied --agent-id"):
                normalize_files([product, monitor], {"T_missing-agent"})

            events, audit = normalize_files([product, monitor], {"T_agent-1"})
            self.assertEqual(2, len(events))
            self.assertEqual(1, audit["duplicatesRemoved"])
            self.assertEqual({"Thumbs Down": 1, "Thumbs Up": 1}, audit["verdictCounts"])
            self.assertEqual(
                {"Microsoft 365 Copilot Chat": 1, "Microsoft Teams": 1},
                audit["channelCounts"],
            )
            self.assertEqual("T_agent-1", events[0]["AgentId"])
            self.assertEqual("", events[0]["ConversationId"])
            self.assertEqual("Microsoft 365 Product Feedback", events[0]["FeedbackSource"])
            self.assertEqual(["T_agent-1"], audit["allowedAgentIds"])
            self.assertEqual(2, audit["productFeedbackRowsIncludedByAllowlist"])
            self.assertEqual(1, audit["productFeedbackRowsExcludedOutsideAllowlist"])
            self.assertEqual(1, audit["productFeedbackRowsExcludedWithoutAgentId"])

            output = temp / "feedback-events.csv"
            subprocess.run(
                [
                    sys.executable,
                    str(Path(__file__).with_name("ess_feedback_normalizer.py")),
                    "--input",
                    str(product),
                    "--input",
                    str(monitor),
                    "--agent-id",
                    "T_agent-1",
                    "--output",
                    str(output),
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            json_events = json.loads(output.with_suffix(".json").read_text(encoding="utf-8"))
            self.assertEqual(events, json_events)

    def test_registry_scopes_and_product_feedback_mapping(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            registry = temp / "agent-registry.csv"
            fieldnames = (
                "RegistryVersion",
                "AgentKey",
                "AgentLabel",
                "IsEss",
                "Selected",
                "Enabled",
                "EnvironmentKey",
                "EnvironmentName",
                "EnvironmentUrl",
                "AliasType",
                "AliasValue",
            )
            rows = [
                {
                    "RegistryVersion": "1",
                    "AgentKey": "ess-agent",
                    "AgentLabel": "Employee Self-Service",
                    "IsEss": "true",
                    "Selected": "false",
                    "Enabled": "true",
                    "EnvironmentKey": "prod",
                    "EnvironmentName": "Production",
                    "EnvironmentUrl": "",
                    "AliasType": "M365Title",
                    "AliasValue": "T_ess",
                },
                {
                    "RegistryVersion": "1",
                    "AgentKey": "it-agent",
                    "AgentLabel": "IT Support",
                    "IsEss": "false",
                    "Selected": "true",
                    "Enabled": "true",
                    "EnvironmentKey": "prod",
                    "EnvironmentName": "Production",
                    "EnvironmentUrl": "",
                    "AliasType": "M365Title",
                    "AliasValue": "T_it",
                },
                {
                    "RegistryVersion": "1",
                    "AgentKey": "ess-agent",
                    "AgentLabel": "Employee Self-Service",
                    "IsEss": "true",
                    "Selected": "false",
                    "Enabled": "true",
                    "EnvironmentKey": "prod",
                    "EnvironmentName": "Production",
                    "EnvironmentUrl": "",
                    "AliasType": "TranscriptId",
                    "AliasValue": "00000000-0000-0000-0000-000000000001",
                },
            ]
            with registry.open("w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(rows)

            loaded = load_registry(registry)
            self.assertEqual({"ess-agent"}, active_agent_keys(loaded, "ESS Safe"))
            self.assertEqual({"it-agent"}, active_agent_keys(loaded, "Selected Agents"))
            self.assertEqual(
                {"ess-agent", "it-agent"}, active_agent_keys(loaded, "All Agents")
            )

            product = temp / "product-feedback.csv"
            with product.open("w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=(
                        "Feedback Id",
                        "Feedback Type",
                        "Microsoft Response Status",
                        "Agent ID",
                        "Comment",
                        "App",
                    ),
                )
                writer.writeheader()
                writer.writerow(
                    {
                        "Feedback Id": "ess-feedback",
                        "Feedback Type": "Thumbs Up",
                        "Microsoft Response Status": "Open",
                        "Agent ID": json.dumps(["T_ESS"]),
                        "Comment": "ESS",
                        "App": "M365 Chat",
                    }
                )
                writer.writerow(
                    {
                        "Feedback Id": "it-feedback",
                        "Feedback Type": "Thumbs Down",
                        "Microsoft Response Status": "Open",
                        "Agent ID": json.dumps(["T_it"]),
                        "Comment": "IT",
                        "App": "M365 Chat",
                    }
                )

            monitor = temp / "monitor-reactions.csv"
            with monitor.open("w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=(
                        "Reaction Id",
                        "Conversation ID",
                        "Reaction",
                        "Bot ID",
                        "Channel",
                    ),
                )
                writer.writeheader()
                writer.writerow(
                    {
                        "Reaction Id": "monitor-feedback",
                        "Conversation ID": "conversation-1",
                        "Reaction": "Thumbs Down",
                        "Bot ID": "00000000-0000-0000-0000-000000000001",
                        "Channel": "Microsoft Teams",
                    }
                )

            events, audit = normalize_files(
                [product, monitor],
                registry_rows=loaded,
                scope_mode="ESS Safe",
            )
            self.assertEqual(2, len(events))
            self.assertEqual("ess-agent", events[0]["AgentId"])
            self.assertEqual("Employee Self-Service", events[0]["AgentName"])
            self.assertEqual(["ess-agent"], audit["agentRegistryKeys"])
            self.assertEqual("ess-agent", events[1]["AgentId"])
            self.assertEqual(1, audit["externalRowsMappedByRegistry"])
            metadata = json.loads(events[0]["AdditionalMetadata"])
            self.assertEqual(["T_ESS"], metadata["sourceAgentIds"])

            conflicting = [*rows, {**rows[0], "AgentKey": "other-agent"}]
            with self.assertRaisesRegex(ValueError, "maps to multiple agents"):
                validate_registry(conflicting)


if __name__ == "__main__":
    unittest.main()
