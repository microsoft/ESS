import csv
import json
import os
import subprocess
import sys
import tempfile
import unittest
import zipfile
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

from ess_topic_tuner import (
    OVERRIDE_COLUMNS, apply_dataverse_rules, expand_customer_terms, finish_analysis, next_command,
    rules_from_override_rows, validate_tuner_output,
)
from guided_dataverse_setup import SetupOptions, TOPIC_OUTPUT_NAME, load_settings, save_settings
from topic_classifier import classify, load_rules, normalize


class TopicTunerTests(unittest.TestCase):
    def test_default_tuner_output_uses_guarded_filename(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            args = Namespace(
                template_output=None,
                settings_file=root / "missing-settings.json",
                input=None,
                taxonomy=None,
                overrides=None,
                apply=None,
                review=None,
                output_dir=None,
            )
            with patch("ess_topic_tuner.GENERATED_DIR", root):
                self.assertEqual(
                    validate_tuner_output(args),
                    root / TOPIC_OUTPUT_NAME,
                )

    def test_punctuation_only_rules_cannot_be_directly_applied_or_built(self) -> None:
        repo = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            rules = root / "rules.json"
            settings = root / "settings.json"
            save_settings(settings, SetupOptions(environment_url="https://savedqa.crm.dynamics.com"))
            output = root / "topics.pbit"
            output.write_bytes(b"protected prior PBIT sentinel")
            for keywords in ("---|?!", "\u2014\u2019\uff0c", "\U00010d6e\U0001e5ff"):
                rules.write_text(json.dumps([{"Locale": "en-US", "Vertical": "Customer", "CanonicalTopic": "Invalid",
                                             "Keywords": keywords, "Exclusions": "", "Priority": 120}]), encoding="utf-8")
                preserved = {path: path.read_bytes() for path in root.iterdir()}
                commands = (
                    [sys.executable, str(repo / "tools/ess_topic_tuner.py"), "--apply", str(rules), "--settings-file", str(settings),
                     "--template-output", str(output), "--no-open"],
                    [sys.executable, str(repo / "tools/build_service_refresh_template.py"), "--input", str(repo / "ESS Dashboard - Dynamic Topics (Dataverse) V21.pbit"),
                     "--environment-url", "https://savedqa.crm.dynamics.com", "--output", str(output), "--topic-overrides-json", str(rules)],
                    [sys.executable, str(repo / "tools/guided_dataverse_setup.py"), "--settings-file", str(settings), "--output", str(output),
                     "--topic-overrides-json", str(rules), "--non-interactive", "--no-open"],
                )
                for command in commands:
                    with self.subTest(keywords=repr(keywords), command=Path(command[1]).name):
                        completed = subprocess.run(command, capture_output=True, text=True)
                        self.assertNotEqual(completed.returncode, 0, completed.stdout + completed.stderr)
                        self.assertIn("Keywords after normalization", completed.stdout + completed.stderr)
                        self.assertEqual({path: path.read_bytes() for path in root.iterdir()}, preserved)

    def test_unicode_punctuation_has_the_same_matching_form_as_ascii_punctuation(self) -> None:
        for separator in ("\u2010", "\u2011", "\u2013", "\u2014", "\u2018", "\u2019", "\u201c", "\u201d", "\u3001",
                          "\uff0c", "\u060c", "\U00010d6e", "\U0001e5ff"):
            self.assertEqual(normalize(f"Device{separator}Enrollment"), "device enrollment", repr(separator))
            rules = rules_from_override_rows([{"Enabled": "true", "Locale": "en", "Vertical": "Customer", "CanonicalTopic": "Enrollment",
                                               "Keywords": f"Device{separator}Enrollment|device enrollment", "Exclusions": "", "Priority": 120}])
            self.assertEqual(rules[0]["Keywords"], "device enrollment|devices enrollment")
            self.assertEqual(classify(f"devices{separator}enrollment", "en", rules)["score"], 3)

    def test_regional_rule_locales_are_canonical_in_parsing_and_merge_keys(self) -> None:
        from ess_topic_tuner import customer_rule_key, merge_customer_rules

        row = {"Enabled": "true", "Locale": "en-US", "Vertical": "Customer", "CanonicalTopic": "Enrollment",
               "Keywords": "device enrollment", "Exclusions": "", "Priority": 120}
        rules = rules_from_override_rows([row])
        self.assertEqual(rules[0]["Locale"], "en")
        self.assertEqual(customer_rule_key(row), customer_rule_key({**row, "Locale": "en"}))
        self.assertEqual(len(merge_customer_rules(rules, rules_from_override_rows([{**row, "Locale": "EN-gb"}]), [])), 1)
        self.assertEqual(classify("devices enrollment", "en-AU", rules)["topic"], "Enrollment")

    def test_punctuation_only_keywords_are_rejected_by_tuner_and_json_validator(self) -> None:
        from build_service_refresh_template import validate_topic_overrides

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "rules.json"
            for keywords in ("---", "...|?!", "\u2014\u2019\uff0c", "\U00010d6e\U0001e5ff"):
                row = {"Enabled": "true", "Locale": "en-US", "Vertical": "Customer", "CanonicalTopic": "Invalid",
                       "Keywords": keywords, "Exclusions": "", "Priority": 120}
                with self.assertRaisesRegex(ValueError, "[Kk]eywords"):
                    rules_from_override_rows([row])
                path.write_text(json.dumps([{column: row[column] for column in row if column != "Enabled"}]), encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "[Kk]eywords"):
                    validate_topic_overrides(path)

    def test_expanded_terms_serialize_and_score_identically_for_normalized_matches(self) -> None:
        baseline = {"Enabled": "true", "Locale": "en", "Vertical": "Customer", "CanonicalTopic": "Enrollment",
                    "Keywords": "device enrollment", "Exclusions": "lost device", "Priority": 120}
        expected = rules_from_override_rows([baseline])
        serialized = json.dumps(expected, sort_keys=True)
        for keywords in ("device enrollment", "Device Enrollment", "devices enrollment", "device-enrollment",
                         "DEVICE ENROLLMENT|device enrollment|Devices enrollment"):
            for exclusions in ("lost device", "Lost Device|lost device|lost devices"):
                with self.subTest(keywords=keywords, exclusions=exclusions):
                    rules = rules_from_override_rows([{**baseline, "Keywords": keywords, "Exclusions": exclusions}])
                    self.assertEqual(json.dumps(rules, sort_keys=True), serialized)
                    for field in ("Keywords", "Exclusions"):
                        terms = rules[0][field].split("|")
                        self.assertEqual(len(terms), len({normalize(term) for term in terms}))
                        self.assertTrue(all(term == normalize(term) for term in terms))
                        self.assertEqual(expand_customer_terms(rules[0][field], "en"), rules[0][field])
                    for prompt in ("device enrollment", "devices enrollment", "DEVICE ENROLLMENT", "devices enrollment lost devices"):
                        self.assertEqual(classify(prompt, "en", rules), classify(prompt, "en", expected))
                    self.assertEqual(classify("device enrollment", "en", rules)["score"], 3)
                    self.assertEqual(classify("devices enrollment", "en", rules)["score"], 3)
        for locale in ("es", "zh"):
            with self.subTest(locale=locale):
                expected = rules_from_override_rows([{**baseline, "Locale": locale}])
                rules = rules_from_override_rows([{**baseline, "Locale": locale, "Keywords": "Device Enrollment|device enrollment"}])
                self.assertEqual(rules, expected)
                self.assertEqual(classify("device enrollment", locale, rules), classify("device enrollment", locale, expected))
                self.assertEqual(rules[0]["Keywords"], "device enrollment")

    def test_saved_singular_rule_rebuilds_pbit_with_plural_variant_once(self) -> None:
        repo = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            saved = root / "saved-rules.json"
            old_rules = [{"Locale": "en", "Vertical": "Customer", "CanonicalTopic": "Device Enrollment",
                          "Keywords": "device enrollment", "Exclusions": "", "Priority": 120}]
            saved.write_text(json.dumps(old_rules), encoding="utf-8")
            original_saved = saved.read_bytes()
            settings = root / "settings.json"
            save_settings(settings, SetupOptions(environment_url="https://savedqa.crm.dynamics.com", topic_overrides_json=str(saved)))
            template = root / "topics.pbit"
            baseline = subprocess.run([sys.executable, str(repo / "tools/guided_dataverse_setup.py"), "--mode", "desktop-validation",
                                       "--settings-file", str(settings), "--output", str(template), "--non-interactive", "--no-open"],
                                      capture_output=True, text=True)
            self.assertEqual(baseline.returncode, 0, baseline.stdout + baseline.stderr)
            old_template = template.read_bytes()
            with zipfile.ZipFile(template) as package:
                schema = json.loads(package.read("DataModelSchema").decode("utf-16-le"))
            embedded = next(item["expression"] for item in schema["model"]["expressions"]
                            if item["name"] == "Customer Topic Overrides JSON (optional)")
            self.assertIn(json.dumps(old_rules, separators=(",", ":")).replace('"', '""'), embedded)
            self.assertNotIn("devices enrollment", embedded)
            source = root / "transcripts.csv"
            source.write_text("session_id,first_user_prompt,locale\nplural,devices enrollment,en\n", encoding="utf-8")
            output = root / "review"
            command = [sys.executable, str(repo / "tools/ess_topic_tuner.py"), "--input", str(source), "--output-dir", str(output),
                       "--settings-file", str(settings), "--template-output", str(template), "--non-interactive", "--no-open"]
            completed = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            self.assertIn("READY:", completed.stdout)
            report = json.loads((output / "privacy-report.json").read_text(encoding="utf-8"))
            self.assertEqual(report["autoValidatedNativeTopicRules"], 0)
            self.assertEqual(report["newOrUpdatedApprovedRules"], 1)
            self.assertTrue(report["publicationRequired"])
            selected = Path(load_settings(settings).topic_overrides_json)
            self.assertEqual(selected.resolve(), (output / "customer-topic-overrides.json").resolve())
            rules = json.loads(selected.read_text(encoding="utf-8"))
            self.assertEqual(rules, [{**old_rules[0], "Keywords": "device enrollment|devices enrollment"}])
            self.assertNotEqual(template.read_bytes(), old_template)
            with zipfile.ZipFile(template) as package:
                self.assertIsNone(package.testzip())
                schema = json.loads(package.read("DataModelSchema").decode("utf-16-le"))
            embedded = next(item["expression"] for item in schema["model"]["expressions"]
                            if item["name"] == "Customer Topic Overrides JSON (optional)")
            self.assertIn(json.dumps(rules, separators=(",", ":")).replace('"', '""'), embedded)
            self.assertIn("devices enrollment", embedded)
            self.assertEqual(saved.read_bytes(), original_saved)
            preserved = {path: path.read_bytes() for path in (saved, selected, settings, template)}
            repeated = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(repeated.returncode, 0, repeated.stdout + repeated.stderr)
            self.assertIn("STOP:", repeated.stdout)
            reports = list(output.glob("run-*/privacy-report.json"))
            self.assertEqual(len(reports), 1)
            repeated_report = json.loads(reports[0].read_text(encoding="utf-8"))
            self.assertFalse(repeated_report["publicationRequired"])
            self.assertEqual(repeated_report["newOrUpdatedApprovedRules"], 0)
            for path, original in preserved.items():
                self.assertEqual(path.read_bytes(), original, str(path))

    def test_saved_rule_merge_preserves_unrelated_rules_and_resolves_conflicts_deterministically(self) -> None:
        from ess_topic_tuner import customer_rule_key, merge_customer_rules

        def rule(topic: str, keywords: str, priority: int, locale: str = "en", exclusions: str = "") -> dict:
            return {"Locale": locale, "Vertical": "Customer", "CanonicalTopic": topic, "Keywords": keywords,
                    "Exclusions": exclusions, "Priority": priority, "RuleSource": "Customer"}

        saved = [rule("Saved conflict", "zorbex flindle|veltrix snorple", 999), rule("Unrelated saved", "crindle morplex", 120),
                 rule("Separate locale", "zorbex flindle|veltrix snorple", 120, locale="es"),
                 rule("Separate exclusions", "zorbex flindle|veltrix snorple", 120, exclusions="blocked")]
        explicit = [rule("Explicit chosen", "VELTRIX snorple|zorbex flindle", 10), rule("Lower explicit duplicate", "zorbex flindle|veltrix snorple", 1),
                    rule("Explicit unrelated", "glorbex tremple", 120), rule("Explicit unrelated", "glorbex tremple", 120)]
        learned = [rule("Learned conflict", "veltrix snorple|zorbex flindle", 2000), rule("Saved conflict suggestion", "crindle morplex", 2000),
                   rule("New learned", "snorvex blimple", 120), rule("Zulu learned duplicate", "snorvex blimple", 120)]
        original = json.dumps([saved, explicit, learned], sort_keys=True)
        merged = merge_customer_rules(saved, explicit, learned)
        self.assertEqual({item["CanonicalTopic"] for item in merged}, {
            "Explicit chosen", "Unrelated saved", "Separate locale", "Separate exclusions", "Explicit unrelated", "New learned",
        })
        self.assertEqual(len({customer_rule_key(item) for item in merged}), len(merged))
        for groups in ((saved[::-1], explicit, learned), (saved, explicit[::-1], learned),
                       (saved, explicit, learned[::-1]), (saved[::-1], explicit[::-1], learned[::-1])):
            self.assertEqual(merge_customer_rules(*groups), merged)
        self.assertEqual(json.dumps([saved, explicit, learned], sort_keys=True), original)

    def test_saved_rules_missing_or_invalid_fail_before_analysis_or_writes(self) -> None:
        from ess_topic_tuner import main

        valid_rule = {"Locale": "en", "Vertical": "Customer", "CanonicalTopic": "Previously Approved", "Keywords": "zorbex flindle",
                      "Exclusions": "", "Priority": 120}
        invalid = {"missing": None, "malformed": b"{invalid", "not-an-array": b"{}", "missing-fields": b"[{}]", "empty": b"[]",
                   "blank-label": json.dumps([{**valid_rule, "CanonicalTopic": ""}]).encode(),
                   "punctuation": json.dumps([{**valid_rule, "Keywords": "---|?!"}]).encode(),
                   "unicode-punctuation": json.dumps([{**valid_rule, "Keywords": "\u2014\u2019\uff0c"}]).encode(),
                   "invalid-priority": json.dumps([{**valid_rule, "Priority": "invalid"}]).encode()}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "transcripts.csv"
            source.write_bytes(b"protected transcript sentinel")
            template = root / "topics.pbit"
            template.write_bytes(b"protected existing PBIT sentinel")
            settings = root / "settings.json"
            for name, payload in invalid.items():
                saved = root / f"saved-{name}.json"
                if payload is not None:
                    saved.write_bytes(payload)
                save_settings(settings, SetupOptions(environment_url="https://savedqa.crm.dynamics.com", topic_overrides_json=str(saved)))
                preserved = {path: path.read_bytes() for path in root.rglob("*") if path.is_file()}
                with self.subTest(saved=name), \
                     patch("sys.argv", ["tuner", "--input", str(source), "--output-dir", str(root / "not-created"),
                                         "--settings-file", str(settings), "--template-output", str(template), "--no-open"]), \
                     patch("ess_topic_tuner.load_rules", side_effect=AssertionError("unexpected taxonomy analysis")), \
                     patch("ess_topic_tuner.load_input", side_effect=AssertionError("unexpected transcript analysis")), \
                     patch("ess_topic_tuner.write_csv", side_effect=AssertionError("unexpected diagnostic write")), \
                     patch("ess_topic_tuner.subprocess.run", side_effect=AssertionError("unexpected builder")):
                    with self.assertRaisesRegex(ValueError, "Saved topic rules .* are missing or invalid") as failure:
                        main()
                    self.assertIn(saved.name, str(failure.exception))
                self.assertEqual({path: path.read_bytes() for path in root.rglob("*") if path.is_file()}, preserved)
                self.assertFalse((root / "not-created").exists())

    def test_saved_explicit_and_learned_rules_are_merged_in_analysis_outputs(self) -> None:
        repo = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            saved = root / "saved-rules.json"
            old = {"Locale": "en", "Vertical": "Customer", "CanonicalTopic": "Saved label", "Keywords": "zorbex flindle", "Exclusions": "", "Priority": 999}
            unrelated = {**old, "CanonicalTopic": "Unrelated prior", "Keywords": "crindle morplex"}
            saved.write_text(json.dumps([old, unrelated]), encoding="utf-8")
            explicit = root / "explicit.csv"
            with explicit.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=OVERRIDE_COLUMNS)
                writer.writeheader()
                writer.writerows([{"Enabled": "true", **old, "CanonicalTopic": "Explicit replacement", "Priority": 10},
                                  {"Enabled": "true", **old, "CanonicalTopic": "Explicit additional", "Keywords": "glorbex tremple", "Priority": 120}])
            source = root / "transcripts.csv"
            with source.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=("session_id", "first_user_prompt", "locale", "primary_topic_name"))
                writer.writeheader()
                writer.writerows({"session_id": f"native-{index}", "first_user_prompt": "veltrix snorple", "locale": "en",
                                  "primary_topic_name": "New learned" if index < 5 else ""} for index in range(6))
                writer.writerows({"session_id": f"prior-{index}", "first_user_prompt": prompt, "locale": "en"}
                                 for index, prompt in enumerate(("zorbex flindle", "crindle morplex", "glorbex tremple")))
            settings = root / "settings.json"
            save_settings(settings, SetupOptions(environment_url="https://savedqa.crm.dynamics.com", topic_overrides_json=str(saved)))
            preserved = {path: path.read_bytes() for path in root.iterdir()}
            output = root / "review"
            completed = subprocess.run([sys.executable, str(repo / "tools/ess_topic_tuner.py"), "--input", str(source), "--overrides", str(explicit),
                                        "--output-dir", str(output), "--settings-file", str(settings), "--analyze-only", "--no-open"],
                                       capture_output=True, text=True)
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            expected = {"Explicit replacement", "Unrelated prior", "Explicit additional", "New learned"}
            rules = json.loads((output / "customer-topic-overrides.json").read_text(encoding="utf-8"))
            self.assertEqual({rule["CanonicalTopic"] for rule in rules}, expected)
            self.assertEqual(len(rules), 4)
            with (output / "customer-topic-overrides.csv").open(encoding="utf-8-sig", newline="") as handle:
                approved = [row for row in csv.DictReader(handle) if row["Enabled"] == "true"]
            self.assertEqual({row["CanonicalTopic"] for row in approved}, expected)
            self.assertEqual(len(approved), 4)
            with (output / "classification-audit.csv").open(encoding="utf-8-sig", newline="") as handle:
                audits = list(csv.DictReader(handle))
            self.assertEqual([row["PredictedTopic"] for row in audits[5:]], ["New learned", "Explicit replacement", "Unrelated prior", "Explicit additional"])
            for path, original in preserved.items():
                self.assertEqual(path.read_bytes(), original, str(path))

    def test_second_learning_run_preserves_first_approved_rule_in_json_settings_and_pbit(self) -> None:
        repo = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "transcripts.csv"
            output = root / "review"
            settings = root / "settings.json"
            template = root / "topics.pbit"
            save_settings(settings, SetupOptions(environment_url="https://savedqa.crm.dynamics.com"))
            command = [sys.executable, str(repo / "tools/ess_topic_tuner.py"), "--input", str(source), "--output-dir", str(output),
                       "--settings-file", str(settings), "--template-output", str(template), "--no-open", "--non-interactive"]
            previous_rules = None
            previous_bytes = None
            for run, prompt, topic in (("A", "zorbex flindle", "Equipment Enrollment"), ("B", "veltrix snorple", "Expense Verification")):
                with source.open("w", encoding="utf-8", newline="") as handle:
                    writer = csv.DictWriter(handle, fieldnames=("session_id", "first_user_prompt", "locale", "primary_topic_name"))
                    writer.writeheader()
                    writer.writerows({"session_id": f"{run}-{index}", "first_user_prompt": prompt, "locale": "en",
                                      "primary_topic_name": topic if index < 5 else ""} for index in range(6))
                completed = subprocess.run(command, capture_output=True, text=True)
                self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
                stored = load_settings(settings)
                selected = Path(stored.topic_overrides_json)
                rules = json.loads(selected.read_text(encoding="utf-8"))
                expected = {"Equipment Enrollment"} if run == "A" else {"Equipment Enrollment", "Expense Verification"}
                self.assertEqual({rule["CanonicalTopic"] for rule in rules}, expected)
                self.assertEqual(len(rules), len(expected))
                if run == "A":
                    self.assertEqual(selected.resolve(), (output / "customer-topic-overrides.json").resolve())
                    previous_rules, previous_bytes = selected, selected.read_bytes()
                else:
                    self.assertEqual(selected.parent.parent.resolve(), output.resolve())
                    self.assertTrue(selected.parent.name.startswith("run-"))
                    self.assertEqual(previous_rules.read_bytes(), previous_bytes)
                with zipfile.ZipFile(template) as package:
                    self.assertIsNone(package.testzip())
                    schema = json.loads(package.read("DataModelSchema").decode("utf-16-le"))
                embedded = next(item["expression"] for item in schema["model"]["expressions"]
                                if item["name"] == "Customer Topic Overrides JSON (optional)")
                self.assertIn(json.dumps(rules, ensure_ascii=False, separators=(",", ":")).replace('"', '""'), embedded)
                for approved_topic in expected:
                    self.assertIn(approved_topic, embedded)
                self.assertEqual(stored.environment_url, "https://savedqa.crm.dynamics.com")

    def test_repeated_run_generated_output_collisions_preserve_all_bytes(self) -> None:
        from ess_topic_tuner import main, tuner_output_paths

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "review"
            output.mkdir()
            for path in tuner_output_paths(output).values():
                path.write_bytes(f"existing {path.name} must remain unchanged".encode())
            source = root / "transcripts.csv"
            source.write_bytes(b"protected transcript sentinel")
            settings = root / "settings.json"
            save_settings(settings, SetupOptions(environment_url="https://savedqa.crm.dynamics.com"))
            template = root / "topics.pbit"
            template.write_bytes(b"previous PBIT must remain byte-identical")
            preserved = {path: path.read_bytes() for path in root.rglob("*") if path.is_file()}
            directories = {path for path in root.rglob("*") if path.is_dir()}
            for destination in tuner_output_paths(output).values():
                for alias in (destination, Path(str(destination).upper()), output / "unused" / ".." / destination.name):
                    for mode in ("analysis", "--json", "--apply", "--review"):
                        action = [mode, str(source)] if mode in {"--apply", "--review"} else ([mode] if mode == "--json" else [])
                        with self.subTest(output=destination.name, alias=str(alias), mode=mode), \
                             patch("sys.argv", ["tuner", "--input", str(source), "--output-dir", str(output), "--settings-file", str(settings),
                                                 "--template-output", str(alias), "--no-open", *action]), \
                             patch("ess_topic_tuner.tempfile.mkdtemp", side_effect=AssertionError("unexpected run directory")), \
                             patch("ess_topic_tuner.tempfile.NamedTemporaryFile", side_effect=AssertionError("unexpected rule candidate")), \
                             patch("ess_topic_tuner.write_csv", side_effect=AssertionError("unexpected diagnostic write")), \
                             patch("ess_topic_tuner.subprocess.run", side_effect=AssertionError("unexpected template build")):
                            with self.assertRaisesRegex(ValueError, "conflicts with protected input") as failure:
                                main()
                            self.assertIn(destination.name, str(failure.exception).casefold())
                        self.assertEqual({path: path.read_bytes() for path in root.rglob("*") if path.is_file()}, preserved)
                        self.assertEqual({path for path in root.rglob("*") if path.is_dir()}, directories)

    def test_selected_run_folder_generated_output_collisions_preserve_all_bytes(self) -> None:
        from ess_topic_tuner import main, tuner_output_paths

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "review"
            selected = output / "run-selected"
            selected.mkdir(parents=True)
            for folder in (output, selected):
                for path in tuner_output_paths(folder).values():
                    path.write_bytes(f"existing {folder.name}/{path.name} must remain unchanged".encode())
            source = root / "transcripts.csv"
            source.write_text("session_id,first_user_prompt,locale\nfirst,holidays,en\n", encoding="utf-8")
            settings = root / "settings.json"
            save_settings(settings, SetupOptions(environment_url="https://savedqa.crm.dynamics.com"))
            template = root / "topics.pbit"
            template.write_bytes(b"previous PBIT must remain byte-identical")
            preserved = {path: path.read_bytes() for path in root.rglob("*") if path.is_file()}
            directories = {path for path in root.rglob("*") if path.is_dir()}
            for destination in tuner_output_paths(selected).values():
                for alias in (destination, Path(str(destination).upper()), selected / "unused" / ".." / destination.name):
                    with self.subTest(output=destination.name, alias=str(alias)), \
                         patch("sys.argv", ["tuner", "--input", str(source), "--output-dir", str(output), "--settings-file", str(settings),
                                             "--template-output", str(alias), "--no-open"]), \
                         patch("ess_topic_tuner.tempfile.mkdtemp", return_value=str(selected)) as allocate, \
                         patch("ess_topic_tuner.write_csv", side_effect=AssertionError("unexpected diagnostic write")), \
                         patch("ess_topic_tuner.subprocess.run", side_effect=AssertionError("unexpected template build")), patch("builtins.print"):
                        with self.assertRaisesRegex(ValueError, "conflicts with protected input") as failure:
                            main()
                        self.assertIn(destination.name, str(failure.exception).casefold())
                        self.assertIn("run-selected", str(failure.exception).casefold())
                        allocate.assert_called_once_with(prefix="run-", dir=output)
                    self.assertEqual({path: path.read_bytes() for path in root.rglob("*") if path.is_file()}, preserved)
                    self.assertEqual({path for path in root.rglob("*") if path.is_dir()}, directories)

    def test_prepared_feedback_outputs_preserve_every_tuner_input_before_writes(self) -> None:
        from ess_topic_tuner import main
        from guided_dataverse_setup import feedback_output_paths

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            csv_output = root / "feedback-events.csv"
            for destination in feedback_output_paths(csv_output):
                for field in ("input", "taxonomy", "overrides", "apply", "review", "settings", "source", "final-output",
                              "agent_registry_json", "org_data_file", "agent_credits_file", "topic_overrides_json", "feedback_events_json", "feedback_input_files"):
                    for prepared_csv in (csv_output, Path(str(csv_output).upper()), root / "unused" / ".." / csv_output.name):
                        with self.subTest(output=destination.name, field=field, prepared=str(prepared_csv)):
                            destination.write_bytes(b"protected tuner input sentinel")
                            settings = destination if field == "settings" else root / "settings.json"
                            options = SetupOptions(environment_url="https://savedqa.crm.dynamics.com", agent_registry_json="registry.json", feedback_input_files=["raw.csv"])
                            if field in {"agent_registry_json", "org_data_file", "agent_credits_file", "topic_overrides_json", "feedback_events_json"}:
                                setattr(options, field, str(destination))
                            if field == "feedback_input_files":
                                options.feedback_input_files.append(str(destination))
                            save_settings(settings, options)
                            arguments = ["tuner", "--input", str(destination if field == "input" else root / "transcripts.csv"),
                                         "--taxonomy", str(destination if field == "taxonomy" else root / "taxonomy.csv"),
                                         "--overrides", str(destination if field == "overrides" else root / "overrides.csv"),
                                         "--settings-file", str(settings), "--output-dir", str(root / "not-created"),
                                         "--template-output", str(destination if field == "final-output" else root / "new.pbit"), "--no-open"]
                            if field in {"apply", "review"}:
                                arguments.extend((f"--{field}", str(destination)))
                            preserved = {path: path.read_bytes() for path in root.iterdir()}
                            with patch("sys.argv", arguments), patch("ess_topic_tuner.PREPARED_FEEDBACK", prepared_csv), \
                                 patch("ess_topic_tuner.SOURCE_TEMPLATE", destination if field == "source" else root / "base.pbit"), \
                                 patch("ess_topic_tuner.subprocess.run", side_effect=AssertionError("unexpected normalization or build")), \
                                 patch("ess_topic_tuner.write_csv", side_effect=AssertionError("unexpected diagnostic write")), \
                                 patch("ess_topic_tuner.tempfile.NamedTemporaryFile", side_effect=AssertionError("unexpected review candidate")):
                                with self.assertRaisesRegex(ValueError, "conflicts with protected input") as failure:
                                    main()
                                self.assertIn(destination.name.casefold(), str(failure.exception).casefold())
                            self.assertEqual({path: path.read_bytes() for path in root.iterdir()}, preserved)

    def test_tuner_pbit_output_cannot_replace_any_prepared_feedback_artifact(self) -> None:
        from ess_topic_tuner import main
        from guided_dataverse_setup import feedback_output_paths

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            csv_output = root / "feedback-events.csv"
            for destination in feedback_output_paths(csv_output):
                destination.write_bytes(b"protected prepared-feedback artifact sentinel")
            preserved = {path: path.read_bytes() for path in root.iterdir()}
            for destination in feedback_output_paths(csv_output):
                with self.subTest(output=destination.name), \
                     patch("sys.argv", ["tuner", "--input", str(root / "transcripts.csv"), "--output-dir", str(root / "not-created"),
                                         "--settings-file", str(root / "missing-settings.json"), "--template-output", str(destination)]), \
                     patch("ess_topic_tuner.PREPARED_FEEDBACK", csv_output):
                    with self.assertRaisesRegex(ValueError, "conflicts with protected input"):
                        main()
                    self.assertEqual({path: path.read_bytes() for path in root.iterdir()}, preserved)

    def test_tuner_output_collisions_preserve_inputs_before_any_writes(self) -> None:
        from ess_topic_tuner import main

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = {name: root / f"{name}.json" for name in (
                "base", "transcripts", "taxonomy", "prior-overrides", "apply", "review", "registry", "organization", "credits",
                "active-rules", "feedback", "raw-feedback", "prepared-feedback",
            )}
            for name, path in paths.items():
                path.write_bytes(f"protected {name} sentinel".encode())
            settings = root / "settings.json"
            save_settings(settings, SetupOptions(environment_url="https://savedqa.crm.dynamics.com",
                                                 agent_registry_json=str(paths["registry"]), org_data_file=str(paths["organization"]),
                                                 agent_credits_file=str(paths["credits"]), topic_overrides_json=str(paths["active-rules"]),
                                                 feedback_events_json=str(paths["feedback"]), feedback_input_files=[str(paths["raw-feedback"])]))
            preserved = {path: path.read_bytes() for path in root.iterdir()}
            common = [path for name, path in paths.items() if name not in {"apply", "review"}] + [settings]
            for mode in ("analysis", "--apply", "--review", "--json"):
                action = [mode, str(paths[mode[2:]])] if mode in {"--apply", "--review"} else ([mode] if mode == "--json" else [])
                inputs = common + ([paths[mode[2:]]] if mode in {"--apply", "--review"} else [])
                for protected in inputs:
                    for output in (protected, Path(str(protected).upper()), root / "unused" / ".." / protected.name):
                        with self.subTest(mode=mode, protected=protected.name, output=str(output)):
                            with patch("sys.argv", ["tuner", "--input", str(paths["transcripts"]), "--taxonomy", str(paths["taxonomy"]),
                                                     "--overrides", str(paths["prior-overrides"]), "--settings-file", str(settings),
                                                     "--output-dir", str(root / "not-created"), "--template-output", str(output), "--no-open", *action]), \
                                 patch("ess_topic_tuner.SOURCE_TEMPLATE", paths["base"]), \
                                 patch("ess_topic_tuner.PREPARED_FEEDBACK", paths["prepared-feedback"]), \
                                 patch("ess_topic_tuner.tempfile.NamedTemporaryFile", side_effect=AssertionError("unexpected candidate write")), \
                                 patch("ess_topic_tuner.write_csv", side_effect=AssertionError("unexpected diagnostic write")), \
                                 patch("ess_topic_tuner.subprocess.run", side_effect=AssertionError("unexpected builder")), patch("builtins.print"):
                                with self.assertRaisesRegex(ValueError, "conflicts with protected input") as failure:
                                    main()
                                self.assertIn(protected.name.casefold(), str(failure.exception).casefold())
                            self.assertEqual({path: path.read_bytes() for path in root.iterdir()}, preserved)

    def test_apply_output_cannot_overwrite_active_rules_json(self) -> None:
        repo = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            active = root / "rules.json"
            active.write_text(json.dumps([{"Locale": "en", "Vertical": "Customer", "CanonicalTopic": "Old Approved Topic",
                                          "Keywords": "zorbex flindle", "Exclusions": "", "Priority": 120}]), encoding="utf-8")
            settings = root / "settings.json"
            save_settings(settings, SetupOptions(environment_url="https://savedqa.crm.dynamics.com", topic_overrides_json=str(active)))
            template = root / "existing.pbit"
            template.write_bytes(b"protected existing template sentinel")
            preserved = {path: path.read_bytes() for path in root.iterdir()}
            for output in (active, Path(str(active).upper())):
                completed = subprocess.run([sys.executable, str(repo / "tools/ess_topic_tuner.py"), "--apply", str(active),
                                            "--settings-file", str(settings), "--template-output", str(output), "--no-open"], capture_output=True, text=True)
                self.assertEqual(completed.returncode, 2, completed.stdout + completed.stderr)
                self.assertIn("conflicts with protected input", completed.stderr)
                self.assertIn("rules.json", completed.stderr.casefold())
                self.assertEqual({path: path.read_bytes() for path in root.iterdir()}, preserved)

    def test_direct_actions_protect_sibling_tuner_artifacts_without_output_dir(self) -> None:
        from ess_topic_tuner import tuner_output_paths

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            artifacts = tuner_output_paths(root)
            for path in artifacts.values():
                path.write_bytes(f"protected {path.name} sentinel".encode())
            preserved = {path: path.read_bytes() for path in artifacts.values()}

            for action_name, action_path in (
                ("apply", artifacts["rules"]),
                ("review", artifacts["review"]),
            ):
                for destination in artifacts.values():
                    args = Namespace(
                        template_output=destination,
                        settings_file=root / "missing-settings.json",
                        input=None,
                        taxonomy=None,
                        overrides=None,
                        apply=action_path if action_name == "apply" else None,
                        review=action_path if action_name == "review" else None,
                        output_dir=None,
                    )
                    with self.subTest(action=action_name, output=destination.name):
                        with self.assertRaisesRegex(
                            ValueError,
                            "conflicts with protected input",
                        ):
                            validate_tuner_output(args)
                        self.assertEqual(
                            {path: path.read_bytes() for path in artifacts.values()},
                            preserved,
                        )

    def test_analysis_rejects_all_generated_output_collisions_before_creating_directory(self) -> None:
        from ess_topic_tuner import main

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "transcripts.csv"
            source.write_bytes(b"protected transcript sentinel")
            output = root / "not-created"
            for name in ("topic-enrichment.csv", "classification-audit.csv", "topic-learning-audit.csv",
                         "customer-topic-overrides.json", "customer-topic-overrides.csv", "privacy-report.json"):
                destination = output / name
                for alias in (destination, Path(str(destination).upper()), output / "unused" / ".." / name):
                    with self.subTest(output=name, alias=str(alias)), \
                         patch("sys.argv", ["tuner", "--input", str(source), "--output-dir", str(output),
                                             "--settings-file", str(root / "missing-settings.json"), "--template-output", str(alias)]), \
                         patch("ess_topic_tuner.write_csv", side_effect=AssertionError("unexpected diagnostic write")), \
                         patch("ess_topic_tuner.subprocess.run", side_effect=AssertionError("unexpected template build")):
                        with self.assertRaisesRegex(ValueError, "conflicts with protected input") as failure:
                            main()
                        self.assertIn(name, str(failure.exception).casefold())
                    self.assertFalse(output.exists())
                    self.assertEqual(list(root.iterdir()), [source])
                    self.assertEqual(source.read_bytes(), b"protected transcript sentinel")

    def test_failed_repeated_review_preserves_active_rules_settings_and_template(self) -> None:
        repo = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            active = root / "rules.json"
            old_rule = {"Locale": "en", "Vertical": "Customer", "CanonicalTopic": "Old Approved Topic",
                        "Keywords": "zorbex flindle", "Exclusions": "", "Priority": 120}
            active.write_text(json.dumps([old_rule]), encoding="utf-8")
            review = active.with_suffix(".csv")
            with review.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=OVERRIDE_COLUMNS)
                writer.writeheader()
                writer.writerow({"Enabled": "true", **old_rule, "CanonicalTopic": "New Reviewed Topic"})
            settings = root / "settings.json"
            save_settings(settings, SetupOptions(environment_url="https://savedqa.crm.dynamics.com",
                                                 topic_overrides_json=str(active), org_data_file=str(root / "missing-users.csv")))
            template = root / "existing.pbit"
            template.write_bytes(b"existing PBIT must remain byte-identical")
            preserved = {path: path.read_bytes() for path in (active, settings, template)}
            completed = subprocess.run([sys.executable, str(repo / "tools/ess_topic_tuner.py"),
                                        "--review", str(review), "--settings-file", str(settings),
                                        "--template-output", str(template), "--no-open"], capture_output=True, text=True)
            self.assertNotEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            self.assertIn("ERROR:", completed.stderr)
            for path, original in preserved.items():
                self.assertEqual(path.read_bytes(), original, str(path))
            self.assertEqual(Path(load_settings(settings).topic_overrides_json), active)
            self.assertEqual(list(root.glob("approved-*.json")), [])

    def test_analysis_modes_reject_actions_without_any_file_changes(self) -> None:
        repo = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            rules = root / "rules.json"
            rules.write_text(json.dumps([{"Locale": "en", "Vertical": "Customer", "CanonicalTopic": "Equipment Enrollment",
                                          "Keywords": "zorbex flindle", "Exclusions": "", "Priority": 120}]))
            review = root / "rules.csv"
            with review.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=OVERRIDE_COLUMNS)
                writer.writeheader()
                writer.writerow({"Enabled": "true", **json.loads(rules.read_text())[0]})
            settings = root / "settings.json"
            save_settings(settings, SetupOptions(environment_url="https://savedqa.crm.dynamics.com"))
            template = root / "topics.pbit"
            template.write_bytes(b"existing template must remain unchanged")
            preserved = {path: path.read_bytes() for path in root.iterdir()}
            for mode in ("--json", "--analyze-only"):
                for action, source in (("--apply", rules), ("--review", review)):
                    with self.subTest(mode=mode, action=action):
                        completed = subprocess.run([sys.executable, str(repo / "tools/ess_topic_tuner.py"),
                                                    mode, action, str(source), "--settings-file", str(settings),
                                                    "--template-output", str(template), "--no-open"],
                                                   capture_output=True, text=True, input="")
                        self.assertEqual(completed.returncode, 2, completed.stdout + completed.stderr)
                        self.assertIn("cannot be combined", completed.stderr)
                        self.assertNotIn("Traceback", completed.stderr)
                        self.assertEqual(completed.stdout, "")
                        self.assertEqual({path: path.read_bytes() for path in root.iterdir()}, preserved)

    def test_noninteractive_review_never_prompts_even_with_terminal_stdin(self) -> None:
        from ess_topic_tuner import parse_args

        with patch("sys.argv", ["tuner", "--input", "source.csv", "--output-dir", "review", "--non-interactive"]):
            args = parse_args()
        outcome = {"status": "review-required", "reviewFile": "review.csv"}
        with patch("ess_topic_tuner.sys.stdin.isatty", return_value=True), \
             patch("builtins.input", side_effect=AssertionError("unexpected review prompt")) as prompted, \
             patch("ess_topic_tuner.review_and_apply") as reviewed:
            self.assertEqual(finish_analysis(outcome, args), 0)
            prompted.assert_not_called()
            reviewed.assert_not_called()

    def test_interactive_review_eof_leaves_template_unchanged(self) -> None:
        args = Namespace(analyze_only=False, non_interactive=False)
        outcome = {"status": "review-required", "reviewFile": "review.csv"}
        with patch("ess_topic_tuner.sys.stdin.isatty", return_value=True), \
             patch("builtins.input", side_effect=EOFError), patch("builtins.print"), \
             patch("ess_topic_tuner.review_and_apply") as reviewed:
            self.assertEqual(finish_analysis(outcome, args), 0)
            reviewed.assert_not_called()

    def test_stop_and_review_reruns_preserve_applied_rules_settings_and_template(self) -> None:
        repo = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "transcripts.csv"
            output = root / "review"
            settings = root / "settings.json"
            template = root / "topics.pbit"
            save_settings(settings, SetupOptions(environment_url="https://savedqa.crm.dynamics.com"))
            command = [sys.executable, str(repo / "tools/ess_topic_tuner.py"),
                       "--input", str(source), "--output-dir", str(output),
                       "--settings-file", str(settings), "--template-output", str(template), "--no-open"]
            with source.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=("session_id", "first_user_prompt", "locale", "primary_topic_name"))
                writer.writeheader()
                for index in range(6):
                    writer.writerow({"session_id": f"native-{index}", "first_user_prompt": "zorbex flindle", "locale": "en",
                                     "primary_topic_name": "Equipment Enrollment" if index < 5 else ""})
            completed = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            rules = output / "customer-topic-overrides.json"
            self.assertEqual(len(json.loads(rules.read_text())), 1)
            self.assertEqual(Path(load_settings(settings).topic_overrides_json).resolve(), rules.resolve())
            preserved = {path: path.read_bytes() for path in (rules, output / "customer-topic-overrides.csv", settings, template)}
            for prompt, count, expected in (("holidays", 1, "STOP"), ("veltrix snorple", 5, "REVIEW REQUIRED")):
                with self.subTest(outcome=expected):
                    with source.open("w", encoding="utf-8", newline="") as handle:
                        writer = csv.DictWriter(handle, fieldnames=("session_id", "first_user_prompt", "locale"))
                        writer.writeheader()
                        writer.writerows({"session_id": f"unlabeled-{index}", "first_user_prompt": prompt, "locale": "en"}
                                         for index in range(count))
                    completed = subprocess.run(command, capture_output=True, text=True, input="")
                    self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
                    self.assertIn(expected, completed.stdout)
                    for path, original in preserved.items():
                        self.assertEqual(path.read_bytes(), original, str(path))
            reports = [json.loads(path.read_text()) for path in output.glob("run-*/privacy-report.json")]
            self.assertEqual({report["outcome"]["status"] for report in reports}, {"stop", "review-required"})

    def test_review_can_finish_in_the_same_session_or_be_skipped(self) -> None:
        args = Namespace(analyze_only=False, non_interactive=False)
        outcome = {"status": "review-required", "reviewFile": "review.csv"}
        with patch("ess_topic_tuner.sys.stdin.isatty", return_value=True), \
             patch("builtins.input", return_value=""), patch("builtins.print"), \
             patch("ess_topic_tuner.review_and_apply", return_value=0) as reviewed:
            self.assertEqual(finish_analysis(outcome, args), 0)
            reviewed.assert_called_once_with(Path("review.csv"), args)
        with patch("ess_topic_tuner.sys.stdin.isatty", return_value=True), \
             patch("builtins.input", return_value="skip"), patch("builtins.print"), \
             patch("ess_topic_tuner.review_and_apply") as reviewed:
            self.assertEqual(finish_analysis(outcome, args), 0)
            reviewed.assert_not_called()

    def test_machine_readable_summary_never_applies_or_prompts(self) -> None:
        from ess_topic_tuner import parse_args

        with patch("sys.argv", ["tuner", "--input", "source.csv", "--output-dir", "review", "--json"]):
            args = parse_args()
        self.assertTrue(args.analyze_only)
        with patch("ess_topic_tuner.apply_dataverse_rules") as applied:
            self.assertEqual(finish_analysis({"status": "ready"}, args), 0)
            applied.assert_not_called()

    def test_singular_plural_support_is_combined_and_variants_are_exported(self) -> None:
        repo = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "variants.csv"
            with source.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=("session_id", "first_user_prompt", "locale", "primary_topic_name"))
                writer.writeheader()
                for index in range(7):
                    writer.writerow({"session_id": f"variant-{index}", "locale": "en-US",
                                     "first_user_prompt": "zorbex ticket" if index % 2 else "zorbex tickets",
                                     "primary_topic_name": "Equipment Enrollment" if index < 5 else ""})
            output = root / "review"
            self.run_tuner(repo / "tools/ess_topic_tuner.py", repo / "taxonomy/topics-taxonomy.csv", source, output, min_frequency=5)
            rules = json.loads((output / "customer-topic-overrides.json").read_text())
            self.assertEqual(len(rules), 1)
            self.assertIn("zorbex ticket", rules[0]["Keywords"].split("|"))
            self.assertIn("zorbex tickets", rules[0]["Keywords"].split("|"))
            with (output / "classification-audit.csv").open(encoding="utf-8-sig") as handle:
                audits = list(csv.DictReader(handle))
            self.assertTrue(all(row["Source"] == "native" for row in audits[:5]))
            self.assertTrue(all(row["PredictedTopic"] == "Equipment Enrollment" and row["RuleSource"] == "Customer" for row in audits[5:]))

    def test_variants_preserve_boundaries_exclusions_and_other_languages(self) -> None:
        rules = rules_from_override_rows([{
            "Enabled": "true", "Locale": "en", "Vertical": "Customer", "CanonicalTopic": "Equipment Enrollment",
            "Keywords": "zorbex ticket", "Exclusions": "lost device", "Priority": 120,
        }])
        self.assertEqual(classify("zorbex tickets", "en-US", rules)["topic"], "Equipment Enrollment")
        self.assertEqual(classify("zorbex tickets lost devices", "en-US", rules)["source"], "uncategorized")
        self.assertEqual(classify("zorbex ticketing", "en-US", rules)["source"], "uncategorized")
        self.assertEqual(expand_customer_terms("bus|business|news|analysis", "en"), "bus|business|news|analysis")
        self.assertEqual(expand_customer_terms("tickets", "es"), "tickets")
        self.assertEqual(set(expand_customer_terms("policy", "en").split("|")), {"policy", "policies"})
        with self.assertRaisesRegex(ValueError, "shorter"):
            expand_customer_terms("ticket device policy account printer laptop benefit", "en")

    def test_variants_with_conflicting_native_labels_are_not_auto_approved(self) -> None:
        repo = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "conflicts.csv"
            with source.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=("session_id", "first_user_prompt", "locale", "primary_topic_name"))
                writer.writeheader()
                for index in range(5):
                    for term, topic in (("ticket", "Topic A"), ("tickets", "Topic B")):
                        writer.writerow({"session_id": f"{topic}-{index}", "first_user_prompt": f"zorbex {term}",
                                         "locale": "en", "primary_topic_name": topic})
            output = root / "review"
            result = self.run_tuner(repo / "tools/ess_topic_tuner.py", repo / "taxonomy/topics-taxonomy.csv", source, output, min_frequency=5)
            self.assertEqual(json.loads((output / "customer-topic-overrides.json").read_text()), [])
            self.assertIn("REVIEW REQUIRED", result.stdout)

    def test_raw_native_evidence_improves_previously_unclassified_conversations(self) -> None:
        repo = Path(__file__).resolve().parents[1]
        taxonomy = repo / "taxonomy/topics-taxonomy.csv"
        self.assertEqual(classify("zorbex flindle", "en-US", load_rules(taxonomy))["source"], "uncategorized")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "ConversationTranscripts.csv"
            with source.open("w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=("conversationtranscriptid", "content"))
                writer.writeheader()
                for index in range(7):
                    activities = [{"type": "message", "from": {"role": "user"}, "locale": "en-US",
                                   "text": "zorbex flindle" if index < 6 else "veltrix snorple"}]
                    if index < 5:
                        activities.append({"name": "IntentRecognition", "value": {"intentTitle": "Equipment Enrollment"}})
                        activities.extend([
                            {"type": "message", "from": {"role": "user"}, "locale": "en-US",
                             "text": "zorbex ticket" if index % 2 else "zorbex tickets"},
                            {"name": "IntentRecognition", "value": {"intentTitle": "Equipment Enrollment"}},
                        ])
                    writer.writerow({"conversationtranscriptid": f"synthetic-{index}",
                                     "content": json.dumps({"activities": activities})})
            output = root / "review"
            settings = root / "settings.json"
            save_settings(settings, SetupOptions(environment_url="https://customerqa.crm.dynamics.com"))
            template = root / "topics.pbit"
            command = [
                sys.executable, str(repo / "tools/guided_dataverse_setup.py"), "--tune-topics",
                "--topic-transcripts", str(source), "--settings-file", str(settings),
                "--output", str(template), "--no-open", "--non-interactive",
            ]
            if sys.platform == "win32":
                command = [os.environ.get("COMSPEC", "cmd.exe"), "/d", "/c", str(repo / "TUNE-TOPICS.cmd"), *command[3:]]
            result = subprocess.run(command, capture_output=True, text=True,
                                    env={**os.environ, "ESS_SETUP_NO_PAUSE": "1"})
            output = root / "Topic Review"
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertTrue(result.stdout.startswith("This local tool learns terminology"))
            self.assertIn("Building a new Desktop Validation PBIT automatically", result.stdout)
            self.assertNotIn("--apply", result.stdout)
            with (output / "classification-audit.csv").open(encoding="utf-8-sig") as handle:
                audits = list(csv.DictReader(handle))
            self.assertTrue(all(row["Source"] == "native" and row["PredictedTopic"] == "Equipment Enrollment" for row in audits[:5]))
            self.assertEqual(audits[5]["PredictedTopic"], "Equipment Enrollment")
            self.assertEqual(audits[5]["RuleSource"], "Customer")
            self.assertEqual(audits[6]["Source"], "uncategorized")
            report = json.loads((output / "privacy-report.json").read_text())
            self.assertEqual(report["outcome"]["status"], "ready")
            self.assertEqual(report["outcome"]["approvedRules"], 1)
            self.assertNotIn("action", report["outcome"])
            with zipfile.ZipFile(template) as package:
                self.assertIsNone(package.testzip())
                schema = json.loads(package.read("DataModelSchema").decode("utf-16-le"))
            embedded = next(item["expression"] for item in schema["model"]["expressions"]
                            if item["name"] == "Customer Topic Overrides JSON (optional)")
            self.assertIn("Equipment Enrollment", embedded)
            self.assertIn("zorbex ticket", embedded)
            self.assertIn("zorbex tickets", embedded)

    def test_full_synthetic_corpus_applies_default_validation_gates(self) -> None:
        repo = Path(__file__).resolve().parents[1]
        tuner = repo / "tools" / "ess_topic_tuner.py"
        taxonomy = repo / "taxonomy" / "topics-taxonomy.csv"
        source = repo / "SampleData" / "ConversationTranscripts.csv"

        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "output"
            self.run_tuner(
                tuner,
                taxonomy,
                source,
                output,
                min_frequency=5,
            )
            with (output / "topic-learning-audit.csv").open(
                "r",
                encoding="utf-8-sig",
                newline="",
            ) as handle:
                learning = list(csv.DictReader(handle))

        self.assertEqual(len(learning), 10)
        self.assertEqual(
            {
                row["NativeTopic"]: row["Status"]
                for row in learning
                if row["Status"] != "AutoValidated"
            },
            {"Learning & Development": "NeedsReview"},
        )
        self.assertTrue(
            all(
                row["ValidationStatus"] == "Passed"
                for row in learning
                if row["Status"] == "AutoValidated"
            )
        )
        self.assertTrue(
            all(row["ValidationPrecision"] == "1.0000" for row in learning)
        )
        self.assertTrue(
            all(
                row["ValidationFalsePositiveConversations"] == "0"
                for row in learning
            )
        )

    def test_native_rules_require_out_of_fold_validation(self) -> None:
        repo = Path(__file__).resolve().parents[1]
        tuner = repo / "tools" / "ess_topic_tuner.py"
        taxonomy = repo / "taxonomy" / "topics-taxonomy.csv"

        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            source = temp / "resolved-and-unresolved.csv"
            output = temp / "output"
            fieldnames = (
                "session_id",
                "first_user_prompt",
                "locale",
                "primary_topic_name",
            )
            with source.open(
                "w",
                encoding="utf-8-sig",
                newline="",
            ) as handle:
                writer = csv.DictWriter(handle, fieldnames=fieldnames)
                writer.writeheader()
                for index in range(12):
                    writer.writerow(
                        {
                            "session_id": f"payroll-{index}",
                            "first_user_prompt": (
                                "Acme payroll portal access issue for employee"
                            ),
                            "locale": "en-US",
                            "primary_topic_name": "Payroll Access",
                        }
                    )
                    writer.writerow(
                        {
                            "session_id": f"travel-{index}",
                            "first_user_prompt": (
                                "Nimbus travel booking policy question for employee"
                            ),
                            "locale": "en-US",
                            "primary_topic_name": "Travel Booking",
                        }
                    )
                writer.writerow(
                    {
                        "session_id": "unresolved-payroll",
                        "first_user_prompt": "Acme payroll portal access issue",
                        "locale": "en-US",
                        "primary_topic_name": "",
                    }
                )
                writer.writerow(
                    {
                        "session_id": "unresolved-travel",
                        "first_user_prompt": "Nimbus travel booking policy question",
                        "locale": "en-US",
                        "primary_topic_name": "",
                    }
                )

            self.run_tuner(tuner, taxonomy, source, output)

            with (output / "topic-learning-audit.csv").open(
                "r",
                encoding="utf-8-sig",
                newline="",
            ) as handle:
                learning = list(csv.DictReader(handle))
            self.assertEqual(
                {row["Status"] for row in learning},
                {"AutoValidated"},
            )
            self.assertTrue(
                all(row["ValidationStatus"] == "Passed" for row in learning)
            )
            self.assertTrue(
                all(row["ValidationPrecision"] == "1.0000" for row in learning)
            )
            self.assertTrue(
                all(
                    row["ValidationMethod"]
                    == "Deterministic conversation-level 5-fold"
                    for row in learning
                )
            )

            with (output / "classification-audit.csv").open(
                "r",
                encoding="utf-8-sig",
                newline="",
            ) as handle:
                classifications = list(csv.DictReader(handle))
            self.assertTrue(
                all(row["Source"] == "native" for row in classifications[:-2])
            )
            self.assertEqual(
                [
                    (row["PredictedTopic"], row["RuleSource"])
                    for row in classifications[-2:]
                ],
                [
                    ("Payroll Access", "Customer"),
                    ("Travel Booking", "Customer"),
                ],
            )

            report = json.loads(
                (output / "privacy-report.json").read_text(encoding="utf-8")
            )
            self.assertEqual(
                report["nativeTopicValidationMethod"],
                "Deterministic conversation-level 5-fold",
            )
            self.assertEqual(report["minimumValidationConversations"], 3)
            self.assertEqual(report["enabledCustomerRulesWritten"], 2)
            self.assertIn("--apply", self.run_tuner(tuner, taxonomy, source, output).stdout)

    def test_minimum_supported_rule_is_balanced_across_validation_folds(self) -> None:
        repo = Path(__file__).resolve().parents[1]
        tuner = repo / "tools" / "ess_topic_tuner.py"
        taxonomy = repo / "taxonomy" / "topics-taxonomy.csv"

        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            source = temp / "minimum-support.csv"
            output = temp / "output"
            with source.open(
                "w",
                encoding="utf-8-sig",
                newline="",
            ) as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=(
                        "session_id",
                        "first_user_prompt",
                        "locale",
                        "primary_topic_name",
                    ),
                )
                writer.writeheader()
                for index in range(5):
                    writer.writerow(
                        {
                            "session_id": f"minimum-{index}",
                            "first_user_prompt": "Acme payroll portal access issue",
                            "locale": "en-US",
                            "primary_topic_name": "Payroll Access",
                        }
                    )

            self.run_tuner(
                tuner,
                taxonomy,
                source,
                output,
                min_frequency=5,
            )
            with (output / "topic-learning-audit.csv").open(
                "r",
                encoding="utf-8-sig",
                newline="",
            ) as handle:
                learning = list(csv.DictReader(handle))

        self.assertEqual(len(learning), 1)
        self.assertEqual(learning[0]["Status"], "AutoValidated")
        self.assertEqual(learning[0]["ValidationMatchedConversations"], "5")
        self.assertEqual(learning[0]["ValidationPrecision"], "1.0000")

    def test_cross_topic_ambiguity_is_not_auto_enabled(self) -> None:
        repo = Path(__file__).resolve().parents[1]
        tuner = repo / "tools" / "ess_topic_tuner.py"
        taxonomy = repo / "taxonomy" / "topics-taxonomy.csv"

        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            source = temp / "ambiguous.csv"
            output = temp / "output"
            with source.open(
                "w",
                encoding="utf-8-sig",
                newline="",
            ) as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=(
                        "session_id",
                        "first_user_prompt",
                        "locale",
                        "primary_topic_name",
                    ),
                )
                writer.writeheader()
                for index in range(10):
                    for topic in ("Topic A", "Topic B"):
                        writer.writerow(
                            {
                                "session_id": f"{topic}-{index}",
                                "first_user_prompt": "shared policy lookup request",
                                "locale": "en-US",
                                "primary_topic_name": topic,
                            }
                        )

            self.run_tuner(tuner, taxonomy, source, output)
            rules = json.loads(
                (output / "customer-topic-overrides.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(rules, [])
            with (output / "topic-learning-audit.csv").open(
                "r",
                encoding="utf-8-sig",
                newline="",
            ) as handle:
                learning = list(csv.DictReader(handle))
            self.assertTrue(
                all(row["AutoEnabled"] == "false" for row in learning)
            )
            result = self.run_tuner(tuner, taxonomy, source, output)
            self.assertIn("REVIEW REQUIRED: No rules are ready yet", result.stdout)
            self.assertNotIn("--apply", result.stdout)

    def test_private_candidate_and_approved_override_round_trip(self) -> None:
        repo = Path(__file__).resolve().parents[1]
        tuner = repo / "tools" / "ess_topic_tuner.py"
        taxonomy = repo / "taxonomy" / "topics-taxonomy.csv"

        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            source = temp / "sessions.csv"
            first_output = temp / "first"
            second_output = temp / "second"
            with source.open("w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=("session_id", "first_user_prompt", "locale"))
                writer.writeheader()
                for index in range(6):
                    writer.writerow(
                        {
                            "session_id": f"session-{index}",
                            "first_user_prompt": (
                                f"How can I request a fleet card for alex{index}@contoso.com "
                                f"or call +1 (555) 000-10{index:02d}?"
                            ),
                            "locale": "en-US",
                        }
                    )

            result = self.run_tuner(tuner, taxonomy, source, first_output)
            self.assertIn("REVIEW REQUIRED: No rules are ready yet", result.stdout)
            self.assertIn("No usable native topic evidence", result.stdout)
            self.assertIn("--review", result.stdout)
            self.assertNotIn("--apply", result.stdout)
            audit_text = (first_output / "classification-audit.csv").read_text(encoding="utf-8-sig")
            enrichment_text = (first_output / "topic-enrichment.csv").read_text(encoding="utf-8-sig")
            overrides_text = (first_output / "customer-topic-overrides.csv").read_text(encoding="utf-8-sig")
            self.assertNotIn("alex0@contoso.com", audit_text + enrichment_text + overrides_text)
            self.assertNotIn("How can I request", audit_text + enrichment_text)

            with (first_output / "customer-topic-overrides.csv").open(
                "r", encoding="utf-8-sig", newline=""
            ) as handle:
                rows = list(csv.DictReader(handle))
            candidate = next(row for row in rows if "fleet card" in row["Keywords"])
            candidate.update(
                {
                    "Enabled": "true",
                    "Vertical": "Finance",
                    "CanonicalTopic": "Fleet Cards",
                    "ReviewStatus": "Approved",
                }
            )
            with (first_output / "customer-topic-overrides.csv").open(
                "w", encoding="utf-8-sig", newline=""
            ) as handle:
                writer = csv.DictWriter(handle, fieldnames=rows[0].keys())
                writer.writeheader()
                writer.writerows(rows)

            self.run_tuner(
                tuner,
                taxonomy,
                source,
                second_output,
                first_output / "customer-topic-overrides.csv",
            )
            approved = json.loads((second_output / "customer-topic-overrides.json").read_text(encoding="utf-8"))
            self.assertEqual("Fleet Cards", approved[0]["CanonicalTopic"])
            with (second_output / "classification-audit.csv").open(
                "r", encoding="utf-8-sig", newline=""
            ) as handle:
                audits = list(csv.DictReader(handle))
            self.assertTrue(all(row["PredictedTopic"] == "Fleet Cards" for row in audits))
            self.assertTrue(all(row["RuleSource"] == "Customer" for row in audits))

            report = json.loads((first_output / "privacy-report.json").read_text(encoding="utf-8"))
            self.assertEqual(6, report["piiPatternsRedactedBeforeCandidateExtraction"]["email"])
            self.assertEqual(6, report["piiPatternsRedactedBeforeCandidateExtraction"]["phone"])
            self.assertFalse(report["rawTranscriptTextWritten"])

    def test_already_classified_conversation_stops_without_apply_action(self) -> None:
        repo = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "sessions.csv"
            with source.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=("session_id", "first_user_prompt", "locale"))
                writer.writeheader()
                writer.writerow({"session_id": "recognized", "first_user_prompt": "holidays", "locale": "en-US"})
            output = Path(directory) / "output"
            result = self.run_tuner(repo / "tools/ess_topic_tuner.py", repo / "taxonomy/topics-taxonomy.csv", source, output)
            self.assertIn("STOP: No useful customer rules", result.stdout)
            self.assertIn("No unclassified rows", result.stdout)
            self.assertNotIn("--apply", result.stdout)
            self.assertNotIn("--review", result.stdout)
            self.assertEqual(json.loads((output / "customer-topic-overrides.json").read_text()), [])
            with (output / "classification-audit.csv").open(encoding="utf-8-sig") as handle:
                audit = next(csv.DictReader(handle))
            self.assertEqual(audit["PredictedTopic"], "Time Off & Attendance")
            self.assertEqual(audit["MatchedTerms"], "holidays")

    def test_empty_json_cannot_be_applied(self) -> None:
        repo = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            rules = Path(directory) / "empty.json"
            rules.write_text("[]", encoding="utf-8")
            result = subprocess.run([sys.executable, str(repo / "tools/ess_topic_tuner.py"), "--apply", str(rules), "--no-open"], capture_output=True, text=True)
            self.assertEqual(result.returncode, 2)
            self.assertIn("Keep the existing template unchanged", result.stderr)

    def test_reviewed_rules_preserve_saved_inputs_and_embed_without_json_dependency(self) -> None:
        repo = Path(__file__).resolve().parents[1]
        samples = repo / "SampleData"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            settings = root / "saved-setup.json"
            output = root / "Desktop Validation - Topics.pbit"
            reviewed = root / "customer-topic-overrides.csv"
            previous_rules = reviewed.with_suffix(".json")
            previous_rules.write_text(json.dumps([{"Locale": "en", "Vertical": "Customer", "CanonicalTopic": "Old Approved Topic",
                                                 "Keywords": "old approved wording", "Exclusions": "", "Priority": 120}]), encoding="utf-8")
            previous_bytes = previous_rules.read_bytes()
            options = SetupOptions(
                environment_url="https://customerqa.crm4.dynamics.com",
                agent_registry_json=str(samples / "agent-registry.json"),
                org_data_file=str(samples / "OrgData.csv"),
                agent_credits_file=str(samples / "EntitlementConsumptionTenantPerUserDetailsReport_MCSMessages_30_SYNTHETIC.csv"),
                feedback_events_json=str(samples / "feedback-events.json"),
                topic_overrides_json=str(previous_rules.resolve()),
            )
            save_settings(settings, options)
            with reviewed.open("w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=OVERRIDE_COLUMNS)
                writer.writeheader()
                writer.writerow({"Enabled": "true", "Locale": "en", "Vertical": "Finance",
                                 "CanonicalTopic": "Fleet Cards", "Keywords": "fleet card",
                                 "Exclusions": "lost", "Priority": "120"})
                writer.writerow({"Enabled": "false", "Locale": "en", "Keywords": "ambiguous phrase"})
            completed = subprocess.run([
                sys.executable, str(repo / "tools/ess_topic_tuner.py"), "--review", str(reviewed),
                "--settings-file", str(settings), "--template-output", str(output), "--no-open",
            ], capture_output=True, text=True)
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            self.assertIn("Approved topic rules: 1 rows", completed.stdout)
            saved = load_settings(settings)
            rules_file = Path(saved.topic_overrides_json)
            self.assertNotEqual(rules_file.resolve(), previous_rules.resolve())
            self.assertEqual(rules_file.parent.resolve(), reviewed.parent.resolve())
            self.assertTrue(rules_file.name.startswith("approved-"))
            self.assertEqual(previous_rules.read_bytes(), previous_bytes)
            saved.topic_overrides_json = options.topic_overrides_json
            self.assertEqual(saved, options)
            final_rules = json.loads(rules_file.read_text(encoding="utf-8"))
            self.assertEqual(len(final_rules), 1)
            self.assertEqual(final_rules[0]["CanonicalTopic"], "Fleet Cards")
            rules_file.unlink()
            reviewed.unlink()
            with zipfile.ZipFile(output) as package:
                self.assertIsNone(package.testzip())
                schema = json.loads(package.read("DataModelSchema").decode("utf-16-le"))
            parameters = {item["name"]: item for item in schema["model"]["expressions"]}
            embedded = parameters["Customer Topic Overrides JSON (optional)"]["expression"]
            self.assertIn('""CanonicalTopic"":""Fleet Cards""', embedded)
            self.assertIn('""Exclusions"":""lost""', embedded)
            self.assertNotIn("ambiguous phrase", embedded)
            self.assertNotIn("Old Approved Topic", embedded)
            self.assertNotIn(str(rules_file.resolve()), json.dumps(schema))
            for connector in ("File.Contents", "Folder.Files", "Web.Contents"):
                self.assertNotIn(connector, embedded)
            self.assertIn(options.environment_url, parameters["Dataverse Environment URL (required)"]["expression"])
            self.assertIn(options.org_data_file, parameters["Org Data File"]["expression"])
            self.assertIn(options.agent_credits_file, parameters["Agent Credits  (optional)"]["expression"])

    def test_apply_requests_noninteractive_open_and_requires_saved_setup(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            rules = root / "rules.json"
            rules.write_text(json.dumps([{"Locale": "en", "Vertical": "Customer", "CanonicalTopic": "Fleet Cards",
                                         "Keywords": "fleet card", "Exclusions": "", "Priority": 120}]), encoding="utf-8")
            args = Namespace(settings_file=root / "settings.json", template_output=root / "new.pbit", no_open=False)
            with patch("ess_topic_tuner.subprocess.run") as runner:
                with self.assertRaisesRegex(ValueError, "No saved Dataverse setup"):
                    apply_dataverse_rules(rules, args)
                runner.assert_not_called()
                save_settings(args.settings_file, SetupOptions(environment_url="https://savedqa.crm.dynamics.com"))
                runner.return_value.returncode = 0
                self.assertEqual(apply_dataverse_rules(rules, args), 0)
                command = runner.call_args.args[0]
                self.assertIn("--open", command)
                self.assertIn("--non-interactive", command)
                self.assertIn("--topic-overrides-json", command)
                self.assertNotIn("--environment-url", command)
                self.assertEqual(command[command.index("--output") + 1], str(args.template_output.resolve()))

    def test_disabled_review_is_stop_and_invalid_enabled_review_does_not_apply(self) -> None:
        repo = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            reviewed = Path(directory) / "review.csv"
            for enabled, expected_code in (("false", 0), ("true", 2)):
                with self.subTest(enabled=enabled):
                    with reviewed.open("w", encoding="utf-8", newline="") as handle:
                        writer = csv.DictWriter(handle, fieldnames=OVERRIDE_COLUMNS)
                        writer.writeheader()
                        writer.writerow({"Enabled": enabled, "Keywords": "fleet card", "Priority": 120})
                    completed = subprocess.run([sys.executable, str(repo / "tools/ess_topic_tuner.py"),
                                                "--review", str(reviewed), "--no-open"], capture_output=True, text=True)
                    self.assertEqual(completed.returncode, expected_code)
                    self.assertFalse(reviewed.with_suffix(".json").exists())
                    if not expected_code:
                        self.assertIn("STOP: No approved rules", completed.stdout)
                    else:
                        self.assertIn("must specify Vertical", completed.stderr)

    def test_sparse_unlabeled_evidence_stops_and_explains_why(self) -> None:
        repo = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "one.csv"
            with source.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=("session_id", "first_user_prompt", "locale"))
                writer.writeheader()
                writer.writerow({"session_id": "unique", "first_user_prompt": "zorbex flindle", "locale": "en"})
            self.run_tuner(repo / "tools/ess_topic_tuner.py", repo / "taxonomy/topics-taxonomy.csv", source, root / "output")
            report = json.loads((root / "output/privacy-report.json").read_text())
            self.assertEqual(report["outcome"]["status"], "stop")
            self.assertNotIn("action", report["outcome"])
            self.assertIn("No usable native topic evidence and insufficient repeated", report["outcome"]["message"])

    def test_action_command_quotes_paths_and_preserves_custom_settings(self) -> None:
        args = Namespace(settings_file=Path("customer's settings.json"), template_output=None, no_open=False)
        command = next_command(args, "--apply", Path("customer's rules.json"))
        self.assertTrue(command.startswith("& '"))
        self.assertIn("customer''s rules.json", command)
        self.assertIn("customer''s settings.json", command)

    def test_failed_apply_keeps_saved_choices_and_existing_template(self) -> None:
        repo = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            settings = root / "settings.json"
            save_settings(settings, SetupOptions(environment_url="https://savedqa.crm.dynamics.com",
                                                org_data_file=str(root / "missing-users.csv"),
                                                topic_overrides_json="previous-rules.json"))
            previous = settings.read_bytes()
            rules = root / "rules.json"
            rules.write_text(json.dumps([{"Locale": "en", "Vertical": "Customer", "CanonicalTopic": "Equipment Enrollment",
                                         "Keywords": "zorbex flindle", "Exclusions": "", "Priority": 120}]), encoding="utf-8")
            output = root / "existing.pbit"
            output.write_bytes(b"previous template")
            completed = subprocess.run([
                sys.executable, str(repo / "tools/ess_topic_tuner.py"), "--apply", str(rules),
                "--settings-file", str(settings), "--template-output", str(output), "--no-open",
            ], capture_output=True, text=True)
            self.assertNotEqual(completed.returncode, 0)
            self.assertEqual(settings.read_bytes(), previous)
            self.assertEqual(output.read_bytes(), b"previous template")

    def run_tuner(
        self,
        tuner: Path,
        taxonomy: Path,
        source: Path,
        output: Path,
        overrides: Path | None = None,
        min_frequency: int = 3,
    ) -> subprocess.CompletedProcess:
        command = [
            sys.executable,
            str(tuner),
            "--input",
            str(source),
            "--taxonomy",
            str(taxonomy),
            "--output-dir",
            str(output),
            "--min-frequency",
            str(min_frequency),
            "--analyze-only",
        ]
        if overrides:
            command.extend(("--overrides", str(overrides)))
        return subprocess.run(command, check=True, capture_output=True, text=True)


if __name__ == "__main__":
    unittest.main()
