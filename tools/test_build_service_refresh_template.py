import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from build_service_refresh_template import (
    build_package,
    normalize_environment_url,
)


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "ESS Dashboard - Dynamic Topics (Dataverse) V20.pbit"


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

    def test_builds_static_refresh_template(self):
        environment_url = "https://orgexample.crm.dynamics.com"
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "service-refresh.pbit"
            build_package(SOURCE, output, environment_url)

            with zipfile.ZipFile(output) as package:
                self.assertIsNone(package.testzip())
                schema = json.loads(
                    package.read("DataModelSchema").decode("utf-16-le")
                )
                changes = json.loads(
                    package.read("UnappliedChanges").decode("utf-16-le")
                )

            queries = {
                query["name"]: query
                for query in changes["queries"]
            }
            agent_text = "\n".join(
                queries["Agent Performance"]["text"]
            )
            self.assertIn(
                f'Cds.Entities("{environment_url}", null)',
                agent_text,
            )
            self.assertNotIn("Cds.Entities(_EnvUrl", agent_text)

            for name in ("Chat + Agent Org Data", "AgentCredits"):
                text = "\n".join(queries[name]["text"])
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
            self.assertNotIn("Org Data File", queries)
            self.assertNotIn("Agent Credits  (optional)", queries)
            self.assertNotIn("Org Data File", model_parameters)
            self.assertNotIn(
                "Agent Credits  (optional)",
                model_parameters,
            )


if __name__ == "__main__":
    unittest.main()
