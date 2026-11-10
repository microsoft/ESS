import json
import unittest
from unittest.mock import patch

from semantic_topic_classifier import (
    SemanticConfig,
    build_topic_catalog,
    classify_semantic_batch,
)


class _Response:
    def __init__(self, payload: dict):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


class SemanticTopicClassifierTests(unittest.TestCase):
    def setUp(self) -> None:
        self.catalog = build_topic_catalog(
            [
                {
                    "Vertical": "HR",
                    "CanonicalTopic": "Benefits & Retirement",
                    "Keywords": "benefits|medical plan",
                },
                {
                    "Vertical": "IT",
                    "CanonicalTopic": "Device & Hardware",
                    "Keywords": "laptop|company device",
                },
            ]
        )
        self.config = SemanticConfig(
            endpoint="https://customer.openai.azure.com",
            deployment="approved-model",
            api_key="not-a-real-key",
        )

    def test_structured_classification_is_constrained_to_catalog(self) -> None:
        provider_result = {
            "classifications": [
                {
                    "id": "S0001",
                    "topic": "Benefits & Retirement",
                    "confidence": 0.97,
                },
                {"id": "S0002", "topic": None, "confidence": 0.42},
            ]
        }
        response = {
            "choices": [
                {"message": {"content": json.dumps(provider_result)}}
            ]
        }
        with patch(
            "semantic_topic_classifier.urllib.request.urlopen",
            return_value=_Response(response),
        ) as urlopen:
            results = classify_semantic_batch(
                [
                    {"id": "S0001", "language": "en", "text": "medical coverage"},
                    {"id": "S0002", "language": "en", "text": "unclear request"},
                ],
                self.catalog,
                self.config,
            )

        self.assertEqual(results[0]["vertical"], "HR")
        self.assertIsNone(results[1]["topic"])
        request = urlopen.call_args.args[0]
        self.assertEqual(
            request.full_url,
            "https://customer.openai.azure.com/openai/v1/chat/completions",
        )
        self.assertEqual(request.headers["Api-key"], "not-a-real-key")
        body = json.loads(request.data.decode("utf-8"))
        self.assertFalse(body["store"])
        self.assertEqual(
            body["response_format"]["type"],
            "json_schema",
        )

    def test_non_microsoft_endpoint_is_rejected_before_network_access(self) -> None:
        config = SemanticConfig(
            endpoint="https://example.com",
            deployment="model",
            api_key="secret",
        )
        with patch(
            "semantic_topic_classifier.urllib.request.urlopen"
        ) as urlopen:
            with self.assertRaisesRegex(ValueError, "customer-owned Azure"):
                classify_semantic_batch(
                    [{"id": "S1", "text": "benefits"}],
                    self.catalog,
                    config,
                )
        urlopen.assert_not_called()

    def test_topic_outside_catalog_is_rejected(self) -> None:
        response = {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "classifications": [
                                    {
                                        "id": "S1",
                                        "topic": "Invented Topic",
                                        "confidence": 0.99,
                                    }
                                ]
                            }
                        )
                    }
                }
            ]
        }
        with patch(
            "semantic_topic_classifier.urllib.request.urlopen",
            return_value=_Response(response),
        ):
            with self.assertRaisesRegex(ValueError, "outside the approved taxonomy"):
                classify_semantic_batch(
                    [{"id": "S1", "text": "invent a topic"}],
                    self.catalog,
                    self.config,
                )

    def test_malformed_structured_values_are_rejected(self) -> None:
        invalid_results = (
            {"classifications": 42},
            {
                "classifications": [
                    {
                        "id": "S1",
                        "topic": "Benefits & Retirement",
                        "confidence": "0.99",
                    }
                ]
            },
            {
                "classifications": [
                    {
                        "id": "S1",
                        "topic": "Benefits & Retirement",
                        "confidence": True,
                    }
                ]
            },
            {
                "classifications": [
                    {
                        "id": 1,
                        "topic": "Benefits & Retirement",
                        "confidence": 0.99,
                    }
                ]
            },
            {
                "classifications": [
                    {
                        "id": "S1",
                        "topic": "Benefits & Retirement",
                        "confidence": 0.99,
                        "extra": "not allowed",
                    }
                ]
            },
        )
        for invalid in invalid_results:
            response = {
                "choices": [
                    {"message": {"content": json.dumps(invalid)}}
                ]
            }
            with self.subTest(invalid=invalid), patch(
                "semantic_topic_classifier.urllib.request.urlopen",
                return_value=_Response(response),
            ):
                with self.assertRaisesRegex(
                    ValueError,
                    "required structured output|invalid classification",
                ):
                    classify_semantic_batch(
                        [{"id": "S1", "text": "benefits"}],
                        self.catalog,
                        self.config,
                    )


if __name__ == "__main__":
    unittest.main()
