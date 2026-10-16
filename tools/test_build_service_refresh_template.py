import json
import os
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

from build_service_refresh_template import (
    build_package,
    normalize_environment_url,
    serialize_registry,
    validate_credits,
    validate_feedback_events,
    validate_org_data,
    validate_topic_overrides,
)


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "ESS Dashboard - Dynamic Topics (Dataverse) V21.pbit"


class ServiceRefreshTemplateTests(unittest.TestCase):
    def test_accepts_supported_dataverse_clouds(self):
        valid_urls = (
            "https://orgexample.crm.dynamics.com",
            "https://orgexample.crm4.dynamics.com/",
            "https://orgexample.crm.microsoftdynamics.us",
            "https://orgexample.crm.appsplatform.us",
            "https://orgexample.crm.dynamics.cn",
            "https://orgexample.crm.microsoftdynamics.de",
        )
        for value in valid_urls:
            with self.subTest(value=value):
                self.assertEqual(
                    normalize_environment_url(value),
                    value.lower().rstrip("/"),
                )

    def test_rejects_non_dataverse_url(self):
        invalid_urls = (
            "https://example.com/path",
            "https://user@orgexample.crm.dynamics.com",
            "https://orgexample.crm.dynamics.com:443",
            "http://orgexample.crm.dynamics.com",
        )
        for value in invalid_urls:
            with self.subTest(value=value), self.assertRaises(ValueError):
                normalize_environment_url(value)

    def test_builds_parameterized_refresh_template(self):
        environment_url = "https://orgexample.crm.dynamics.com"
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "service-refresh.pbit"
            build_package(SOURCE, output, environment_url)

            with zipfile.ZipFile(output) as package:
                self.assertIsNone(package.testzip())
                names = package.namelist()
                self.assertNotIn("UnappliedChanges", names)
                self.assertNotIn(
                    b"/UnappliedChanges",
                    package.read("[Content_Types].xml"),
                )
                self.assertNotIn(
                    b"UnappliedChanges",
                    package.read("_rels/.rels"),
                )
                schema = json.loads(
                    package.read("DataModelSchema").decode("utf-16-le")
                )

            model_expressions = {
                item["name"]: (
                    "\n".join(item["expression"])
                    if isinstance(item["expression"], list)
                    else item["expression"]
                )
                for item in schema["model"].get("expressions", [])
            }
            for table in schema["model"]["tables"]:
                partitions = table.get("partitions", [])
                if len(partitions) != 1:
                    continue
                source = partitions[0].get("source", {})
                expression = source.get("expression")
                if expression is None:
                    continue
                model_expressions[table["name"]] = (
                    "\n".join(expression)
                    if isinstance(expression, list)
                    else expression
                )

            agent_text = model_expressions["Agent Performance"]
            parameterized_source = (
                'Cds.Entities('
                '#"Dataverse Environment URL (required)", null)'
            )
            self.assertEqual(agent_text.count(parameterized_source), 1)
            self.assertNotIn("Cds.Entities(_EnvUrl", agent_text)
            self.assertNotIn(environment_url, agent_text)

            for name in ("Chat + Agent Org Data", "AgentCredits"):
                text = model_expressions[name]
                self.assertNotIn("Web.Contents", text)
                self.assertNotIn("File.Contents", text)

            model_parameters = {
                item["name"]: item
                for item in schema["model"]["expressions"]
            }
            self.assertIn(
                environment_url,
                model_parameters[
                    "Dataverse Environment URL (required)"
                ]["expression"],
            )
            self.assertNotIn("Org Data File", model_parameters)
            self.assertNotIn(
                "Agent Credits  (optional)",
                model_parameters,
            )
            service_description = model_parameters[
                "Dataverse Environment URL (required)"
            ]["description"]
            self.assertIn("connector uses this parameter directly", service_description)
            self.assertNotIn(environment_url, service_description)
            descriptions = [
                str(item.get("description") or "")
                for item in model_parameters.values()
            ]
            for internal_reference in (
                "python",
                ".py",
                "tools/",
                ".cmd",
                "build",
                "generated",
            ):
                self.assertTrue(
                    all(
                        internal_reference not in value.lower()
                        for value in descriptions
                    ),
                    internal_reference,
                )

            with zipfile.ZipFile(SOURCE) as source_package:
                source_changes = json.loads(
                    source_package.read("UnappliedChanges").decode("utf-16-le")
                )
            source_queries = {
                query["name"]: (
                    "\n".join(query["text"])
                    if isinstance(query["text"], list)
                    else query["text"]
                )
                for query in source_changes["queries"]
            }
            self.assertEqual(
                model_expressions["ConversationFeedback"],
                source_queries["ConversationFeedback"],
            )

    def test_service_query_is_independent_of_customer_url(self):
        environment_urls = (
            "https://orgone.crm.dynamics.com",
            "https://orgtwo.crm4.dynamics.com",
        )
        agent_expressions = []
        with tempfile.TemporaryDirectory() as temporary:
            for index, environment_url in enumerate(environment_urls):
                output = Path(temporary) / f"service-refresh-{index}.pbit"
                build_package(SOURCE, output, environment_url)
                with zipfile.ZipFile(output) as package:
                    schema = json.loads(
                        package.read("DataModelSchema").decode("utf-16-le")
                    )
                table = next(
                    item
                    for item in schema["model"]["tables"]
                    if item["name"] == "Agent Performance"
                )
                expression = table["partitions"][0]["source"]["expression"]
                agent_expressions.append(
                    "\n".join(expression)
                    if isinstance(expression, list)
                    else expression
                )

        self.assertEqual(agent_expressions[0], agent_expressions[1])

    def test_embeds_optional_validated_registry(self):
        environment_url = "https://orgexample.crm.dynamics.com"
        registry_json = (
            '[{"RegistryVersion":"1","AgentKey":"employee-self-service",'
            '"AgentLabel":"Employee Self-Service","IsEss":true,'
            '"Selected":true,"Enabled":true,"EnvironmentKey":"",'
            '"EnvironmentName":"","EnvironmentUrl":"","AliasType":'
            '"M365Title","AliasValue":"T_example"}]'
        )
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "service-refresh.pbit"
            build_package(
                SOURCE,
                output,
                environment_url,
                registry_json,
            )
            with zipfile.ZipFile(output) as package:
                schema = json.loads(
                    package.read("DataModelSchema").decode("utf-16-le")
                )
            expressions = {
                item["name"]: item
                for item in schema["model"]["expressions"]
            }
            registry_expression = expressions[
                "Agent Registry JSON"
            ]["expression"]
            self.assertIn("T_example", registry_expression)
            self.assertNotIn(
                "IsParameterQuery=true",
                registry_expression,
            )

    def test_builds_prefilled_desktop_validation_template(self):
        environment_url = "https://orgexample.crm.dynamics.com"
        org_data = ROOT / "SampleData" / "OrgData.csv"
        credits = (
            ROOT
            / "SampleData"
            / "EntitlementConsumptionTenantPerUserDetailsReport_MCSMessages_30_SYNTHETIC.csv"
        )
        registry_path = ROOT / "SampleData" / "agent-registry.json"
        feedback_path = ROOT / "SampleData" / "feedback-events.json"
        registry_rows, registry_json = serialize_registry(registry_path)
        feedback_json, feedback_audit = validate_feedback_events(
            feedback_path,
            registry_rows,
        )

        with tempfile.TemporaryDirectory() as temporary:
            temporary_path = Path(temporary)
            overrides_path = temporary_path / "customer-topic-overrides.json"
            overrides_path.write_text(
                json.dumps(
                    [
                        {
                            "Locale": "en",
                            "Vertical": "Customer",
                            "CanonicalTopic": "Benefits Enrollment",
                            "Keywords": "benefits enrollment",
                            "Exclusions": "",
                            "Priority": 120,
                        }
                    ]
                ),
                encoding="utf-8",
            )
            overrides_json, overrides_audit = validate_topic_overrides(
                overrides_path
            )
            output = temporary_path / "desktop-validation.pbit"
            build_package(
                SOURCE,
                output,
                environment_url,
                registry_json,
                mode="desktop-validation",
                org_data_file=org_data,
                credits_file=credits,
                overrides_json=overrides_json,
                feedback_json=feedback_json,
            )

            with zipfile.ZipFile(output) as package:
                self.assertIsNone(package.testzip())
                self.assertNotIn("UnappliedChanges", package.namelist())
                schema = json.loads(
                    package.read("DataModelSchema").decode("utf-16-le")
                )

        schema_expressions = {
            item["name"]: item
            for item in schema["model"]["expressions"]
        }
        desktop_description = schema_expressions[
            "Dataverse Environment URL (required)"
        ]["description"]
        self.assertIn("Power Apps Session details", desktop_description)
        descriptions = [
            str(item.get("description") or "")
            for item in schema_expressions.values()
        ]
        for internal_reference in (
            "python",
            ".py",
            "tools/",
            ".cmd",
            "build",
            "generated",
        ):
            self.assertTrue(
                all(
                    internal_reference not in value.lower()
                    for value in descriptions
                ),
                internal_reference,
            )
        self.assertIn(
            "approved customer topic rules",
            schema_expressions[
                "Customer Topic Overrides JSON (optional)"
            ]["description"].lower(),
        )
        self.assertIn(
            "approved agents",
            schema_expressions[
                "Feedback Events JSON (optional)"
            ]["description"].lower(),
        )

        expressions = {
            item["name"]: (
                "\n".join(item["expression"])
                if isinstance(item["expression"], list)
                else item["expression"]
            )
            for item in schema["model"]["expressions"]
        }
        tables = {table["name"]: table for table in schema["model"]["tables"]}
        transcript_expression = tables["Agent Performance"]["partitions"][0][
            "source"
        ]["expression"]
        transcript_text = (
            "\n".join(transcript_expression)
            if isinstance(transcript_expression, list)
            else transcript_expression
        )

        self.assertIn(
            'Cds.Entities(#"Dataverse Environment URL (required)", null)',
            transcript_text,
        )
        self.assertNotIn("Cds.Entities(_EnvUrl, null)", transcript_text)
        self.assertIn(str(org_data.resolve()), expressions["Org Data File"])
        self.assertIn(
            str(credits.resolve()),
            expressions["Agent Credits  (optional)"],
        )
        self.assertIn(
            "Benefits Enrollment",
            expressions["Customer Topic Overrides JSON (optional)"],
        )
        self.assertIn(
            "synthetic-external-unique",
            expressions["Feedback Events JSON (optional)"],
        )
        self.assertIn("ess-synthetic", expressions["Agent Registry JSON"])
        self.assertEqual(overrides_audit["enabledRules"], 1)
        self.assertEqual(feedback_audit["events"], 2)

    def test_validates_desktop_source_contracts_and_registry_match(self):
        registry_rows, _ = serialize_registry(
            ROOT / "SampleData" / "agent-registry.json"
        )
        org_audit = validate_org_data(
            ROOT / "SampleData" / "OrgData.csv"
        )
        credits_audit = validate_credits(
            ROOT
            / "SampleData"
            / "EntitlementConsumptionTenantPerUserDetailsReport_MCSMessages_30_SYNTHETIC.csv",
            registry_rows,
        )

        self.assertEqual(org_audit["missingOptionalAttributes"], [])
        self.assertEqual(org_audit["warning"], "")
        self.assertEqual(
            credits_audit["matchedRegistryCreditIds"],
            ["f1d40245-f319-4e2d-8023-9e7b6f6456ac"],
        )
        self.assertEqual(credits_audit["warning"], "")

    def test_monitor_feedback_can_reconcile_by_conversation(self):
        registry_rows, _ = serialize_registry(
            ROOT / "SampleData" / "agent-registry.json"
        )
        with tempfile.TemporaryDirectory() as temporary:
            feedback_path = Path(temporary) / "monitor-feedback.json"
            feedback_path.write_text(
                json.dumps(
                    [
                        {
                            "FeedbackEventId": "monitor-1",
                            "ConversationId": "conversation-1",
                            "AgentId": "",
                            "FeedbackSource": "MonitorReactions.csv",
                            "FeedbackVerdict": "Thumbs Up",
                        }
                    ]
                ),
                encoding="utf-8",
            )

            _, audit = validate_feedback_events(
                feedback_path,
                registry_rows,
            )

        self.assertEqual(audit["events"], 1)

    def test_product_feedback_requires_registered_agent(self):
        registry_rows, _ = serialize_registry(
            ROOT / "SampleData" / "agent-registry.json"
        )
        with tempfile.TemporaryDirectory() as temporary:
            feedback_path = Path(temporary) / "product-feedback.json"
            feedback_path.write_text(
                json.dumps(
                    [
                        {
                            "FeedbackEventId": "product-1",
                            "ConversationId": "unsupported-metadata-id",
                            "AgentId": "",
                            "FeedbackSource": "Microsoft 365 Product Feedback",
                            "FeedbackVerdict": "Thumbs Up",
                        }
                    ]
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(
                ValueError,
                "neither an enabled registry AgentKey",
            ):
                validate_feedback_events(feedback_path, registry_rows)

    def test_rejects_local_files_in_service_refresh_mode(self):
        with self.assertRaisesRegex(ValueError, "not supported"):
            build_package(
                SOURCE,
                Path("unused.pbit"),
                "https://orgexample.crm.dynamics.com",
                mode="service-refresh",
                org_data_file=ROOT / "SampleData" / "OrgData.csv",
            )

    def test_accepts_multiple_rules_for_one_customer_topic(self):
        rules = [
            {
                "Locale": "en",
                "Vertical": "HR",
                "CanonicalTopic": "Payroll Help",
                "Keywords": "pay statement",
                "Exclusions": "",
                "Priority": 120,
            },
            {
                "Locale": "en",
                "Vertical": "HR",
                "CanonicalTopic": "Payroll Help",
                "Keywords": "salary correction",
                "Exclusions": "",
                "Priority": 120,
            },
        ]
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "customer-topic-overrides.json"
            path.write_text(json.dumps(rules), encoding="utf-8")

            serialized, audit = validate_topic_overrides(path)

        self.assertEqual(json.loads(serialized), rules)
        self.assertEqual(audit["enabledRules"], 2)

    def test_cli_output_is_ascii_safe_for_unicode_paths(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "客户" / "service-refresh.pbit"
            completed = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "tools" / "build_service_refresh_template.py"),
                    "--mode",
                    "service-refresh",
                    "--input",
                    str(SOURCE),
                    "--environment-url",
                    "https://orgexample.crm.dynamics.com",
                    "--output",
                    str(output),
                ],
                check=False,
                capture_output=True,
                env={**os.environ, "PYTHONIOENCODING": "cp1252"},
            )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertTrue(completed.stdout.isascii())
        self.assertEqual(
            json.loads(completed.stdout.decode("ascii"))["output"],
            str(output.resolve()),
        )


if __name__ == "__main__":
    unittest.main()
