import csv
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class TopicTunerTests(unittest.TestCase):
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
            "3",
        ]
        if overrides:
            command.extend(("--overrides", str(overrides)))
        subprocess.run(command, check=True, capture_output=True, text=True)


if __name__ == "__main__":
    unittest.main()
