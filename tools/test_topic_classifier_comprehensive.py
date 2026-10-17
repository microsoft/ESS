import csv
import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path

from build_service_refresh_template import build_package
from topic_classifier import SEPARATOR_CHARACTERS, SEPARATOR_UNICODE_VERSION, classify, load_rules, normalize
from update_fabric_topic_classifier import build_stage_one, read_taxonomy
from update_topic_classifier import (
    build_classifier,
    build_customer_topic_rules,
    build_derived_block,
    build_normalization,
    build_topic_rules,
    load_taxonomy,
    m_string,
)


ROOT = Path(__file__).resolve().parents[1]
TAXONOMY = ROOT / "taxonomy" / "topics-taxonomy.csv"
SOURCE = ROOT / "ESS Dashboard - Dynamic Topics (Dataverse) V21.pbit"
LOCALES = {"*": "en-US", "es": "es-MX", "zh": "zh-CN"}


def expression_text(value):
    return "\n".join(value) if isinstance(value, list) else value


def source_model():
    with zipfile.ZipFile(SOURCE) as package:
        return json.loads(
            package.read("DataModelSchema").decode("utf-16-le")
        )["model"]


class TopicClassifierComprehensiveTests(unittest.TestCase):
    def test_power_query_runtime_matches_python_canonicalization(self):
        executable = os.environ.get("ESS_PQTEST") or shutil.which("PQTest.exe") or shutil.which("PQTest")
        if not executable:
            self.skipTest("Standalone Power Query runtime unavailable; set ESS_PQTEST to PQTest.exe.")
        rules = [{"Locale": "en-US", "Vertical": "Customer", "CanonicalTopic": "Enrollment", "Priority": 120, "RuleSource": "Customer",
                  "Keywords": "Device\u2011Enrollment|device enrollment|devices enrollment", "Exclusions": "lost\u2019device"}]
        cases = []
        for separator in ("-", "\u2010", "\u2011", "\u2013", "\u2014", "\u2019", "\u201d", "\u3001", "\uff0c",
                          "\u060c", "\U00010100", "\U00010d6e", "\U0001e5ff"):
            for prompt in (f"device{separator}enrollment", f"devices{separator}enrollment", f"device{separator}enrollment lost{separator}device"):
                result = classify(prompt, "en-GB", rules)
                cases.append({"prompt": prompt, "locale": "en-GB", "expected": {"Topic": result["topic"], "Score": result["score"],
                              "Language": result["language"], "Ambiguous": result["ambiguous"], "Confidence": result["confidence"]}})
        payload = json.dumps([{column: rule[column] for column in ("Locale", "Vertical", "CanonicalTopic", "Keywords", "Exclusions", "Priority")}
                              for rule in rules])
        invalid = json.dumps([{**json.loads(payload)[0], "Keywords": "\u2014\U00010d6e\U0001e5ff"}])
        query = f'''let
    #"Customer Topic Overrides JSON (optional)" = {m_string(payload)},
    CustomerTopicRules = ({build_customer_topic_rules()}),
    TopicRules = CustomerTopicRules,
    ClassifyTopic = ({build_classifier()}),
    Cases = Json.Document(Text.ToBinary({m_string(json.dumps(cases))}, TextEncoding.Utf8)),
    Checks = List.Transform(Cases, (test) => let actual = ClassifyTopic(test[prompt], test[locale])
        in List.AllTrue(List.Transform(Record.FieldNames(test[expected]), (field) => Record.Field(actual, field) = Record.Field(test[expected], field)))),
    InvalidRules = let #"Customer Topic Overrides JSON (optional)" = {m_string(invalid)} in ({build_customer_topic_rules()}),
    InvalidCheck = try Table.RowCount(InvalidRules)
in
    if List.AllTrue(Checks) and InvalidCheck[HasError] then #table({{"Status"}}, {{{{"ESS_CANONICALIZATION_PASS"}}}})
    else error "ESS_CANONICALIZATION_MISMATCH"
'''
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            extension = root / "ESSCanonicalization.mez"
            with zipfile.ZipFile(extension, "w", zipfile.ZIP_DEFLATED) as package:
                package.writestr("ESSCanonicalization.pq", "section ESSCanonicalization;\nshared ESSCanonicalization.Contents = () => " + query + ";")
            path = root / "canonicalization.query.pq"
            path.write_text("ESSCanonicalization.Contents()", encoding="utf-8")
            completed = subprocess.run([executable, "run-test", "--extension", str(extension), "--queryFile", str(path)],
                                       capture_output=True, text=True, encoding="utf-8", timeout=120)
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            self.assertIn("ESS_CANONICALIZATION_PASS", completed.stdout)
            self.assertNotIn("ESS_CANONICALIZATION_MISMATCH", completed.stdout + completed.stderr)

    def test_csv_rule_parsing_canonicalizes_locales_and_rejects_punctuation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "rules.csv"
            for keywords in ("Device\u2011Enrollment|device enrollment", "---|?!", "\u2014\u2019\uff0c"):
                with path.open("w", encoding="utf-8", newline="") as handle:
                    writer = csv.DictWriter(handle, fieldnames=("Locale", "Vertical", "CanonicalTopic", "Keywords", "Exclusions", "Priority"))
                    writer.writeheader()
                    writer.writerow({"Locale": "en-US", "Vertical": "Customer", "CanonicalTopic": "Enrollment", "Keywords": keywords,
                                     "Exclusions": "", "Priority": 120})
                if keywords.startswith("Device"):
                    rules = load_rules(path)
                    self.assertEqual(rules[0]["Locale"], "en")
                    self.assertEqual(rules[0]["Keywords"], "device enrollment")
                else:
                    with self.assertRaisesRegex(ValueError, "keywords after normalization"):
                        load_rules(path, enabled_only=False)

    def test_generated_power_query_uses_shared_unicode_normalization_contract(self):
        normalization = build_normalization()
        for separator in set(SEPARATOR_CHARACTERS):
            token = f"#({ord(separator):04X})" if ord(separator) <= 0xFFFF else '"' + separator + '"'
            self.assertIn(token, normalization)
        for expression in (build_classifier(), build_customer_topic_rules()):
            self.assertIn(normalization, expression)
            self.assertIn("NormalizeTerms", expression)
            self.assertIn("RuleLocale", expression)
            self.assertIn("Keywords after normalization", expression)

    def test_separator_table_is_independent_of_python_unicode_version(self):
        self.assertEqual(SEPARATOR_UNICODE_VERSION, "16.0.0")
        self.assertEqual(len(SEPARATOR_CHARACTERS), 892)
        self.assertEqual(len(set(SEPARATOR_CHARACTERS)), 892)
        for separator in ("\U00010d6e", "\U00016d6d", "\U0001e5ff"):
            self.assertIn(separator, SEPARATOR_CHARACTERS)
            self.assertEqual(normalize(f"device{separator}enrollment"), "device enrollment")
            self.assertEqual(normalize(separator), "")

    @classmethod
    def setUpClass(cls):
        cls.rules = load_rules(TAXONOMY)

    def test_every_keyword_routes_to_its_declared_topic(self):
        cases = 0
        for rule in self.rules:
            locale = LOCALES[rule["Locale"]]
            for keyword in rule["Keywords"].split("|"):
                keyword = keyword.strip()
                variants = (
                    keyword,
                    f"Please help with {keyword}.",
                    f"({keyword.upper()})",
                )
                for prompt in variants:
                    with self.subTest(
                        locale=locale,
                        topic=rule["CanonicalTopic"],
                        keyword=keyword,
                        prompt=prompt,
                    ):
                        result = classify(prompt, locale, self.rules)
                        self.assertEqual(
                            (
                                result["vertical"],
                                result["topic"],
                            ),
                            (
                                rule["Vertical"],
                                rule["CanonicalTopic"],
                            ),
                        )
                    cases += 1
        self.assertGreaterEqual(cases, 1700)

    def test_taxonomy_schema_and_values_are_complete(self):
        with TAXONOMY.open(
            "r",
            encoding="utf-8-sig",
            newline="",
        ) as handle:
            reader = csv.DictReader(handle)
            rows = list(reader)
        self.assertEqual(
            reader.fieldnames,
            [
                "Locale",
                "Vertical",
                "CanonicalTopic",
                "Keywords",
                "Exclusions",
                "Priority",
            ],
        )
        self.assertEqual(len(rows), 74)
        rule_keys = set()
        for row_number, row in enumerate(rows, start=2):
            with self.subTest(row=row_number):
                for field in (
                    "Locale",
                    "Vertical",
                    "CanonicalTopic",
                    "Keywords",
                    "Priority",
                ):
                    self.assertTrue(row[field].strip())
                self.assertIn(row["Locale"], LOCALES)
                self.assertTrue(row["Priority"].isdigit())
                self.assertGreaterEqual(int(row["Priority"]), 0)
                keywords = [
                    normalize(value)
                    for value in row["Keywords"].split("|")
                ]
                self.assertTrue(all(keywords))
                self.assertEqual(len(keywords), len(set(keywords)))
                rule_key = (
                    row["Locale"],
                    row["Vertical"],
                    row["CanonicalTopic"],
                )
                self.assertNotIn(rule_key, rule_keys)
                rule_keys.add(rule_key)

    def test_no_keyword_has_cross_topic_ownership(self):
        ownership = {}
        for rule in self.rules:
            for keyword in rule["Keywords"].split("|"):
                key = (rule["Locale"], normalize(keyword))
                ownership.setdefault(key, set()).add(
                    (rule["Vertical"], rule["CanonicalTopic"])
                )
        collisions = {
            key: topics
            for key, topics in ownership.items()
            if len(topics) > 1
        }
        self.assertEqual(collisions, {})

    def test_every_exclusion_blocks_its_rule(self):
        cases = 0
        for rule in self.rules:
            exclusions = [
                value.strip()
                for value in rule["Exclusions"].split("|")
                if value.strip()
            ]
            if not exclusions:
                continue
            keyword = rule["Keywords"].split("|")[0].strip()
            locale = LOCALES[rule["Locale"]]
            for exclusion in exclusions:
                with self.subTest(
                    topic=rule["CanonicalTopic"],
                    exclusion=exclusion,
                ):
                    result = classify(
                        f"{keyword} {exclusion}",
                        locale,
                        self.rules,
                    )
                    self.assertNotEqual(
                        (
                            result["vertical"],
                            result["topic"],
                        ),
                        (
                            rule["Vertical"],
                            rule["CanonicalTopic"],
                        ),
                    )
                cases += 1
        self.assertGreater(cases, 0)

    def test_word_boundaries_prevent_partial_matches(self):
        latin_keywords = {
            normalize(keyword)
            for rule in self.rules
            if rule["Locale"] != "zh"
            for keyword in rule["Keywords"].split("|")
            if normalize(keyword)
        }
        for keyword in latin_keywords:
            with self.subTest(keyword=keyword):
                result = classify(
                    f"prefix{keyword.replace(' ', '')}suffix",
                    "en-US",
                    self.rules,
                )
                self.assertEqual(result["topic"], "Other / Uncategorized")

    def test_core_decision_paths(self):
        synthetic = [
            {
                "Locale": "*",
                "Vertical": "One",
                "CanonicalTopic": "Lower Priority",
                "Keywords": "shared",
                "Exclusions": "",
                "Priority": 10,
                "RuleSource": "BuiltIn",
            },
            {
                "Locale": "*",
                "Vertical": "Two",
                "CanonicalTopic": "Higher Priority",
                "Keywords": "shared",
                "Exclusions": "",
                "Priority": 20,
                "RuleSource": "Customer",
            },
        ]
        result = classify("shared", "en-US", synthetic)
        self.assertEqual(result["topic"], "Higher Priority")
        self.assertEqual(result["version"], "ESS-TOPICS-2026.10+CUSTOMER")

        same_priority = [dict(item, Priority=20) for item in synthetic]
        result = classify("shared", "en-US", same_priority)
        self.assertEqual(result["topic"], "Higher Priority")
        self.assertFalse(result["ambiguous"])

        tied = [
            dict(item, Priority=20, RuleSource="Customer")
            for item in synthetic
        ]
        result = classify("shared", "en-US", tied)
        self.assertEqual(result["topic"], "Other / Uncategorized")
        self.assertTrue(result["ambiguous"])
        self.assertEqual(result["confidence"], 0.4)

        result = classify("", "en-US", self.rules)
        self.assertEqual(result["topic"], "No User Intent")
        self.assertEqual(result["vertical"], "System-Init")

    def test_locale_specific_rules_require_the_matching_language(self):
        synthetic = [
            {
                "Locale": "es",
                "Vertical": "HR",
                "CanonicalTopic": "Spanish Only",
                "Keywords": "palabra exclusiva",
                "Exclusions": "",
                "Priority": 90,
                "RuleSource": "BuiltIn",
            }
        ]
        self.assertEqual(
            classify(
                "palabra exclusiva",
                "es-MX",
                synthetic,
            )["topic"],
            "Spanish Only",
        )
        self.assertEqual(
            classify(
                "palabra exclusiva",
                "en-US",
                synthetic,
            )["topic"],
            "Other / Uncategorized",
        )

    def test_generated_fabric_classifier_matches_reference(self):
        stage = build_stage_one(read_taxonomy(TAXONOMY))
        runtime = {
            "re": re,
            "TOPIC_OVERRIDES_FILE": "",
        }
        exec(stage.split("_classified =", 1)[0], runtime)
        fabric_rules = runtime["TOPIC_RULES"]
        fabric_classify = runtime["classify_topic_keyword"]

        cases = []
        for rule in self.rules:
            locale = LOCALES[rule["Locale"]]
            for keyword in rule["Keywords"].split("|"):
                keyword = keyword.strip()
                cases.extend(
                    (
                        (keyword, locale, self.rules, fabric_rules),
                        (
                            f"Please help with {keyword}.",
                            locale,
                            self.rules,
                            fabric_rules,
                        ),
                    )
                )
        cases.append(("", "en-US", self.rules, fabric_rules))
        synthetic = [
            {
                "Locale": "*",
                "Vertical": "One",
                "CanonicalTopic": "Built In",
                "Keywords": "shared",
                "Exclusions": "",
                "Priority": 20,
                "RuleSource": "BuiltIn",
            },
            {
                "Locale": "*",
                "Vertical": "Two",
                "CanonicalTopic": "Customer",
                "Keywords": "shared",
                "Exclusions": "",
                "Priority": 30,
                "RuleSource": "Customer",
            },
        ]
        fabric_synthetic = [
            {
                "locale": item["Locale"],
                "vertical": item["Vertical"],
                "topic": item["CanonicalTopic"],
                "keywords": item["Keywords"].split("|"),
                "exclusions": [],
                "priority": item["Priority"],
                "rule_source": item["RuleSource"],
            }
            for item in synthetic
        ]
        cases.append(
            ("shared", "en-US", synthetic, fabric_synthetic)
        )

        for prompt, locale, reference_rules, generated_rules in cases:
            with self.subTest(locale=locale, prompt=prompt):
                expected = classify(prompt, locale, reference_rules)
                actual = fabric_classify(
                    prompt,
                    locale,
                    generated_rules,
                )
                for field in (
                    "topic",
                    "vertical",
                    "score",
                    "confidence",
                    "ambiguous",
                    "language",
                    "rule_source",
                    "version",
                ):
                    self.assertEqual(actual[field], expected[field])

    def test_source_pbit_contains_generated_power_query(self):
        model = source_model()
        expressions = {
            item["name"]: expression_text(item["expression"])
            for item in model["expressions"]
        }
        self.assertEqual(
            expressions["TopicRules"],
            build_topic_rules(load_taxonomy(TAXONOMY)),
        )
        self.assertEqual(
            expressions["ClassifyTopic"],
            build_classifier(),
        )
        self.assertEqual(expressions["CustomerTopicRules"], build_customer_topic_rules())
        with zipfile.ZipFile(SOURCE) as package:
            pending = json.loads(package.read("UnappliedChanges").decode("utf-16-le"))
        queries = {query["name"]: expression_text(query["text"]) for query in pending["queries"]}
        for name in ("TopicRules", "ClassifyTopic", "CustomerTopicRules"):
            self.assertEqual(queries[name].rstrip("\r\n"), expressions[name].rstrip("\r\n"))
        table = next(
            item
            for item in model["tables"]
            if item["name"] == "Agent Performance"
        )
        partition = expression_text(
            table["partitions"][0]["source"]["expression"]
        )
        self.assertIn(build_derived_block(), partition)
        self.assertIn(
            "then ClassifyTopic([FirstUserMessage], [Locale])",
            partition,
        )
        self.assertIn('RuleSource = "Native"', partition)
        self.assertIn('then "Native"', partition)

    def test_service_refresh_build_preserves_classifier_cleanly(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "service-refresh.pbit"
            build_package(
                SOURCE,
                output,
                "https://orgexample.crm.dynamics.com",
            )
            with zipfile.ZipFile(output) as package:
                self.assertNotIn(
                    "UnappliedChanges",
                    package.namelist(),
                )
                model = json.loads(
                    package.read("DataModelSchema").decode("utf-16-le")
                )["model"]
            expressions = {
                item["name"]: expression_text(item["expression"])
                for item in model["expressions"]
            }
            self.assertEqual(
                expressions["TopicRules"].rstrip(),
                build_topic_rules(load_taxonomy(TAXONOMY)).rstrip(),
            )
            self.assertEqual(
                expressions["ClassifyTopic"].rstrip(),
                build_classifier().rstrip(),
            )


if __name__ == "__main__":
    unittest.main()
