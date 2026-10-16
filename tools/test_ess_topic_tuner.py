import csv
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class TopicTunerTests(unittest.TestCase):
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

            self.run_tuner(tuner, taxonomy, source, first_output)
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

    def run_tuner(
        self,
        tuner: Path,
        taxonomy: Path,
        source: Path,
        output: Path,
        overrides: Path | None = None,
        min_frequency: int = 3,
    ) -> None:
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
        ]
        if overrides:
            command.extend(("--overrides", str(overrides)))
        subprocess.run(command, check=True, capture_output=True, text=True)


if __name__ == "__main__":
    unittest.main()
