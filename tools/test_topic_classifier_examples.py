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

    def test_generic_hr_service_prompts(self):
        cases = (
            ("How do I file a workplace complaint?", "Employee Relations & Workplace Conduct"),
            ("I need to request an employee transfer.", "Job & Organization Changes"),
            ("Where do I update my performance goals?", "Performance & Talent Management"),
            ("What relocation assistance is available?", "Mobility & Relocation"),
            ("We received an external HR audit request.", "HR Audit & Compliance"),
            ("I cannot access the HR portal.", "HR Systems & Self-Service"),
            ("How can I request an employment reference?", "Employee Records & Documents"),
            ("Where can I find the employee engagement survey?", "Culture, Engagement & Inclusion"),
            ("How do I onboard a contingent worker?", "Contingent Workforce"),
            ("I need a headcount report.", "HR Reporting & Analytics"),
            ("How do I change an employee's legal name?", "Personal Information & Profile"),
            ("Where can I enroll in a required learning course?", "Learning & Development"),
            ("How do I create a job requisition?", "Recruiting & Referrals"),
        )
        for prompt, topic in cases:
            with self.subTest(prompt=prompt):
                result = classify(prompt, "en-US", self.rules)
                self.assertEqual(result["topic"], topic)
                self.assertEqual(result["vertical"], "HR")

    def test_generic_hr_rules_do_not_steal_existing_topics(self):
        cases = (
            ("Please transfer me to a human agent.", "Agent Handoff & Escalation"),
            ("The software has a performance issue.", "Software & Downloads"),
            ("I need application access.", "Access & Permissions"),
            ("I need a tax form for a vendor.", "Accounting & Tax"),
        )
        for prompt, topic in cases:
            with self.subTest(prompt=prompt):
                result = classify(prompt, "en-US", self.rules)
                self.assertEqual(result["topic"], topic)


if __name__ == "__main__":
    unittest.main()
