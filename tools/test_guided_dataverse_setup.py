import csv
import json
import os
import subprocess
import tempfile
import unittest
import zipfile
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

from guided_dataverse_setup import (
    OUTPUT_NAMES,
    TOPIC_OUTPUT_NAME,
    SetupOptions,
    build_command,
    build_feedback_command,
    load_settings,
    last_process_message,
    merge_cli_options,
    prepare_feedback,
    save_settings,
    validation_summary,
    tune_topics,
)
from build_service_refresh_template import (
    serialize_registry,
    validate_feedback_events,
)


class GuidedDataverseSetupTests(unittest.TestCase):
    def test_default_output_names_make_publication_choice_unambiguous(self) -> None:
        desktop_name = OUTPUT_NAMES["desktop-validation"]
        service_name = OUTPUT_NAMES["service-refresh"]

        self.assertIn("Desktop Validation - DO NOT PUBLISH", desktop_name)
        self.assertIn("Power BI Service - PUBLISH THIS", service_name)
        self.assertIn("Desktop Validation - Topics - DO NOT PUBLISH", TOPIC_OUTPUT_NAME)
        self.assertNotEqual(desktop_name, service_name)

    def test_topic_launcher_checks_every_prepared_feedback_destination(self) -> None:
        from guided_dataverse_setup import feedback_output_paths, main

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            csv_output = root / "feedback-events.csv"
            for destination in feedback_output_paths(csv_output):
                for field in ("transcript", "settings", "source", "final-output", "rules", "registry", "raw"):
                    with self.subTest(output=destination.name, field=field):
                        destination.write_bytes(b"protected launcher input sentinel")
                        settings = destination if field == "settings" else root / "settings.json"
                        save_settings(settings, SetupOptions(
                            environment_url="https://savedqa.crm.dynamics.com",
                            agent_registry_json=str(destination) if field == "registry" else "registry.json",
                            topic_overrides_json=str(destination) if field == "rules" else "rules.json",
                            feedback_input_files=[str(destination) if field == "raw" else "raw.csv"],
                        ))
                        preserved = {path: path.read_bytes() for path in root.iterdir()}
                        with patch("sys.argv", ["setup", "--tune-topics", "--non-interactive", "--no-open", "--settings-file", str(settings),
                                                 "--topic-transcripts", str(destination if field == "transcript" else root / "transcripts.csv"),
                                                 "--output", str(destination if field == "final-output" else root / "not-created" / "new.pbit")]), \
                             patch("guided_dataverse_setup.SOURCE_TEMPLATE", destination if field == "source" else root / "base.pbit"), \
                             patch("guided_dataverse_setup.PREPARED_FEEDBACK", csv_output), patch("guided_dataverse_setup.validate_runtime"), \
                             patch("guided_dataverse_setup.subprocess.run", side_effect=AssertionError("unexpected tuner launch")):
                            with self.assertRaisesRegex(ValueError, "conflicts with protected input"):
                                main()
                        self.assertEqual({path: path.read_bytes() for path in root.iterdir()}, preserved)

    def test_topic_launcher_preserves_missing_saved_setup_error(self) -> None:
        from guided_dataverse_setup import main

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch("sys.argv", ["setup", "--tune-topics", "--non-interactive", "--no-open", "--settings-file", str(root / "missing-settings.json"),
                                     "--topic-transcripts", str(root / "transcripts.csv"), "--output", str(root / "not-created" / "new.pbit")]), \
                 patch("guided_dataverse_setup.validate_runtime"), \
                 patch("guided_dataverse_setup.subprocess.run", side_effect=AssertionError("unexpected tuner launch")):
                with self.assertRaisesRegex(ValueError, "baseline before tuning topics"):
                    main()
            self.assertEqual(list(root.iterdir()), [])

    def test_normalizer_feedback_outputs_preserve_registry_and_raw_inputs(self) -> None:
        from ess_feedback_normalizer import feedback_output_paths, main

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            csv_output = root / "feedback-events.csv"
            outputs = feedback_output_paths(csv_output)
            for destination in outputs:
                destination.write_bytes(f"protected {destination.name} sentinel".encode())
            raw = root / "raw.csv"
            raw.write_bytes(b"protected raw feedback sentinel")
            registry = root / "registry.json"
            registry.write_bytes(b"protected registry sentinel")
            preserved = {path: path.read_bytes() for path in root.iterdir()}
            for destination in outputs:
                for field in ("--input", "--agent-registry"):
                    for alias in (destination, Path(str(destination).upper()), root / "unused" / ".." / destination.name):
                        arguments = ["normalizer", "--input", str(alias if field == "--input" else raw),
                                     "--agent-registry", str(alias if field == "--agent-registry" else registry), "--output", str(csv_output)]
                        with self.subTest(output=destination.name, field=field, alias=str(alias)), \
                             patch("sys.argv", arguments), \
                             patch("ess_feedback_normalizer.load_registry", side_effect=AssertionError("unexpected registry read")), \
                             patch("ess_feedback_normalizer.normalize_files", side_effect=AssertionError("unexpected normalization")):
                            with self.assertRaisesRegex(ValueError, "conflicts with protected input"):
                                main()
                            self.assertEqual({path: path.read_bytes() for path in root.iterdir()}, preserved)

    def test_normalizer_custom_audit_cannot_replace_inputs_or_other_outputs(self) -> None:
        from ess_feedback_normalizer import feedback_output_paths, main

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raw = root / "raw.csv"
            registry = root / "registry.json"
            csv_output = root / "feedback-events.csv"
            for path in (raw, registry):
                path.write_bytes(b"protected input sentinel")
            preserved = {path: path.read_bytes() for path in root.iterdir()}
            self.assertEqual(feedback_output_paths(csv_output), (csv_output, csv_output.with_suffix(".json"), csv_output.with_suffix(".audit.json")))
            for audit in (raw, registry, csv_output, csv_output.with_suffix(".json"), Path(str(raw).upper())):
                with self.subTest(audit=str(audit)), \
                     patch("sys.argv", ["normalizer", "--input", str(raw), "--agent-registry", str(registry),
                                         "--output", str(csv_output), "--audit", str(audit)]), \
                     patch("ess_feedback_normalizer.normalize_files", side_effect=AssertionError("unexpected normalization")):
                    with self.assertRaisesRegex(ValueError, "conflicts with protected input"):
                        main()
                    self.assertEqual({path: path.read_bytes() for path in root.iterdir()}, preserved)

    def test_guided_prepared_outputs_protect_source_settings_transcripts_and_final_pbit(self) -> None:
        from guided_dataverse_setup import feedback_output_paths, main

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            csv_output = root / "feedback-events.csv"
            for destination in feedback_output_paths(csv_output):
                for protected in ("source", "settings", "transcripts", "final-output"):
                    with self.subTest(output=destination.name, protected=protected):
                        destination.write_bytes(b"protected feedback collision sentinel")
                        settings = destination if protected == "settings" else root / "settings.json"
                        save_settings(settings, SetupOptions(environment_url="https://savedqa.crm.dynamics.com", agent_registry_json="registry.json", feedback_input_files=["raw.csv"]))
                        output = destination if protected == "final-output" else root / "not-created" / "new.pbit"
                        source = destination if protected == "source" else root / "base.pbit"
                        transcript = destination if protected == "transcripts" else root / "transcripts.csv"
                        preserved = {path: path.read_bytes() for path in root.iterdir()}
                        with patch("sys.argv", ["setup", "--non-interactive", "--no-open", "--settings-file", str(settings),
                                                 "--output", str(output), "--topic-transcripts", str(transcript)]), \
                             patch("guided_dataverse_setup.SOURCE_TEMPLATE", source), patch("guided_dataverse_setup.PREPARED_FEEDBACK", csv_output), \
                             patch("guided_dataverse_setup.validate_runtime"), patch("builtins.print"), \
                             patch("guided_dataverse_setup.subprocess.run", side_effect=AssertionError("unexpected feedback normalization")), \
                             patch("guided_dataverse_setup.staging_path", side_effect=AssertionError("unexpected PBIT staging")):
                            with self.assertRaisesRegex(ValueError, "conflicts with protected input"):
                                main()
                        self.assertEqual({path: path.read_bytes() for path in root.iterdir()}, preserved)

    def test_prepared_feedback_outputs_preserve_inputs_before_normalization(self) -> None:
        from guided_dataverse_setup import feedback_output_paths

        fields = ("agent_registry_json", "org_data_file", "agent_credits_file", "topic_overrides_json", "feedback_events_json", "feedback_input_files")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            csv_output = root / "feedback-events.csv"
            outputs = feedback_output_paths(csv_output)
            for destination in outputs:
                destination.write_bytes(f"protected {destination.name} sentinel".encode())
            raw = root / "raw.csv"
            raw.write_bytes(b"protected raw feedback sentinel")
            registry = root / "registry.json"
            registry.write_bytes(b"protected registry sentinel")
            preserved = {path: path.read_bytes() for path in root.iterdir()}
            for destination in outputs:
                for field_name in fields:
                    for alias in (destination, Path(str(destination).upper()), root / "unused" / ".." / destination.name):
                        with self.subTest(output=destination.name, field=field_name, alias=str(alias)):
                            options = SetupOptions(environment_url="https://savedqa.crm.dynamics.com", agent_registry_json=str(registry), feedback_input_files=[str(raw)])
                            setattr(options, field_name, [str(raw), str(alias)] if field_name == "feedback_input_files" else str(alias))
                            with patch("guided_dataverse_setup.PREPARED_FEEDBACK", csv_output), \
                                 patch("guided_dataverse_setup.subprocess.run", side_effect=AssertionError("unexpected normalizer write")):
                                with self.assertRaisesRegex(ValueError, "conflicts with protected input") as failure:
                                    prepare_feedback(options)
                                self.assertIn(destination.name.casefold(), str(failure.exception).casefold())
                            self.assertEqual({path: path.read_bytes() for path in root.iterdir()}, preserved)

    def test_prepared_feedback_outputs_reject_protected_context_without_directory_writes(self) -> None:
        from guided_dataverse_setup import feedback_output_paths

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            csv_output = root / "feedback-events.csv"
            for destination in feedback_output_paths(csv_output):
                destination.write_bytes(b"protected settings, source, transcript or PBIT sentinel")
                options = SetupOptions(environment_url="https://savedqa.crm.dynamics.com", agent_registry_json="registry.json", feedback_input_files=["raw.csv"])
                with patch("guided_dataverse_setup.PREPARED_FEEDBACK", csv_output), \
                     patch("guided_dataverse_setup.subprocess.run", side_effect=AssertionError("unexpected normalizer write")):
                    with self.assertRaisesRegex(ValueError, "conflicts with protected input"):
                        prepare_feedback(options, [destination])
                self.assertEqual(destination.read_bytes(), b"protected settings, source, transcript or PBIT sentinel")

    def test_output_collisions_preserve_all_guided_setup_inputs_before_staging(self) -> None:
        from guided_dataverse_setup import main

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = {name: root / f"{name}.json" for name in (
                "base", "transcripts", "registry", "organization", "credits", "active-rules", "new-rules", "feedback", "raw-feedback", "prepared-feedback",
            )}
            for name, path in paths.items():
                path.write_bytes(f"protected {name} sentinel".encode())
            settings = root / "settings.json"
            save_settings(settings, SetupOptions(environment_url="https://savedqa.crm.dynamics.com",
                                                 agent_registry_json=str(paths["registry"]), org_data_file=str(paths["organization"]),
                                                 agent_credits_file=str(paths["credits"]), topic_overrides_json=str(paths["active-rules"]),
                                                 feedback_events_json=str(paths["feedback"]), feedback_input_files=[str(paths["raw-feedback"])]))
            preserved = {path: path.read_bytes() for path in root.iterdir()}
            for protected in [*paths.values(), settings]:
                for output in (protected, Path(str(protected).upper()), root / "unused" / ".." / protected.name):
                    with self.subTest(protected=protected.name, output=str(output)):
                        with patch("sys.argv", ["setup", "--non-interactive", "--no-open", "--settings-file", str(settings),
                                                 "--output", str(output), "--topic-transcripts", str(paths["transcripts"]),
                                                 "--topic-overrides-json", str(paths["new-rules"])]), \
                             patch("guided_dataverse_setup.SOURCE_TEMPLATE", paths["base"]), \
                             patch("guided_dataverse_setup.PREPARED_FEEDBACK", paths["prepared-feedback"]), \
                             patch("guided_dataverse_setup.validate_runtime"), patch("builtins.print"), \
                             patch("guided_dataverse_setup.staging_path", side_effect=AssertionError("unexpected staging")), \
                             patch("guided_dataverse_setup.prepare_feedback", side_effect=AssertionError("unexpected feedback write")), \
                             patch("guided_dataverse_setup.subprocess.run", side_effect=AssertionError("unexpected builder")):
                            with self.assertRaisesRegex(ValueError, "conflicts with protected input") as failure:
                                main()
                            self.assertIn(protected.name.casefold(), str(failure.exception).casefold())
                        self.assertEqual({path: path.read_bytes() for path in root.iterdir()}, preserved)

    def test_topic_launcher_rejects_input_collision_before_starting_tuner(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "transcripts.csv"
            source.write_bytes(b"protected transcript sentinel")
            active = root / "active-rules.json"
            active.write_bytes(b"protected active rules sentinel")
            settings = root / "settings.json"
            save_settings(settings, SetupOptions(environment_url="https://savedqa.crm.dynamics.com", topic_overrides_json=str(active)))
            preserved = {path: path.read_bytes() for path in root.iterdir()}
            for output in (source, Path(str(active).upper()), settings):
                args = Namespace(mode="desktop-validation", settings_file=settings, topic_transcripts=source,
                                 output=output, no_open=True, non_interactive=True)
                with patch("guided_dataverse_setup.subprocess.run", side_effect=AssertionError("unexpected tuner launch")):
                    with self.assertRaisesRegex(ValueError, "conflicts with protected input"):
                        tune_topics(args)
                self.assertEqual({path: path.read_bytes() for path in root.iterdir()}, preserved)

    def test_backup_cleanup_failure_after_commit_does_not_report_failure(self) -> None:
        from guided_dataverse_setup import main

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            settings = root / "settings.json"
            output = root / "existing.pbit"
            candidate = root / "approved-candidate.json"
            candidate.write_text("[]", encoding="utf-8")
            previous = SetupOptions(environment_url="https://savedqa.crm.dynamics.com", topic_overrides_json="old-approved.json")
            save_settings(settings, previous)
            old_settings = settings.read_bytes()
            output.write_bytes(b"old template sentinel")
            new_template = []
            unlink_file = Path.unlink

            def build(command, **kwargs):
                staged = Path(command[command.index("--output") + 1])
                with zipfile.ZipFile(staged, "w") as package:
                    package.writestr("DataModelSchema", '{"model":{"name":"new template"}}')
                new_template.append(staged.read_bytes())
                return subprocess.CompletedProcess(command, 0, stdout='{"sources":[]}')

            def reject_backup_cleanup(path, *args, **kwargs):
                if path.suffix == ".backup":
                    raise PermissionError("injected locked settings backup")
                return unlink_file(path, *args, **kwargs)

            with patch("sys.argv", ["setup", "--non-interactive", "--no-open", "--settings-file", str(settings),
                                     "--output", str(output), "--topic-overrides-json", str(candidate)]), \
                 patch("guided_dataverse_setup.validate_runtime"), \
                 patch("guided_dataverse_setup.subprocess.run", side_effect=build), \
                 patch.object(Path, "unlink", autospec=True, side_effect=reject_backup_cleanup), \
                 patch("builtins.print") as printed:
                self.assertEqual(main(), 0)
            expected = SetupOptions(environment_url=previous.environment_url, topic_overrides_json=str(candidate.resolve()))
            self.assertEqual(load_settings(settings), expected)
            self.assertNotEqual(settings.read_bytes(), old_settings)
            self.assertEqual(output.read_bytes(), new_template[0])
            backups = list(root.glob("*.backup"))
            self.assertEqual(len(backups), 1)
            self.assertEqual(backups[0].read_bytes(), old_settings)
            messages = "\n".join(str(call.args[0]) for call in printed.call_args_list if call.args)
            self.assertIn("WARNING:", messages)
            self.assertIn("publication succeeded", messages)
            self.assertIn(str(backups[0].resolve()), messages)
            self.assertNotIn("Setup could not continue", messages)
            self.assertEqual(set(root.iterdir()), {settings, output, candidate, backups[0]})

    def test_settings_write_failure_preserves_existing_template_and_settings(self) -> None:
        self.assert_publication_failure("settings")

    def test_template_commit_failure_restores_original_settings(self) -> None:
        for existing_settings in (True, False):
            with self.subTest(existing_settings=existing_settings):
                self.assert_publication_failure("template", existing_settings)

    def assert_publication_failure(self, failed_artifact: str, existing_settings: bool = True) -> None:
        from guided_dataverse_setup import main

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            settings = root / "settings.json"
            output = root / "existing.pbit"
            active = root / "old-approved.json"
            candidate = root / "candidate.json"
            active.write_text("[]", encoding="utf-8")
            candidate.write_text("[]", encoding="utf-8")
            if existing_settings:
                save_settings(settings, SetupOptions(environment_url="https://savedqa.crm.dynamics.com", topic_overrides_json=str(active)))
            output.write_bytes(b"existing template sentinel")
            preserved = {path: path.read_bytes() for path in root.iterdir()}
            replace_file = os.replace

            def build(command, **kwargs):
                staged = Path(command[command.index("--output") + 1])
                self.assertNotEqual(staged.resolve(), output.resolve())
                self.assertEqual(staged.parent.resolve(), output.parent.resolve())
                with zipfile.ZipFile(staged, "w") as package:
                    package.writestr("DataModelSchema", "{}")
                return subprocess.CompletedProcess(command, 0, stdout='{"sources":[]}')

            def reject_commit(source, destination):
                target = settings if failed_artifact == "settings" else output
                if Path(destination).resolve() == target.resolve():
                    raise PermissionError(f"injected {failed_artifact} commit failure")
                return replace_file(source, destination)

            with patch("sys.argv", ["setup", "--non-interactive", "--no-open", "--settings-file", str(settings),
                                     "--environment-url", "https://savedqa.crm.dynamics.com", "--output", str(output), "--topic-overrides-json", str(candidate)]), \
                 patch("guided_dataverse_setup.validate_runtime"), patch("guided_dataverse_setup.subprocess.run", side_effect=build), \
                 patch("guided_dataverse_setup.os.replace", side_effect=reject_commit), patch("builtins.print"):
                with self.assertRaisesRegex(RuntimeError, f"{failed_artifact} commit failure"):
                    main()
            for path, original in preserved.items():
                self.assertEqual(path.read_bytes(), original, str(path))
            if existing_settings:
                self.assertEqual(load_settings(settings).topic_overrides_json, str(active))
            else:
                self.assertFalse(settings.exists())
            self.assertEqual(set(root.iterdir()), set(preserved))

    def test_atomic_standalone_settings_save_preserves_previous_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            settings = Path(directory) / "settings.json"
            original = SetupOptions(environment_url="https://savedqa.crm.dynamics.com", topic_overrides_json="old-approved.json")
            save_settings(settings, original)
            previous = settings.read_bytes()
            with patch("guided_dataverse_setup.os.replace", side_effect=PermissionError("injected atomic settings failure")):
                with self.assertRaisesRegex(PermissionError, "atomic settings failure"):
                    save_settings(settings, SetupOptions(environment_url="https://savedqa.crm.dynamics.com", topic_overrides_json="uncommitted.json"))
            self.assertEqual(settings.read_bytes(), previous)
            self.assertEqual(list(settings.parent.iterdir()), [settings])

    def test_rollback_failure_identifies_settings_and_retains_recovery_backup(self) -> None:
        from guided_dataverse_setup import publish_template

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            settings = root / "settings.json"
            staged_settings = root / "candidate-settings.json"
            output = root / "existing.pbit"
            staged_output = root / "candidate.pbit"
            save_settings(settings, SetupOptions(environment_url="https://savedqa.crm.dynamics.com", topic_overrides_json="old-approved.json"))
            original = settings.read_bytes()
            save_settings(staged_settings, SetupOptions(environment_url="https://savedqa.crm.dynamics.com", topic_overrides_json="candidate.json"))
            output.write_bytes(b"existing template sentinel")
            staged_output.write_bytes(b"new staged template")
            replace_file = os.replace

            def reject_template_and_rollback(source, destination):
                if Path(destination).resolve() == output.resolve():
                    raise PermissionError("injected template commit failure")
                if str(source).endswith(".backup"):
                    raise PermissionError("injected settings rollback failure")
                return replace_file(source, destination)

            with patch("guided_dataverse_setup.os.replace", side_effect=reject_template_and_rollback):
                with self.assertRaisesRegex(RuntimeError, "Settings rollback failed") as failure:
                    publish_template(staged_output, output, staged_settings, settings)
            self.assertIn(str(settings), str(failure.exception))
            self.assertIn("template commit failure", str(failure.exception))
            backups = list(root.glob("*.backup"))
            self.assertEqual(len(backups), 1)
            self.assertEqual(backups[0].read_bytes(), original)
            self.assertIn(str(backups[0]), str(failure.exception))
            self.assertEqual(output.read_bytes(), b"existing template sentinel")

    def test_topic_launcher_forwards_noninteractive_mode_without_file_picker(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            settings = root / "settings.json"
            save_settings(settings, SetupOptions(environment_url="https://savedqa.crm.dynamics.com"))
            args = Namespace(mode="desktop-validation", settings_file=settings, topic_transcripts=root / "transcripts.csv",
                             output=None, no_open=True, non_interactive=True)
            with patch("guided_dataverse_setup.select_file", side_effect=AssertionError("unexpected file picker")), \
                 patch("guided_dataverse_setup.subprocess.run") as runner:
                runner.return_value.returncode = 0
                self.assertEqual(tune_topics(args), 0)
                self.assertIn("--non-interactive", runner.call_args.args[0])
                self.assertIn("--no-open", runner.call_args.args[0])

    def test_topic_launcher_asks_only_for_export_and_reuses_saved_settings(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            settings = root / "settings.json"
            save_settings(settings, SetupOptions(environment_url="https://savedqa.crm.dynamics.com", org_data_file="users.csv"))
            original = settings.read_bytes()
            args = Namespace(mode="desktop-validation", settings_file=settings, topic_transcripts=None, output=None, no_open=False, non_interactive=False)
            with patch("guided_dataverse_setup.select_file", return_value=str(root / "transcripts.csv")) as picker, \
                 patch("guided_dataverse_setup.subprocess.run") as runner:
                runner.return_value.returncode = 0
                self.assertEqual(tune_topics(args), 0)
                picker.assert_called_once()
                command = runner.call_args.args[0]
                self.assertEqual(command[command.index("--settings-file") + 1], str(settings.resolve()))
                self.assertEqual(
                    Path(command[command.index("--template-output") + 1]).name,
                    TOPIC_OUTPUT_NAME,
                )
                self.assertNotIn("--analyze-only", command)
                self.assertNotIn("--environment-url", command)
                self.assertEqual(settings.read_bytes(), original)

    def test_topic_launcher_cancel_and_missing_baseline_do_not_run_tuner(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            settings = Path(directory) / "settings.json"
            args = Namespace(mode="desktop-validation", settings_file=settings, topic_transcripts=None, output=None, no_open=False, non_interactive=False)
            with patch("guided_dataverse_setup.subprocess.run") as runner:
                with self.assertRaisesRegex(ValueError, "baseline"):
                    tune_topics(args)
                save_settings(settings, SetupOptions(environment_url="https://savedqa.crm.dynamics.com"))
                with patch("guided_dataverse_setup.select_file", return_value=""), patch("builtins.print"):
                    self.assertEqual(tune_topics(args), 0)
                runner.assert_not_called()

    def test_topic_launcher_reuses_existing_windows_launcher(self) -> None:
        root = Path(__file__).resolve().parents[1]
        self.assertIn('call "%~dp0START-HERE-DATAVERSE.cmd" --tune-topics %*', (root / "TUNE-TOPICS.cmd").read_text())

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

    def test_noninteractive_open_is_explicit_and_mutually_exclusive(self) -> None:
        from guided_dataverse_setup import parse_args

        with patch("sys.argv", ["setup", "--non-interactive", "--open"]):
            args = parse_args()
        self.assertTrue(args.non_interactive)
        self.assertTrue(args.open_template)
        self.assertFalse(args.no_open)
        with patch("sys.argv", ["setup", "--open", "--no-open"]), patch("sys.stderr"):
            with self.assertRaises(SystemExit):
                parse_args()

    def test_topic_cli_override_preserves_all_unrelated_saved_choices(self) -> None:
        stored = SetupOptions(
            environment_url="https://savedqa.crm4.dynamics.com",
            agent_registry_json="registry.json",
            org_data_file="users.csv",
            agent_credits_file="credits.csv",
            topic_overrides_json="previous-topics.json",
            feedback_events_json="feedback.json",
            feedback_input_files=["monitor.csv"],
        )
        args = Namespace(environment_url=None, agent_registry_json=None, org_data_file=None,
                         agent_credits_file=None, topic_overrides_json=Path("approved.json"),
                         feedback_events_json=None, feedback_input=[])
        from dataclasses import asdict

        previous = asdict(stored)
        merged = asdict(merge_cli_options(args, stored))
        self.assertEqual(merged.pop("topic_overrides_json"), str(Path("approved.json").resolve()))
        previous.pop("topic_overrides_json")
        self.assertEqual(merged, previous)

    def test_noninteractive_open_builds_without_prompting(self) -> None:
        from guided_dataverse_setup import main

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            settings = root / "settings.json"
            output = root / "new.pbit"
            save_settings(settings, SetupOptions(environment_url="https://savedqa.crm.dynamics.com"))
            completed = subprocess.CompletedProcess(args=[], returncode=0, stdout='{"sources":[]}')

            def build(command, **kwargs):
                staged = Path(command[command.index("--output") + 1])
                with zipfile.ZipFile(staged, "w") as package:
                    package.writestr("DataModelSchema", "{}")
                return completed

            with patch("sys.argv", ["setup", "--non-interactive", "--open", "--settings-file", str(settings), "--output", str(output)]), \
                 patch("guided_dataverse_setup.validate_runtime"), \
                 patch("guided_dataverse_setup.subprocess.run", side_effect=build), \
                 patch("guided_dataverse_setup.os.startfile", create=True) as opener, \
                 patch("builtins.input", side_effect=AssertionError("No setup questions expected")), \
                 patch("builtins.print"):
                self.assertEqual(main(), 0)
                opener.assert_called_once_with(output.resolve())
                with zipfile.ZipFile(output) as package:
                    self.assertIsNone(package.testzip())

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
