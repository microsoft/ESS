import csv
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from agent_registry import active_agent_keys, load_registry, validate_registry
from ess_feedback_normalizer import normalize_files


class FeedbackNormalizerTests(unittest.TestCase):
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
            self.assertEqual("conversation-1", events[0]["ConversationId"])
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

            events, audit = normalize_files(
                [product], registry_rows=loaded, scope_mode="ESS Safe"
            )
            self.assertEqual(1, len(events))
            self.assertEqual("ess-agent", events[0]["AgentId"])
            self.assertEqual("Employee Self-Service", events[0]["AgentName"])
            self.assertEqual(["ess-agent"], audit["agentRegistryKeys"])
            metadata = json.loads(events[0]["AdditionalMetadata"])
            self.assertEqual(["T_ESS"], metadata["sourceAgentIds"])

            conflicting = [*rows, {**rows[0], "AgentKey": "other-agent"}]
            with self.assertRaisesRegex(ValueError, "maps to multiple agents"):
                validate_registry(conflicting)


if __name__ == "__main__":
    unittest.main()
