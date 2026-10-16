import csv
import json
import subprocess
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

from guided_dataverse_setup import (
    SetupOptions,
    build_command,
    build_feedback_command,
    load_settings,
    last_process_message,
    merge_cli_options,
    prepare_feedback,
    save_settings,
    validation_summary,
)
from build_service_refresh_template import (
    serialize_registry,
    validate_feedback_events,
)


class GuidedDataverseSetupTests(unittest.TestCase):
    def test_desktop_command_includes_every_supplied_source(self) -> None:
        options = SetupOptions(
            environment_url="https://orgexample.crm.dynamics.com",
            agent_registry_json="registry.json",
            org_data_file="users.csv",
            agent_credits_file="credits.csv",
            topic_overrides_json="topics.json",
            feedback_events_json="feedback.json",
        )

        command = build_command(
            "desktop-validation",
            options,
            Path("desktop.pbit"),
        )

        self.assertIn("--agent-registry-json", command)
        self.assertIn("--org-data-file", command)
        self.assertIn("--agent-credits-file", command)
        self.assertIn("--topic-overrides-json", command)
        self.assertIn("--feedback-events-json", command)

    def test_service_command_excludes_local_file_sources(self) -> None:
        options = SetupOptions(
            environment_url="https://orgexample.crm.dynamics.com",
            agent_registry_json="registry.json",
            org_data_file="users.csv",
            agent_credits_file="credits.csv",
            topic_overrides_json="topics.json",
            feedback_events_json="feedback.json",
        )

        command = build_command(
            "service-refresh",
            options,
            Path("service.pbit"),
        )

        self.assertIn("--agent-registry-json", command)
        self.assertIn("--topic-overrides-json", command)
        self.assertIn("--feedback-events-json", command)
        self.assertNotIn("--org-data-file", command)
        self.assertNotIn("--agent-credits-file", command)

    def test_raw_feedback_is_prepared_internally(self) -> None:
        options = SetupOptions(
            environment_url="https://orgexample.crm.dynamics.com",
            agent_registry_json="registry.csv",
            feedback_input_files=["product.csv", "monitor.csv"],
        )

        command = build_feedback_command(options, Path("feedback-events.csv"))

        self.assertEqual(command.count("--input"), 2)
        self.assertIn("product.csv", command)
        self.assertIn("monitor.csv", command)
        self.assertIn("--agent-registry", command)
        self.assertIn("registry.csv", command)

    def test_raw_feedback_requires_registry(self) -> None:
        options = SetupOptions(
            environment_url="https://orgexample.crm.dynamics.com",
            feedback_input_files=["product.csv"],
        )

        with self.assertRaisesRegex(ValueError, "requires an agent registry"):
            build_feedback_command(options, Path("feedback-events.csv"))

    def test_raw_feedback_is_filtered_and_mapped_by_guided_setup(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            registry = root / "agent-registry.csv"
            with registry.open("w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=(
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
                    ),
                )
                writer.writeheader()
                writer.writerow(
                    {
                        "RegistryVersion": "1",
                        "AgentKey": "ess-agent",
                        "AgentLabel": "Employee Self-Service",
                        "IsEss": "true",
                        "Selected": "true",
                        "Enabled": "true",
                        "EnvironmentKey": "",
                        "EnvironmentName": "",
                        "EnvironmentUrl": "",
                        "AliasType": "M365Title",
                        "AliasValue": "T_ess",
                    }
                )

            product_feedback = root / "product-feedback.csv"
            with product_feedback.open(
                "w",
                encoding="utf-8-sig",
                newline="",
            ) as handle:
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
                        "Feedback Id": "feedback-1",
                        "Feedback Type": "Thumbs Up",
                        "Microsoft Response Status": "Open",
                        "Agent ID": json.dumps(["T_ess"]),
                        "Comment": "Helpful",
                        "App": "M365 Chat",
                    }
                )

            monitor_feedback = root / "monitor-feedback.csv"
            with monitor_feedback.open(
                "w",
                encoding="utf-8-sig",
                newline="",
            ) as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=(
                        "Reaction Id",
                        "Conversation ID",
                        "Reaction",
                        "Channel",
                    ),
                )
                writer.writeheader()
                writer.writerow(
                    {
                        "Reaction Id": "monitor-1",
                        "Conversation ID": "conversation-1",
                        "Reaction": "Thumbs Down",
                        "Channel": "Microsoft Teams",
                    }
                )

            output = root / "prepared" / "feedback-events.csv"
            options = SetupOptions(
                environment_url="https://orgexample.crm.dynamics.com",
                agent_registry_json=str(registry),
                feedback_input_files=[
                    str(product_feedback),
                    str(monitor_feedback),
                ],
            )
            with patch(
                "guided_dataverse_setup.PREPARED_FEEDBACK",
                output,
            ):
                prepared = prepare_feedback(options)

            events = json.loads(
                output.with_suffix(".json").read_text(encoding="utf-8")
            )
            registry_rows, _ = serialize_registry(registry)
            _, audit = validate_feedback_events(
                output.with_suffix(".json"),
                registry_rows,
            )

        self.assertEqual(
            prepared.feedback_events_json,
            str(output.with_suffix(".json")),
        )
        self.assertEqual(events[0]["AgentId"], "ess-agent")
        self.assertEqual(events[1]["AgentId"], "")
        self.assertEqual(events[1]["ConversationId"], "conversation-1")
        self.assertEqual(audit["events"], 2)

    def test_settings_round_trip(self) -> None:
        options = SetupOptions(
            environment_url="https://orgexample.crm.dynamics.com",
            org_data_file="users.csv",
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            save_settings(path, options)
            loaded = load_settings(path)

        self.assertEqual(loaded, options)

    def test_changed_environment_clears_saved_customer_files(self) -> None:
        stored = SetupOptions(
            environment_url="https://orga.crm.dynamics.com",
            agent_registry_json="customer-a-registry.json",
            org_data_file="customer-a-users.csv",
            agent_credits_file="customer-a-credits.csv",
            topic_overrides_json="customer-a-topics.json",
            feedback_events_json="customer-a-feedback.json",
            feedback_input_files=["customer-a-product.csv"],
        )
        args = Namespace(
            environment_url="https://orgb.crm.dynamics.com",
            agent_registry_json=Path("customer-b-registry.json"),
            org_data_file=None,
            agent_credits_file=None,
            topic_overrides_json=None,
            feedback_events_json=None,
            feedback_input=[],
        )

        options = merge_cli_options(args, stored)

        self.assertEqual(
            options.environment_url,
            "https://orgb.crm.dynamics.com",
        )
        self.assertEqual(
            options.agent_registry_json,
            str(Path("customer-b-registry.json").resolve()),
        )
        self.assertEqual(options.org_data_file, "")
        self.assertEqual(options.agent_credits_file, "")
        self.assertEqual(options.topic_overrides_json, "")
        self.assertEqual(options.feedback_events_json, "")
        self.assertEqual(options.feedback_input_files, [])

    def test_prepared_feedback_cli_replaces_saved_raw_inputs(self) -> None:
        stored = SetupOptions(
            environment_url="https://orga.crm.dynamics.com",
            agent_registry_json="registry.csv",
            feedback_input_files=["old-product.csv"],
        )
        args = Namespace(
            environment_url=None,
            agent_registry_json=None,
            org_data_file=None,
            agent_credits_file=None,
            topic_overrides_json=None,
            feedback_events_json=Path("feedback-events.json"),
            feedback_input=[],
        )

        options = merge_cli_options(args, stored)

        self.assertEqual(
            options.feedback_events_json,
            str(Path("feedback-events.json").resolve()),
        )
        self.assertEqual(options.feedback_input_files, [])

    def test_validation_summary_uses_plain_language(self) -> None:
        summary = validation_summary(
            {
                "registryAliases": 4,
                "sources": [
                    {"contract": "Org Data", "rows": 303},
                    {
                        "contract": "Customer Topic Overrides",
                        "enabledRules": 2,
                    },
                    {"contract": "Feedback Events", "events": 6},
                ],
            }
        )

        self.assertEqual(
            summary,
            [
                "Dataverse Environment URL: valid",
                "Agent registry: 4 aliases",
                "Organization data: 303 rows",
                "Approved topic rules: 2 rows",
                "Prepared feedback: 6 rows",
            ],
        )

    def test_process_error_uses_last_nonempty_message(self) -> None:
        completed = subprocess.CompletedProcess(
            args=[],
            returncode=1,
            stdout="",
            stderr="Traceback\n\nValueError: invalid Environment URL\n",
        )

        self.assertEqual(
            last_process_message(completed),
            "ValueError: invalid Environment URL",
        )

    def test_invalid_settings_json_is_not_silently_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            path.write_text("{", encoding="utf-8")
            with self.assertRaises(json.JSONDecodeError):
                load_settings(path)

    def test_file_dialog_fallback_is_testable_without_tk(self) -> None:
        with patch.dict("sys.modules", {"tkinter": None}):
            from guided_dataverse_setup import select_file

            with patch("builtins.input", return_value="users.csv"):
                self.assertEqual(
                    select_file("Organization data", (("CSV", "*.csv"),)),
                    "users.csv",
                )


if __name__ == "__main__":
    unittest.main()
