import unittest
from pathlib import Path

from topic_classifier import classify, load_rules


ROOT = Path(__file__).resolve().parents[1]


class TopicClassifierExampleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rules = load_rules(ROOT / "taxonomy" / "topics-taxonomy.csv")

    def test_ess_sample_prompts(self):
        cases = (
            (
                "What holidays does the company observe?",
                "Time Off & Attendance",
                "HR",
            ),
            (
                "How do I update my home address?",
                "Personal Information & Profile",
                "HR",
            ),
            (
                "How can I request time off?",
                "Time Off & Attendance",
                "HR",
            ),
        )
        for prompt, topic, vertical in cases:
            with self.subTest(prompt=prompt):
                result = classify(prompt, "en-US", self.rules)
                self.assertEqual(result["topic"], topic)
                self.assertEqual(result["vertical"], vertical)

    def test_office_address_remains_facilities(self):
        result = classify(
            "What is the office address?",
            "en-US",
            self.rules,
        )
        self.assertEqual(result["topic"], "Office Info & Locations")
        self.assertEqual(result["vertical"], "Facilities")


if __name__ == "__main__":
    unittest.main()
