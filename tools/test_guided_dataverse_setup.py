import csv
import io
import json
from dataclasses import asdict
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
    collect_interactive_options,
    load_settings,
    last_process_message,
    local_semantic_environment,
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
    def test_local_semantic_runtime_bootstraps_without_transcript_arguments(self) -> None:
        with tempfile.TemporaryDirectory() as temporary, patch(
            "guided_dataverse_setup.LOCAL_RUNTIME_DIR",
            Path(temporary) / "runtime",
        ), patch(
            "guided_dataverse_setup.importlib.util.find_spec",
            return_value=None,
        ), patch(
            "guided_dataverse_setup.subprocess.run",
        ) as runner:
            runner.return_value = subprocess.CompletedProcess([], 0, "", "")
            environment = local_semantic_environment()

        self.assertEqual(runner.call_count, 2)
        install = runner.call_args_list[0].args[0]
        self.assertIn("pip", install)
        self.assertIn("--only-binary=:all:", install)
        self.assertNotIn("transcript", " ".join(install).lower())
        verify = runner.call_args_list[1]
        self.assertIn("PYTHONPATH", verify.kwargs["env"])
        self.assertIn(str(Path(temporary) / "runtime"), environment["PYTHONPATH"])

    def test_default_output_names_make_publication_choice_unambiguous(self) -> None:
        desktop_name = OUTPUT_NAMES["desktop-validation"]
        service_name = OUTPUT_NAMES["service-refresh"]

        self.assertIn("Desktop Validation - LOCAL ONLY", desktop_name)
        self.assertIn("Power BI Service - PUBLISH THIS", service_name)
        self.assertIn("Desktop Validation - Topics - LOCAL ONLY", TOPIC_OUTPUT_NAME)
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
                 patch("guided_dataverse_setup.ask_yes_no", return_value=False), \
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

    def test_topic_launcher_forwards_explicit_semantic_opt_in_without_persisting_credentials(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            settings = root / "settings.json"
            save_settings(settings, SetupOptions(environment_url="https://savedqa.crm.dynamics.com"))
            original = settings.read_bytes()
            args = Namespace(
                mode="desktop-validation",
                settings_file=settings,
                topic_transcripts=root / "transcripts.csv",
                output=None,
                no_open=True,
                non_interactive=True,
                semantic_classification=True,
                semantic_endpoint="https://customer.openai.azure.com",
                semantic_deployment="approved-model",
            )
            with patch.dict(os.environ, {"ESS_SEMANTIC_API_KEY": "secret-sentinel"}), \
                 patch("guided_dataverse_setup.subprocess.run") as runner:
                runner.return_value.returncode = 0
                self.assertEqual(tune_topics(args), 0)
            command = runner.call_args.args[0]
            self.assertIn("--semantic-classification", command)
            self.assertEqual(
                command[command.index("--semantic-endpoint") + 1],
                "https://customer.openai.azure.com",
            )
            self.assertEqual(
                command[command.index("--semantic-deployment") + 1],
                "approved-model",
            )
            self.assertNotIn("secret-sentinel", command)
            self.assertEqual(settings.read_bytes(), original)

    def test_noninteractive_semantic_tuning_requires_endpoint_and_deployment(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            settings = root / "settings.json"
            save_settings(settings, SetupOptions(environment_url="https://savedqa.crm.dynamics.com"))
            base = {
                "mode": "desktop-validation",
                "settings_file": settings,
                "topic_transcripts": root / "transcripts.csv",
                "output": None,
                "no_open": True,
                "non_interactive": True,
                "semantic_classification": True,
            }
            with patch("guided_dataverse_setup.subprocess.run") as runner:
                with self.assertRaisesRegex(ValueError, "--semantic-endpoint"):
                    tune_topics(Namespace(**base, semantic_endpoint="", semantic_deployment="approved-model"))
                with self.assertRaisesRegex(ValueError, "--semantic-deployment"):
                    tune_topics(
                        Namespace(
                            **base,
                            semantic_endpoint="https://customer.openai.azure.com",
                            semantic_deployment="",
                        )
                    )
                runner.assert_not_called()

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
            org_data_url=(
                "https://contoso.sharepoint.com/sites/HR/Shared Documents/"
                "ESS/OrgData.csv"
            ),
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
        self.assertIn("--org-data-url", command)
        self.assertIn(options.org_data_url, command)
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

    def test_raw_monitor_feedback_does_not_require_registry(self) -> None:
        options = SetupOptions(
            environment_url="https://orgexample.crm.dynamics.com",
            feedback_input_files=["monitor.csv"],
        )

        command = build_feedback_command(options, Path("feedback-events.csv"))

        self.assertIn("monitor.csv", command)
        self.assertNotIn("--agent-registry", command)

    def test_interactive_setup_allows_every_optional_input_to_be_skipped(self) -> None:
        stored = SetupOptions(
            environment_url="https://orgexample.crm.dynamics.com"
        )
        args = Namespace(mode="desktop-validation")
        decisions = [True, False, False, False, False, False]

        with patch("guided_dataverse_setup.ask_yes_no", side_effect=decisions), \
             patch("builtins.input", return_value=""), \
             patch("guided_dataverse_setup.select_file", side_effect=AssertionError("unexpected picker")), \
             patch("builtins.print"):
            options = collect_interactive_options(args, stored)

        self.assertEqual(options.agent_registry_json, "")
        self.assertEqual(options.org_data_file, "")
        self.assertEqual(options.agent_credits_file, "")
        self.assertEqual(options.topic_overrides_json, "")
        self.assertEqual(options.feedback_input_files, [])

    def test_interactive_product_feedback_can_select_registry_when_needed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            product = root / "product-feedback.csv"
            registry = root / "agent-registry.csv"
            product.write_text(
                "Feedback Id,Feedback Type,Microsoft Response Status,Agent ID\n"
                "1,Like,Open,T_agent\n",
                encoding="utf-8",
            )
            stored = SetupOptions(
                environment_url="https://orgexample.crm.dynamics.com"
            )
            args = Namespace(mode="desktop-validation")
            decisions = [
                True, False, False, False, False, True, False, True
            ]

            with patch("guided_dataverse_setup.ask_yes_no", side_effect=decisions), \
                 patch("builtins.input", return_value=""), \
                 patch("guided_dataverse_setup.select_file", side_effect=[str(product), str(registry)]), \
                 patch("builtins.print"):
                options = collect_interactive_options(args, stored)

        self.assertEqual(options.agent_registry_json, str(registry.resolve()))
        self.assertEqual(options.feedback_input_files, [str(product.resolve())])

    def test_interactive_product_feedback_is_skipped_when_registry_is_declined(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            product = root / "product-feedback.csv"
            monitor = root / "monitor.csv"
            product.write_text(
                "Feedback Id,Feedback Type,Microsoft Response Status,Agent ID\n"
                "1,Like,Open,T_agent\n",
                encoding="utf-8",
            )
            monitor.write_text(
                "Reaction Id,Conversation ID,Reaction\n1,conversation-1,Like\n",
                encoding="utf-8",
            )
            stored = SetupOptions(
                environment_url="https://orgexample.crm.dynamics.com"
            )
            args = Namespace(mode="desktop-validation")
            decisions = [
                True, False, False, False, False,
                True, True, False, False,
            ]

            with patch("guided_dataverse_setup.ask_yes_no", side_effect=decisions), \
                 patch("builtins.input", return_value=""), \
                 patch("guided_dataverse_setup.select_file", side_effect=[str(product), str(monitor)]), \
                 patch("builtins.print") as printer:
                options = collect_interactive_options(args, stored)

        self.assertEqual(options.agent_registry_json, "")
        self.assertEqual(options.feedback_input_files, [str(monitor.resolve())])
        self.assertTrue(
            any(
                "Setup will continue" in str(call)
                for call in printer.call_args_list
            )
        )

    def test_interactive_monitor_feedback_does_not_prompt_for_registry(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            monitor = Path(directory) / "monitor.csv"
            monitor.write_text(
                "Reaction Id,Conversation ID,Reaction\n1,conversation-1,Like\n",
                encoding="utf-8",
            )
            stored = SetupOptions(
                environment_url="https://orgexample.crm.dynamics.com"
            )
            args = Namespace(mode="desktop-validation")
            decisions = [
                True, False, False, False, False, True, False
            ]

            with patch("guided_dataverse_setup.ask_yes_no", side_effect=decisions) as questions, \
                 patch("builtins.input", return_value=""), \
                 patch("guided_dataverse_setup.select_file", return_value=str(monitor)), \
                 patch("builtins.print"):
                options = collect_interactive_options(args, stored)

        self.assertEqual(options.feedback_input_files, [str(monitor.resolve())])
        self.assertFalse(
            any(
                "Select an agent registry now?" in call.args[0]
                for call in questions.call_args_list
            )
        )

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

    def saved_enhancements(self) -> SetupOptions:
        return SetupOptions(
            environment_url="https://orgexample.crm.dynamics.com",
            agent_registry_json="missing-registry.json",
            org_data_file="missing-users.csv",
            org_data_url="https://contoso.sharepoint.com/sites/HR/OrgData.csv",
            agent_credits_file="missing-credits.csv",
            topic_overrides_json="missing-topics.json",
            feedback_events_json="missing-feedback.json",
            feedback_input_files=["missing-monitor.csv"],
        )

    def setup_arguments(self, *arguments: str) -> Namespace:
        from guided_dataverse_setup import parse_args

        with patch("sys.argv", ["setup", *arguments]):
            return parse_args()

    def test_fresh_setup_defaults_to_skipping_every_enhancement_in_both_modes(self) -> None:
        for mode in ("desktop-validation", "service-refresh"):
            with self.subTest(mode=mode), \
                 patch("guided_dataverse_setup.prompt_environment", return_value="https://orgexample.crm.dynamics.com"), \
                 patch("guided_dataverse_setup.ask_yes_no", return_value=False) as questions, \
                 patch("guided_dataverse_setup.select_file", side_effect=AssertionError("unexpected picker")), \
                 patch("builtins.print"):
                options = collect_interactive_options(Namespace(mode=mode), None)
            self.assertEqual(options, SetupOptions(environment_url="https://orgexample.crm.dynamics.com"))
            self.assertTrue(all(call.kwargs["default"] is False for call in questions.call_args_list))

    def test_cancelled_replacement_clears_each_saved_enhancement(self) -> None:
        cases = (
            ("desktop-validation", "agent_registry_json"),
            ("desktop-validation", "org_data_file"),
            ("desktop-validation", "agent_credits_file"),
            ("desktop-validation", "topic_overrides_json"),
            ("desktop-validation", "feedback_events_json"),
            ("service-refresh", "agent_registry_json"),
            ("service-refresh", "org_data_url"),
            ("service-refresh", "topic_overrides_json"),
            ("service-refresh", "feedback_events_json"),
        )
        for mode, field_name in cases:
            stored = SetupOptions(environment_url="https://orgexample.crm.dynamics.com")
            setattr(stored, field_name, getattr(self.saved_enhancements(), field_name))
            before = asdict(stored)
            with self.subTest(mode=mode, field=field_name), \
                 patch("guided_dataverse_setup.prompt_environment", return_value=stored.environment_url), \
                 patch("guided_dataverse_setup.ask_yes_no", return_value=True), \
                 patch("guided_dataverse_setup.select_file", return_value=""), \
                 patch("builtins.input", side_effect=lambda prompt: "" if prompt.startswith("Paste ") else "replace"), \
                 patch("builtins.print"):
                options = collect_interactive_options(Namespace(mode=mode), stored)
            self.assertEqual(getattr(options, field_name), "")
            self.assertEqual(asdict(stored), before)
            if field_name.startswith("feedback"):
                self.assertEqual(options.feedback_input_files, [])

    def test_saved_enhancements_can_be_skipped_independently_in_both_modes(self) -> None:
        for mode in ("desktop-validation", "service-refresh"):
            cases = [
                ("agent_registry_json", "Agent registry"),
                ("org_data_file" if mode == "desktop-validation" else "org_data_url", "Organization data"),
                ("topic_overrides_json", "Approved topic rules"),
                ("feedback_events_json", "Microsoft 365 feedback"),
            ]
            if mode == "desktop-validation":
                cases.append(("agent_credits_file", "Copilot credit consumption"))
            for field_name, label in cases:
                stored = self.saved_enhancements()
                before = asdict(stored)
                with self.subTest(mode=mode, field=field_name), \
                     patch("guided_dataverse_setup.prompt_environment", return_value=stored.environment_url), \
                     patch("guided_dataverse_setup.ask_yes_no", side_effect=lambda prompt, **kwargs: "Reuse" in prompt), \
                     patch("guided_dataverse_setup.product_feedback_inputs", return_value=[]), \
                     patch("guided_dataverse_setup.select_file", side_effect=AssertionError("unexpected picker")), \
                     patch("builtins.input", side_effect=lambda prompt: "skip" if label in prompt else "keep"), \
                     patch("builtins.print"):
                    options = collect_interactive_options(Namespace(mode=mode), stored)
                    self.assertEqual(getattr(options, field_name), "")
                    for unrelated, _ in cases:
                        if unrelated != field_name:
                            self.assertEqual(getattr(options, unrelated), before[unrelated])
                    if mode == "service-refresh":
                        self.assertEqual(options.org_data_file, "")
                        self.assertEqual(options.agent_credits_file, "")
                    if field_name.startswith("org_data"):
                        self.assertEqual((options.org_data_file, options.org_data_url), ("", ""))
                    if field_name == "feedback_events_json":
                        self.assertEqual(options.feedback_input_files, [])
                    self.assertEqual(asdict(stored), before)

    def test_desktop_organization_can_be_selected_without_other_enhancements(self) -> None:
        roster = Path("users.csv").resolve()
        with patch("guided_dataverse_setup.prompt_environment", return_value="https://orgexample.crm.dynamics.com"), \
             patch("guided_dataverse_setup.ask_yes_no", side_effect=lambda prompt, **kwargs: "Organization data" in prompt), \
             patch("guided_dataverse_setup.select_file", return_value=str(roster)) as picker, \
             patch("builtins.print"):
            options = collect_interactive_options(Namespace(mode="desktop-validation"), None)
        self.assertEqual(options, SetupOptions(environment_url="https://orgexample.crm.dynamics.com", org_data_file=str(roster)))
        picker.assert_called_once()

    def test_service_organization_can_be_selected_without_other_enhancements(self) -> None:
        url = "https://contoso.sharepoint.com/sites/HR/OrgData.csv"
        with patch("guided_dataverse_setup.prompt_environment", return_value="https://orgexample.crm.dynamics.com"), \
             patch("guided_dataverse_setup.ask_yes_no", side_effect=lambda prompt, **kwargs: "Organization data" in prompt), \
             patch("builtins.input", return_value=url), \
             patch("guided_dataverse_setup.select_file", side_effect=AssertionError("unexpected local picker")), \
             patch("builtins.print"):
            options = collect_interactive_options(Namespace(mode="service-refresh"), None)
        self.assertEqual(options, SetupOptions(environment_url="https://orgexample.crm.dynamics.com", org_data_url=url))

    def test_saved_enhancements_default_to_skip_without_deliberate_keep(self) -> None:
        for mode in ("desktop-validation", "service-refresh"):
            with self.subTest(mode=mode):
                stored = self.saved_enhancements()
                before = asdict(stored)
                with patch("guided_dataverse_setup.prompt_environment", return_value=stored.environment_url), \
                     patch("guided_dataverse_setup.ask_yes_no", return_value=True), \
                     patch("builtins.input", return_value=""), \
                     patch("guided_dataverse_setup.select_file", side_effect=AssertionError("unexpected picker")), \
                     patch("builtins.print"):
                    options = collect_interactive_options(Namespace(mode=mode), stored)
                self.assertEqual(options, SetupOptions(environment_url=stored.environment_url))
                self.assertEqual(asdict(stored), before)

    def test_explicit_registry_skip_keeps_monitor_feedback_and_other_selections(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            product = root / "product.csv"
            monitor = root / "monitor.csv"
            product.write_text("Feedback Id,Feedback Type,Microsoft Response Status,Agent ID\n1,Like,Open,T_agent\n", encoding="utf-8")
            monitor.write_text("Reaction Id,Conversation ID,Reaction\n1,conversation-1,Like\n", encoding="utf-8")
            for mode in ("desktop-validation", "service-refresh"):
                with self.subTest(mode=mode):
                    stored = SetupOptions(
                        environment_url="https://orgexample.crm.dynamics.com", agent_registry_json="previous-registry.json",
                        org_data_file="users.csv", org_data_url="https://contoso.sharepoint.com/sites/HR/OrgData.csv",
                        feedback_events_json="previous-prepared-feedback.json", feedback_input_files=[str(product), str(monitor)],
                    )
                    before = asdict(stored)
                    args = self.setup_arguments("--mode", mode, "--skip-agent-registry")
                    with patch("guided_dataverse_setup.prompt_environment", return_value=stored.environment_url), \
                         patch("guided_dataverse_setup.ask_yes_no", side_effect=lambda prompt, **kwargs: "Reuse" in prompt) as questions, \
                         patch("builtins.input", return_value="keep"), \
                         patch("guided_dataverse_setup.select_file", side_effect=AssertionError("skipped registry must not be reopened")), \
                         patch("builtins.print"):
                        options = collect_interactive_options(args, stored)
                    self.assertEqual(options.agent_registry_json, "")
                    self.assertEqual(options.feedback_input_files, [str(monitor)])
                    self.assertEqual(options.feedback_events_json, "")
                    self.assertEqual(options.org_data_file if mode == "desktop-validation" else options.org_data_url,
                                     stored.org_data_file if mode == "desktop-validation" else stored.org_data_url)
                    self.assertFalse(any("registry" in call.args[0].lower() for call in questions.call_args_list))
                    self.assertEqual(asdict(stored), before)

    def test_prepared_feedback_can_be_selected_without_raw_exports(self) -> None:
        prepared = Path("monitor-events.json").resolve()
        with patch("guided_dataverse_setup.prompt_environment", return_value="https://orgexample.crm.dynamics.com"), \
             patch("guided_dataverse_setup.ask_yes_no", side_effect=lambda prompt, **kwargs: "Microsoft 365 feedback" in prompt), \
             patch("guided_dataverse_setup.select_file", return_value=str(prepared)), \
             patch("builtins.print"):
            options = collect_interactive_options(Namespace(mode="service-refresh"), None)
        self.assertEqual(options.feedback_events_json, str(prepared))
        self.assertEqual(options.feedback_input_files, [])
        self.assertEqual(options.agent_registry_json, "")

    def test_cli_skip_flags_clear_only_the_selected_enhancement(self) -> None:
        cases = (
            ("--skip-agent-registry", ("agent_registry_json",)),
            ("--skip-org-data", ("org_data_file", "org_data_url")),
            ("--skip-agent-credits", ("agent_credits_file",)),
            ("--skip-topic-overrides", ("topic_overrides_json",)),
            ("--skip-feedback", ("feedback_events_json", "feedback_input_files")),
        )
        for flag, fields in cases:
            with self.subTest(flag=flag), patch("sys.stderr"):
                args = self.setup_arguments("--non-interactive", flag)
                stored = self.saved_enhancements()
                previous = asdict(stored)
                options = merge_cli_options(args, stored)
                expected = dict(previous)
                for name in fields:
                    expected[name] = [] if name == "feedback_input_files" else ""
                self.assertEqual(asdict(options), expected)
                self.assertEqual(asdict(stored), previous)

    def test_skipping_all_saved_missing_files_never_prepares_or_passes_them(self) -> None:
        flags = ("--skip-agent-registry", "--skip-org-data", "--skip-agent-credits", "--skip-topic-overrides", "--skip-feedback")
        for mode in ("desktop-validation", "service-refresh"):
            with self.subTest(mode=mode), patch("sys.stderr"):
                args = self.setup_arguments("--mode", mode, "--non-interactive", *flags)
                options = merge_cli_options(args, self.saved_enhancements())
                with patch("guided_dataverse_setup.subprocess.run", side_effect=AssertionError("unexpected normalization")):
                    self.assertIs(prepare_feedback(options), options)
                command = build_command(mode, options, Path("output.pbit"))
                for argument in ("--agent-registry-json", "--org-data-file", "--org-data-url", "--agent-credits-file", "--topic-overrides-json", "--feedback-events-json"):
                    self.assertNotIn(argument, command)
                self.assertEqual(options, SetupOptions(environment_url="https://orgexample.crm.dynamics.com"))

    def test_supply_and_skip_arguments_are_rejected_as_conflicting(self) -> None:
        cases = (
            ("--skip-agent-registry", "--agent-registry-json", "registry.json"),
            ("--skip-org-data", "--org-data-file", "users.csv"),
            ("--skip-org-data", "--org-data-url", "https://contoso.sharepoint.com/sites/HR/OrgData.csv"),
            ("--skip-agent-credits", "--agent-credits-file", "credits.csv"),
            ("--skip-topic-overrides", "--topic-overrides-json", "rules.json"),
            ("--skip-feedback", "--feedback-events-json", "feedback.json"),
            ("--skip-feedback", "--feedback-input", "monitor.csv"),
        )
        for skip, supplied, value in cases:
            error = io.StringIO()
            with self.subTest(skip=skip, supplied=supplied), patch("sys.stderr", error):
                with self.assertRaises(SystemExit) as failure:
                    self.setup_arguments(skip, supplied, value)
            self.assertEqual(failure.exception.code, 2)
            self.assertIn("not allowed with argument", error.getvalue())

    def test_replacing_local_organization_clears_a_saved_cloud_selection(self) -> None:
        stored = self.saved_enhancements()
        options = merge_cli_options(self.setup_arguments("--org-data-file", "new-users.csv"), stored)
        self.assertEqual(options.org_data_file, str(Path("new-users.csv").resolve()))
        self.assertEqual(options.org_data_url, "")
        self.assertNotEqual(stored.org_data_file, options.org_data_file)

    def test_guided_skip_flags_do_not_prompt_or_open_inherited_files(self) -> None:
        flags = ("--skip-agent-registry", "--skip-org-data", "--skip-agent-credits", "--skip-topic-overrides", "--skip-feedback")
        for mode in ("desktop-validation", "service-refresh"):
            with self.subTest(mode=mode), patch("sys.stderr"):
                args = self.setup_arguments("--mode", mode, *flags)
                with patch("guided_dataverse_setup.prompt_environment", return_value="https://orgexample.crm.dynamics.com"), \
                     patch("guided_dataverse_setup.ask_yes_no", return_value=True) as questions, \
                     patch("guided_dataverse_setup.select_file", side_effect=AssertionError("unexpected picker")), \
                     patch("builtins.input", side_effect=AssertionError("unexpected enhancement prompt")), \
                     patch("builtins.print"):
                    options = collect_interactive_options(args, self.saved_enhancements())
                self.assertEqual(options, SetupOptions(environment_url="https://orgexample.crm.dynamics.com"))
                self.assertEqual(questions.call_count, 1)

    def test_topic_launcher_forwards_skip_controls(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            settings = root / "settings.json"
            save_settings(settings, self.saved_enhancements())
            flags = ("--skip-agent-registry", "--skip-org-data", "--skip-agent-credits", "--skip-feedback")
            with patch("sys.stderr"):
                args = self.setup_arguments("--tune-topics", "--non-interactive", "--no-open", "--settings-file", str(settings), "--topic-transcripts", str(root / "transcripts.csv"), *flags)
            with patch("guided_dataverse_setup.subprocess.run") as runner:
                runner.return_value.returncode = 0
                self.assertEqual(tune_topics(args), 0)
            for flag in flags:
                self.assertIn(flag, runner.call_args.args[0])

    def test_topic_tuning_cannot_also_skip_the_topic_rules_it_builds(self) -> None:
        error = io.StringIO()
        with patch("sys.stderr", error), self.assertRaises(SystemExit) as failure:
            self.setup_arguments("--tune-topics", "--skip-topic-overrides")
        self.assertEqual(failure.exception.code, 2)
        self.assertIn("cannot be combined with --tune-topics", error.getvalue())

    def test_v23_version_and_template_names_are_explicit(self) -> None:
        from guided_dataverse_setup import (
            ROOT,
            SOURCE_TEMPLATE,
            parse_args,
            validate_runtime,
        )

        output = io.StringIO()
        with patch("sys.argv", ["setup", "--version"]), patch("sys.stdout", output), patch("sys.stderr"), self.assertRaises(SystemExit) as result:
            parse_args()
        self.assertEqual(result.exception.code, 0)
        self.assertIn("V23", output.getvalue())
        self.assertIn("Python 3.10-3.14", output.getvalue())
        self.assertIn("V23", SOURCE_TEMPLATE.name)
        self.assertTrue(SOURCE_TEMPLATE.is_file())
        for name in (*OUTPUT_NAMES.values(), TOPIC_OUTPUT_NAME):
            self.assertIn("V23", name)
        with patch(
            "guided_dataverse_setup.sys.version_info",
            (3, 15, 0),
        ), self.assertRaisesRegex(RuntimeError, "3.15"):
            validate_runtime()
        with patch(
            "guided_dataverse_setup.sys.version_info",
            (3, 14, 0),
        ):
            validate_runtime()
        launcher = (ROOT / "START-HERE-DATAVERSE.cmd").read_text(
            encoding="utf-8"
        )
        self.assertIn("3.14 3.13 3.12 3.11 3.10", launcher)
        self.assertIn("Python 3.15 is not yet supported", launcher)
        self.assertNotIn(
            'py -3 "tools\\guided_dataverse_setup.py"',
            launcher,
        )

    def test_independent_optional_build_matrix_ignores_all_skipped_saved_files(self) -> None:
        from build_service_refresh_template import expression_text
        from guided_dataverse_setup import ROOT, main

        flags = ("--skip-agent-registry", "--skip-org-data", "--skip-agent-credits", "--skip-topic-overrides", "--skip-feedback")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            topics = root / "topics.json"
            topics.write_text(json.dumps([{"Locale": "en", "Vertical": "Customer", "CanonicalTopic": "Enrollment Matrix",
                                          "Keywords": "device enrollment", "Exclusions": "", "Priority": 120}]), encoding="utf-8")
            prepared = root / "feedback.json"
            prepared.write_text(json.dumps([{"FeedbackEventId": "monitor-matrix", "ConversationId": "conversation-matrix",
                                            "AgentId": "", "FeedbackSource": "MonitorReactions.csv", "FeedbackVerdict": "Thumbs Up"}]), encoding="utf-8")
            raw = root / "monitor.csv"
            raw.write_text("Reaction Id,Conversation ID,Reaction\nmonitor-matrix,conversation-matrix,Like\n", encoding="utf-8")
            sample = ROOT / "SampleData"
            for mode in ("desktop-validation", "service-refresh"):
                organization = ["--org-data-file", str(sample / "OrgData.csv")] if mode == "desktop-validation" else [
                    "--org-data-url", "https://qademo.sharepoint.com/sites/HR/OrgData.csv",
                ]
                cases = [
                    ("baseline", [], None),
                    ("registry", ["--agent-registry-json", str(sample / "agent-registry.json")], "--skip-agent-registry"),
                    ("organization", organization, "--skip-org-data"),
                    ("topics", ["--topic-overrides-json", str(topics)], "--skip-topic-overrides"),
                    ("prepared-feedback", ["--feedback-events-json", str(prepared)], "--skip-feedback"),
                    ("raw-feedback", ["--feedback-input", str(raw)], "--skip-feedback"),
                ]
                if mode == "desktop-validation":
                    cases.append(("credits", ["--agent-credits-file", str(sample / "EntitlementConsumptionTenantPerUserDetailsReport_MCSMessages_30_SYNTHETIC.csv")], "--skip-agent-credits"))
                for name, selection, selected_flag in cases:
                    with self.subTest(mode=mode, enhancement=name):
                        destination = root / mode / name
                        settings = destination / "settings.json"
                        save_settings(settings, self.saved_enhancements())
                        previous = settings.read_bytes()
                        output = destination / "result.pbit"
                        arguments = ["setup", "--mode", mode, "--non-interactive", "--no-open", "--settings-file", str(settings),
                                     "--output", str(output), *[flag for flag in flags if flag != selected_flag], *selection]
                        with patch("sys.argv", arguments), patch("builtins.print"), \
                             patch("builtins.input", side_effect=AssertionError("unexpected non-interactive prompt")), \
                             patch("guided_dataverse_setup.PREPARED_FEEDBACK", destination / "prepared" / "feedback-events.csv"):
                            self.assertEqual(main(), 0)
                        if mode == "service-refresh":
                            self.assertEqual(settings.read_bytes(), previous)
                        else:
                            saved = load_settings(settings)
                            active = {
                                "registry": bool(saved.agent_registry_json),
                                "organization": bool(saved.org_data_file or saved.org_data_url),
                                "credits": bool(saved.agent_credits_file),
                                "topics": bool(saved.topic_overrides_json),
                                "feedback": bool(saved.feedback_events_json or saved.feedback_input_files),
                            }
                            expected = "feedback" if "feedback" in name else name
                            self.assertEqual({key for key, enabled in active.items() if enabled}, set() if name == "baseline" else {expected})
                        with zipfile.ZipFile(output) as package:
                            self.assertIsNone(package.testzip())
                            schema = json.loads(package.read("DataModelSchema").decode("utf-16-le"))
                        expressions = {item["name"]: expression_text(item["expression"]) for item in schema["model"]["expressions"]}
                        serialized = json.dumps(schema)
                        for stale in ("missing-registry.json", "missing-users.csv", "missing-credits.csv", "missing-topics.json", "missing-feedback.json", "missing-monitor.csv"):
                            self.assertNotIn(stale, serialized)
                        self.assertEqual("ess-synthetic" in expressions["Agent Registry JSON"], name == "registry")
                        self.assertEqual("Enrollment Matrix" in expressions["Customer Topic Overrides JSON (optional)"], name == "topics")
                        self.assertEqual("conversation-matrix" in expressions["Feedback Events JSON (optional)"], "feedback" in name)
                        if mode == "service-refresh":
                            self.assertNotIn("File.Contents", serialized)
                            self.assertNotIn("Org Data File", expressions)
                            self.assertEqual("SharePoint.Files" in serialized, name == "organization")
                        else:
                            self.assertEqual(str((sample / "OrgData.csv").resolve()) in expressions["Org Data File"], name == "organization")
                            self.assertEqual("MCSMessages_30_SYNTHETIC.csv" in expressions["Agent Credits  (optional)"], name == "credits")

    def test_settings_round_trip(self) -> None:
        options = SetupOptions(
            environment_url="https://orgexample.crm.dynamics.com",
            org_data_file="users.csv",
            org_data_url=(
                "https://contoso.sharepoint.com/sites/HR/Shared Documents/"
                "ESS/OrgData.csv"
            ),
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
            org_data_url="https://customer-a.sharepoint.com/sites/HR/OrgData.csv",
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
        self.assertEqual(options.org_data_url, "")
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
                    {
                        "contract": "Customer Conversation Topics",
                        "classifiedConversations": 18,
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
                "Human-approved conversation topics: 18 rows",
                "Prepared feedback: 6 rows",
            ],
        )

    def test_validation_summary_reports_cloud_org_data(self) -> None:
        summary = validation_summary(
            {
                "organizationDataUrl": (
                    "https://contoso.sharepoint.com/sites/HR/OrgData.csv"
                ),
                "sources": [],
            }
        )

        self.assertEqual(
            summary,
            [
                "Dataverse Environment URL: valid",
                "Organization data URL format: valid",
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
