#!/usr/bin/env python3
"""Build validated Desktop or Service-refresh Dataverse PBIT packages."""

from __future__ import annotations

import argparse
import base64
import csv
import gzip
import hashlib
import hmac
import io
import json
import os
import re
import sys
import tempfile
import uuid
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import unquote, urlparse, urlunparse

from agent_registry import load_registry
from topic_classifier import canonical_terms, rule_locale


ROOT = Path(__file__).resolve().parents[1]
M_TYPE_BY_TABULAR_TYPE = {
    "string": "nullable text",
    "dateTime": "nullable datetime",
    "date": "nullable date",
    "boolean": "nullable logical",
    "int64": "nullable number",
    "double": "nullable number",
    "decimal": "nullable number",
}

ENVIRONMENT_PARAMETER = "Dataverse Environment URL (required)"
REGISTRY_EXPRESSION = "Agent Registry JSON"
ORG_DATA_PARAMETER = "Org Data File"
CREDITS_PARAMETER = "Agent Credits  (optional)"
OVERRIDES_PARAMETER = "Customer Topic Overrides JSON (optional)"
CONVERSATION_TOPICS_PARAMETER = "Customer Conversation Topics JSON (optional)"
CONVERSATION_REVIEW_DIGEST = "Approved Conversation Review Digest"
FEEDBACK_PARAMETER = "Feedback Events JSON (optional)"
DISABLED_FILE_PARAMETERS = (
    ORG_DATA_PARAMETER,
    CREDITS_PARAMETER,
)
BUILD_MODES = ("service-refresh", "desktop-validation", "service-direct")
SERVICE_MODES = ("service-refresh", "service-direct")
TOPIC_RULE_COLUMNS = (
    "Locale",
    "Vertical",
    "CanonicalTopic",
    "Keywords",
    "Exclusions",
    "Priority",
)
TOPIC_RULE_ORIGINS = {
    "CustomerExplicit",
    "CustomerSaved",
    "NativeLearned",
    "SemanticLearned",
}
CONVERSATION_TOPIC_COLUMNS = (
    "ConversationTranscriptId",
    "Vertical",
    "CanonicalTopic",
    "Confidence",
    "ProviderVersion",
    "ReviewDigest",
)
SEMANTIC_REVIEW_COLUMNS = (
    "ReviewGroup",
    "Enabled",
    "Locale",
    "SupportingConversations",
    "SuggestedVertical",
    "SuggestedTopic",
    "AlternativeTopics",
    "MinimumSimilarity",
    "MinimumMargin",
    *(f"Example{index}" for index in range(1, 11)),
    "DecisionVertical",
    "DecisionTopic",
    "Notes",
)
SEMANTIC_REVIEW_MUTABLE_COLUMNS = {
    "Enabled",
    "DecisionVertical",
    "DecisionTopic",
    "Notes",
}
PPAC_CREDIT_COLUMNS = {
    "User Id",
    "User Email",
    "Agent Id",
    "Agent Name",
    "Billable credit used",
    "Credits used",
    "M365 Copilot Licensed",
}
LEGACY_CREDIT_COLUMNS = {
    "Agent ID",
    "Agent name",
    "User principal name",
    "Display name",
    "Billing policy ID",
    "Past 7 days",
    "Past 30 days",
    "Last activity date (UTC)",
}
FEEDBACK_REQUIRED_COLUMNS = {
    "FeedbackEventId",
    "AgentId",
    "FeedbackSource",
    "FeedbackVerdict",
}
DATAVERSE_HOST_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"^[a-z0-9-]+\.crm\d*\.dynamics\.com$",
        r"^[a-z0-9-]+\.crm\.microsoftdynamics\.us$",
        r"^[a-z0-9-]+\.crm\.appsplatform\.us$",
        r"^[a-z0-9-]+\.crm\.dynamics\.cn$",
        r"^[a-z0-9-]+\.crm\.microsoftdynamics\.de$",
    )
)
ENVIRONMENT_DESCRIPTION = (
    "Required. The Dataverse environment that contains the Copilot Studio "
    "conversation data. Use the Environment URL from Power Apps Developer resources. "
    "The connector uses this parameter directly; after changing environments in "
    "Power BI Service, update the Dataverse credentials before refreshing."
)
PARAMETERIZED_DATAVERSE_SOURCE = (
    'Cds.Entities(#"Dataverse Environment URL (required)", null)'
)
LEGACY_DATAVERSE_SOURCE = "Cds.Entities(_EnvUrl, null)"
PARAMETER_DESCRIPTIONS = {
    REGISTRY_EXPRESSION: (
        "Optional. Approved agent mapping for stable labels and cross-source "
        "identity matching. Required when cross-channel Product Feedback is loaded."
    ),
    ORG_DATA_PARAMETER: (
        "Optional. Approved user roster CSV for organization analysis. The file "
        "must contain UserPrincipalName, UPN, or PersonId. Leave blank to skip."
    ),
    CREDITS_PARAMETER: (
        "Optional. User-Level Credit Consumption CSV from Power Platform admin "
        "center. Leave blank to skip credit-consumption analysis."
    ),
    OVERRIDES_PARAMETER: (
        "Optional. Approved customer topic rules for recurring language that native "
        "and built-in topics do not classify reliably. Leave blank to use the "
        "built-in taxonomy."
    ),
    FEEDBACK_PARAMETER: (
        "Optional. Prepared Microsoft 365 or Monitor feedback events limited to "
        "approved agents. Leave blank to use transcript-native reactions only."
    ),
}
DIRECT_FEEDBACK_DESCRIPTION = (
    "Optional. Prepared Monitor feedback events whose Conversation ID matches one "
    "exact loaded conversation. Use the guided setup for registry-dependent "
    "Microsoft 365 Product Feedback. Leave blank to use transcript-native reactions only."
)
PACKAGED_PLACEHOLDER_EXAMPLES = (
    " (e.g. https://orgabc12345.crm.dynamics.com)",
)
DESKTOP_SOURCE_PAYLOAD_SHA256 = (
    "c044a61c4d09c4fa93e9b135be53908737999c4fca23d3cef0b6f4608d3dc241"
)
DESKTOP_SOURCE_PAYLOAD = (
    "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"
)
CONTENT_TYPES_NAMESPACE = (
    "http://schemas.openxmlformats.org/package/2006/content-types"
)
RELATIONSHIPS_NAMESPACE = (
    "http://schemas.openxmlformats.org/package/2006/relationships"
)


def m_text(value: str) -> str:
    return f'"{value.replace(chr(34), chr(34) * 2)}"'


def strip_packaged_placeholder_examples(value):
    if isinstance(value, dict):
        return {
            key: strip_packaged_placeholder_examples(child)
            for key, child in value.items()
        }
    if isinstance(value, list):
        return [strip_packaged_placeholder_examples(child) for child in value]
    if isinstance(value, str):
        for example in PACKAGED_PLACEHOLDER_EXAMPLES:
            value = value.replace(example, "")
    return value


def desktop_source_payload() -> dict:
    payload_bytes = gzip.decompress(base64.b64decode(DESKTOP_SOURCE_PAYLOAD))
    if hashlib.sha256(payload_bytes).hexdigest() != DESKTOP_SOURCE_PAYLOAD_SHA256:
        raise ValueError("Desktop source definitions failed their integrity check")
    return json.loads(payload_bytes)


def order_org_loader_before_result(expression: str) -> str:
    result_marker = "\n    Result =\n"
    loader_marker = "\n    // Loader (only invoked when a path is provided)\n"
    final_marker = "\nin\n    Result"
    result_start = expression.find(result_marker)
    loader_start = expression.find(loader_marker)
    final_start = expression.rfind(final_marker)
    if not 0 <= result_start < loader_start < final_start:
        raise ValueError("Organization query binding order is not recognized")

    result_block = expression[result_start:loader_start].rstrip()
    loader_block = expression[loader_start:final_start].rstrip()
    if not result_block.endswith(",") or loader_block.endswith(","):
        raise ValueError("Organization query binding delimiters are not recognized")

    return (
        expression[:result_start]
        + loader_block
        + ",\n"
        + result_block[:-1]
        + expression[final_start:]
    )


def restore_desktop_sources(schema: dict) -> None:
    payload = desktop_source_payload()
    expressions = schema["model"]["expressions"]
    existing = {item["name"] for item in expressions}
    lineage_tags = {
        item["lineageTag"].casefold()
        for item in expressions
        if item.get("lineageTag")
    }
    for parameter in payload["parameters"]:
        if parameter["name"] not in existing:
            parameter = json.loads(json.dumps(parameter))
            lineage_tag = parameter.get("lineageTag")
            if lineage_tag and lineage_tag.casefold() in lineage_tags:
                seed = f"ess-desktop-expression:{parameter['name']}:{lineage_tag}"
                lineage_tag = str(uuid.uuid5(uuid.NAMESPACE_URL, seed))
                parameter["lineageTag"] = lineage_tag
            expressions.append(parameter)
            if lineage_tag:
                lineage_tags.add(lineage_tag.casefold())
    tables = {
        table["name"]: table
        for table in schema["model"]["tables"]
    }
    for table_name, expression in payload["queries"].items():
        partition = tables[table_name]["partitions"][0]
        source = partition["source"]
        source["expression"] = store_expression(
            source["expression"],
            expression_text(expression),
        )


def normalize_environment_url(value: str) -> str:
    parsed = urlparse(value.strip())
    if (
        parsed.scheme.lower() != "https"
        or not parsed.hostname
        or not any(
            pattern.fullmatch(parsed.hostname)
            for pattern in DATAVERSE_HOST_PATTERNS
        )
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port is not None
        or parsed.path not in ("", "/")
        or parsed.params
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError(
            "Environment URL must be an HTTPS Dataverse root URL such as "
            "https://orgabc12345.crm.dynamics.com."
        )
    return f"https://{parsed.hostname.lower()}"


def normalize_org_data_url(value: str) -> str:
    parsed = urlparse(value.strip())
    hostname = (parsed.hostname or "").lower()
    sharepoint_suffixes = (
        ".sharepoint.com",
        ".sharepoint.us",
        ".sharepoint-mil.us",
        ".sharepoint.de",
        ".sharepoint.cn",
    )
    if (
        parsed.scheme.lower() != "https"
        or not any(hostname.endswith(suffix) for suffix in sharepoint_suffixes)
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port is not None
        or not parsed.path.lower().endswith(".csv")
        or parsed.params
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError(
            "Organization Data URL must be a direct HTTPS CSV path in "
            "SharePoint Online or OneDrive for Business, without sharing-link "
            "query parameters."
        )
    return urlunparse(("https", hostname, parsed.path, "", "", ""))


def sharepoint_file_location(value: str) -> tuple[str, str, str]:
    parsed = urlparse(normalize_org_data_url(value))
    segments = [
        unquote(segment)
        for segment in parsed.path.split("/")
        if segment
    ]
    if not segments:
        raise ValueError("Organization Data URL must identify a CSV file")

    site_segment_count = (
        2
        if len(segments) >= 2
        and segments[0].lower() in {"sites", "teams", "personal"}
        else 0
    )
    site_path = (
        "/" + "/".join(segments[:site_segment_count])
        if site_segment_count
        else ""
    )
    site_url = f"{parsed.scheme}://{parsed.netloc}{site_path}"
    folder_url = (
        f"{parsed.scheme}://{parsed.netloc}/"
        + "/".join(segments[:-1])
        + "/"
    )
    return site_url, folder_url, segments[-1]


def read_csv_rows(path: Path, label: str) -> tuple[list[str], list[dict]]:
    if not path.exists():
        raise ValueError(f"{label} file not found: {path}")
    data = path.read_bytes()
    text = None
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            text = data.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        raise ValueError(f"{label} must be a UTF-8 or Windows-1252 CSV: {path}")
    reader = csv.DictReader(io.StringIO(text))
    fieldnames = [str(name or "").strip() for name in reader.fieldnames or []]
    if not fieldnames:
        raise ValueError(f"{label} has no CSV header: {path}")
    rows = list(reader)
    return fieldnames, rows


def normalized_header(value: str) -> str:
    return re.sub(r"[\s_.()\[\]-]+", "", str(value or "")).casefold()


def validate_org_data(path: Path) -> dict:
    fieldnames, rows = read_csv_rows(path, "Org Data")
    normalized = {normalized_header(name) for name in fieldnames}
    if not normalized.intersection({"userprincipalname", "upn", "personid"}):
        raise ValueError(
            "Org Data must contain UserPrincipalName, UPN, or PersonId."
        )
    optional = {
        "Department": {"department"},
        "Country": {"country", "countryorregion"},
        "JobTitle": {"jobtitle", "title"},
        "DisplayName": {"displayname"},
    }
    missing = [
        label
        for label, aliases in optional.items()
        if not normalized.intersection(aliases)
    ]
    return {
        "contract": "Org Data",
        "rows": len(rows),
        "missingOptionalAttributes": missing,
        "warning": (
            "Missing optional attributes will render as blank: "
            + ", ".join(missing)
            if missing
            else ""
        ),
    }


def normalize_agent_id(value: object) -> str:
    normalized = str(value or "").strip().strip("{}").casefold()
    return normalized[2:] if normalized.startswith("p_") else normalized


def validate_credits(path: Path, registry_rows: list[dict] | None) -> dict:
    fieldnames, rows = read_csv_rows(path, "Agent Credits")
    columns = set(fieldnames)
    if PPAC_CREDIT_COLUMNS.issubset(columns):
        contract = "Power Platform admin center User-Level Credit Consumption"
        agent_column = "Agent Id"
        numeric_columns = ("Billable credit used", "Credits used")
        blank_emails = sum(not str(row.get("User Email") or "").strip() for row in rows)
    elif LEGACY_CREDIT_COLUMNS.issubset(columns):
        contract = "Legacy Microsoft 365 Copilot Credits"
        agent_column = "Agent ID"
        numeric_columns = ("Past 7 days", "Past 30 days")
        blank_emails = sum(
            not str(row.get("User principal name") or "").strip()
            for row in rows
        )
    else:
        raise ValueError(
            "Agent Credits has an unsupported schema. Use the User-Level Credit "
            "Consumption CSV from Power Platform admin center."
        )

    for row_number, row in enumerate(rows, start=2):
        for column in numeric_columns:
            value = str(row.get(column) or "").strip()
            if not value:
                continue
            try:
                float(value.replace(",", ""))
            except ValueError as error:
                raise ValueError(
                    f"Agent Credits row {row_number} has a non-numeric {column}: {value!r}"
                ) from error

    agent_ids = {
        normalize_agent_id(row.get(agent_column))
        for row in rows
        if normalize_agent_id(row.get(agent_column))
    }
    configured_ids = {
        row["AliasValueNormalized"]
        for row in registry_rows or []
        if row["Enabled"] and row["AliasType"] == "CreditId"
    }
    matched_ids = sorted(agent_ids.intersection(configured_ids))
    warning = ""
    if configured_ids and not matched_ids:
        warning = (
            "No Agent Id in this credit export matches an enabled CreditId in the "
            "agent registry. Credit visuals for the registered agents will be blank."
        )
    return {
        "contract": contract,
        "rows": len(rows),
        "distinctAgentIds": len(agent_ids),
        "blankUserEmails": blank_emails,
        "matchedRegistryCreditIds": matched_ids,
        "warning": warning,
    }


def load_json_array(path: Path, label: str) -> list[dict]:
    if not path.exists():
        raise ValueError(f"{label} file not found: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as error:
        raise ValueError(f"{label} is not valid JSON: {error}") from error
    if not isinstance(payload, list) or not all(
        isinstance(item, dict) for item in payload
    ):
        raise ValueError(f"{label} must contain a JSON array of objects.")
    return payload


def validate_topic_overrides(path: Path, *, canonicalize: bool = True) -> tuple[str, dict]:
    rows = load_json_array(path, "Customer Topic Overrides")
    for row_number, row in enumerate(rows, start=1):
        missing = [column for column in TOPIC_RULE_COLUMNS if column not in row]
        if missing:
            raise ValueError(
                f"Customer Topic Overrides rule {row_number} is missing: {missing}"
            )
        for column in ("Vertical", "CanonicalTopic", "Keywords"):
            if not str(row.get(column) or "").strip():
                raise ValueError(
                    f"Customer Topic Overrides rule {row_number} has no {column}."
                )
        if not canonical_terms(str(row["Keywords"])):
            raise ValueError(f"Customer Topic Overrides rule {row_number} has no Keywords after normalization.")
        try:
            int(row["Priority"])
        except (TypeError, ValueError) as error:
            raise ValueError(
                f"Customer Topic Overrides rule {row_number} has an invalid Priority."
            ) from error
        origin = str(row.get("RuleOrigin") or "CustomerSaved").strip()
        if origin not in TOPIC_RULE_ORIGINS:
            raise ValueError(
                f"Customer Topic Overrides rule {row_number} has an invalid RuleOrigin."
            )
    if canonicalize:
        rows = [{**row, "Locale": rule_locale(str(row.get("Locale") or "")),
                 "Keywords": canonical_terms(str(row["Keywords"])),
                 "Exclusions": canonical_terms(str(row.get("Exclusions") or ""))} for row in rows]
    return (
        json.dumps(rows, ensure_ascii=False, separators=(",", ":")),
        {"contract": "Customer Topic Overrides", "enabledRules": len(rows)},
    )


def _spreadsheet_unescape(value):
    if (
        isinstance(value, str)
        and len(value) >= 2
        and value[0] == "'"
        and value[1:].lstrip().startswith(("=", "+", "-", "@"))
    ):
        return value[1:]
    return value


def _semantic_review_payload(
    review_rows: list[dict],
    evidence_rows: list[dict],
) -> bytes:
    immutable = sorted(
        [
            {
                column: str(row.get(column) or "")
                for column in SEMANTIC_REVIEW_COLUMNS
                if column not in SEMANTIC_REVIEW_MUTABLE_COLUMNS
            }
            for row in review_rows
        ],
        key=lambda row: row["ReviewGroup"],
    )
    evidence_rows = sorted(
        evidence_rows,
        key=lambda row: str(row.get("ReviewGroup") or ""),
    )
    return json.dumps(
        {
            "version": 1,
            "review": immutable,
            "evidence": evidence_rows,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _validate_semantic_review_bundle(
    mapping_path: Path,
    mappings: list[dict],
) -> None:
    review_path = mapping_path.with_name("semantic-topic-review.csv")
    evidence_path = mapping_path.with_name("semantic-review-evidence.json")
    key_path = mapping_path.with_name("semantic-review-integrity.key")
    try:
        previous_limit = csv.field_size_limit()
        try:
            csv.field_size_limit(sys.maxsize)
            with review_path.open(
                "r",
                encoding="utf-8-sig",
                newline="",
            ) as handle:
                reader = csv.DictReader(handle)
                if tuple(reader.fieldnames or ()) != SEMANTIC_REVIEW_COLUMNS:
                    raise ValueError("Semantic review columns are invalid.")
                review_rows = [
                    {
                        key: _spreadsheet_unescape(value)
                        for key, value in row.items()
                    }
                    for row in reader
                ]
        finally:
            csv.field_size_limit(previous_limit)
        evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
        key = bytes.fromhex(key_path.read_text(encoding="ascii").strip())
    except (OSError, ValueError, json.JSONDecodeError) as error:
        raise ValueError(
            "Customer Conversation Topics requires its original reviewed "
            "semantic-topic-review.csv, evidence, and integrity key."
        ) from error
    if (
        len(key) != 32
        or not isinstance(evidence, dict)
        or set(evidence) != {"version", "groups", "integrity"}
        or evidence["version"] != 1
        or not isinstance(evidence["groups"], list)
    ):
        raise ValueError("Semantic review approval bundle is invalid.")
    expected = hmac.new(
        key,
        _semantic_review_payload(review_rows, evidence["groups"]),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(expected, str(evidence["integrity"])):
        raise ValueError("Semantic review approval bundle failed integrity validation.")

    evidence_by_group = {
        str(group.get("ReviewGroup") or ""): group.get("Conversations")
        for group in evidence["groups"]
        if isinstance(group, dict)
    }
    expected_mappings = []
    for row in review_rows:
        if str(row.get("Enabled") or "").strip().lower() not in {
            "true",
            "1",
            "yes",
            "y",
        }:
            continue
        group_id = str(row.get("ReviewGroup") or "")
        conversations = evidence_by_group.get(group_id)
        if not isinstance(conversations, list):
            raise ValueError("Semantic review approval bundle has missing evidence.")
        for conversation in conversations:
            if not isinstance(conversation, dict):
                raise ValueError("Semantic review approval bundle has invalid evidence.")
            expected_mappings.append(
                {
                    "ConversationTranscriptId": str(
                        conversation.get("ConversationTranscriptId") or ""
                    ).strip().lower(),
                    "Vertical": str(row.get("DecisionVertical") or "").strip(),
                    "CanonicalTopic": str(row.get("DecisionTopic") or "").strip(),
                    "Confidence": 1.0,
                    "ProviderVersion": "ESS-SEMANTIC-HUMAN-REVIEW-V1",
                    "ReviewDigest": expected,
                }
            )
    expected_mappings.sort(
        key=lambda row: row["ConversationTranscriptId"]
    )
    if mappings != expected_mappings:
        raise ValueError(
            "Customer Conversation Topics does not match the reviewed semantic decisions."
        )


def validate_conversation_topics(path: Path) -> tuple[str, dict]:
    rows = load_json_array(path, "Customer Conversation Topics")
    with (ROOT / "taxonomy" / "topics-taxonomy.csv").open(
        "r",
        encoding="utf-8-sig",
        newline="",
    ) as handle:
        taxonomy_pairs = {
            (
                str(row.get("Vertical") or "").strip(),
                str(row.get("CanonicalTopic") or "").strip(),
            )
            for row in csv.DictReader(handle)
        }

    normalized = []
    seen_ids = set()
    required = set(CONVERSATION_TOPIC_COLUMNS)
    for row_number, row in enumerate(rows, start=1):
        if set(row) != required:
            raise ValueError(
                "Customer Conversation Topics row "
                f"{row_number} must contain exactly: {sorted(required)}"
            )
        conversation_id = str(row["ConversationTranscriptId"] or "").strip().lower()
        if not conversation_id or len(conversation_id) > 256:
            raise ValueError(
                f"Customer Conversation Topics row {row_number} has an invalid ConversationTranscriptId."
            )
        if conversation_id in seen_ids:
            raise ValueError(
                f"Customer Conversation Topics contains duplicate ID {conversation_id}."
            )
        seen_ids.add(conversation_id)

        vertical = str(row["Vertical"] or "").strip()
        topic = str(row["CanonicalTopic"] or "").strip()
        if (vertical, topic) not in taxonomy_pairs:
            raise ValueError(
                f"Customer Conversation Topics row {row_number} is outside the checked-in taxonomy."
            )
        confidence_value = row["Confidence"]
        if isinstance(confidence_value, bool):
            raise ValueError(
                f"Customer Conversation Topics row {row_number} has invalid Confidence."
            )
        try:
            confidence = float(confidence_value)
        except (TypeError, ValueError) as error:
            raise ValueError(
                f"Customer Conversation Topics row {row_number} has invalid Confidence."
            ) from error
        if not 0 <= confidence <= 1:
            raise ValueError(
                f"Customer Conversation Topics row {row_number} has Confidence outside 0-to-1."
            )
        provider_version = str(row["ProviderVersion"] or "").strip()
        if provider_version != "ESS-SEMANTIC-HUMAN-REVIEW-V1":
            raise ValueError(
                f"Customer Conversation Topics row {row_number} has an invalid ProviderVersion."
            )
        review_digest = str(row["ReviewDigest"] or "").strip().lower()
        if not re.fullmatch(r"[0-9a-f]{64}", review_digest):
            raise ValueError(
                f"Customer Conversation Topics row {row_number} has an invalid ReviewDigest."
            )
        normalized.append(
            {
                "ConversationTranscriptId": conversation_id,
                "Vertical": vertical,
                "CanonicalTopic": topic,
                "Confidence": confidence,
                "ProviderVersion": provider_version,
                "ReviewDigest": review_digest,
            }
        )
    normalized.sort(key=lambda row: row["ConversationTranscriptId"])
    if len({row["ReviewDigest"] for row in normalized}) > 1:
        raise ValueError(
            "Customer Conversation Topics must come from one reviewed approval set."
        )
    _validate_semantic_review_bundle(path, normalized)
    return (
        json.dumps(normalized, ensure_ascii=False, separators=(",", ":")),
        {
            "contract": "Customer Conversation Topics",
            "classifiedConversations": len(normalized),
        },
    )


def validate_feedback_events(
    path: Path,
    registry_rows: list[dict] | None,
) -> tuple[str, dict]:
    rows = load_json_array(path, "Feedback Events")
    for row_number, row in enumerate(rows, start=1):
        missing = sorted(FEEDBACK_REQUIRED_COLUMNS - set(row))
        if missing:
            raise ValueError(
                f"Feedback Events row {row_number} is missing: {missing}"
            )
    active_keys = {
        row["AgentKey"]
        for row in registry_rows or []
        if row["Enabled"]
    }
    invalid_identifiers = sorted(
        {
            str(row.get("AgentId") or "").strip() or "<blank>"
            for row in rows
            if (
                str(row.get("AgentId") or "").strip() not in active_keys
                and not (
                    str(row.get("ConversationId") or "").strip()
                    and "product feedback"
                    not in str(row.get("FeedbackSource") or "").casefold()
                )
            )
        }
    )
    if invalid_identifiers:
        raise ValueError(
            "Feedback Events contains rows that have neither an enabled registry "
            "AgentKey nor a supported conversation identifier: "
            f"{invalid_identifiers}"
        )
    return (
        json.dumps(rows, ensure_ascii=False, separators=(",", ":")),
        {"contract": "Feedback Events", "events": len(rows)},
    )


def serialize_registry(path: Path | None) -> tuple[list[dict] | None, str | None]:
    if path is None:
        return None, None
    rows = load_registry(path)
    payload = [
        {
            key: row[key]
            for key in (
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
            )
        }
        for row in rows
    ]
    return rows, json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
    )


def expression_text(value: object) -> str:
    if isinstance(value, list):
        return "\n".join(value)
    if isinstance(value, str):
        return value
    raise TypeError("Unexpected Power Query expression type")


def store_expression(original: object, value: str) -> object:
    return value.split("\n") if isinstance(original, list) else value


def materialize_unapplied_queries(schema: dict, changes: dict) -> None:
    destinations = {
        item["name"]: (item, "expression")
        for item in schema["model"].get("expressions", [])
    }
    for table in schema["model"]["tables"]:
        partitions = table.get("partitions", [])
        if len(partitions) != 1:
            continue
        source = partitions[0].get("source", {})
        if "expression" in source:
            destinations[table["name"]] = (source, "expression")

    missing = []
    for query in changes["queries"]:
        destination = destinations.get(query["name"])
        if destination is None:
            missing.append(query["name"])
            continue
        owner, key = destination
        owner[key] = store_expression(
            owner[key],
            expression_text(query["text"]),
        )
    if missing:
        raise ValueError(
            "Unapplied Power Query definitions are missing from the model: "
            + ", ".join(sorted(missing))
        )


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise ValueError(f"{label}: expected one match, found {count}")
    return text.replace(old, new)


def empty_partition_expression(table: dict) -> str:
    fields = []
    for column in table.get("columns", []):
        source_column = column.get("sourceColumn")
        if not source_column:
            continue
        escaped_name = source_column.replace('"', '""')
        field_type = M_TYPE_BY_TABULAR_TYPE.get(
            column["dataType"],
            "nullable any",
        )
        fields.append(f'            #"{escaped_name}" = {field_type}')
    return (
        "let\n"
        "    Empty = #table(\n"
        "        type table [\n"
        + ",\n".join(fields)
        + "\n"
        "        ],\n"
        "        {}\n"
        "    )\n"
        "in\n"
        "    Empty"
    )


def build_query_expressions(
    schema: dict,
    org_data_url: str | None = None,
) -> dict[str, str]:
    tables = {
        table["name"]: table
        for table in schema["model"]["tables"]
    }
    query_expressions = {}

    agent_table = tables["Agent Performance"]
    partition = agent_table["partitions"][0]
    agent_expression = expression_text(partition["source"]["expression"])
    if PARAMETERIZED_DATAVERSE_SOURCE not in agent_expression:
        agent_expression = replace_once(
            agent_expression,
            LEGACY_DATAVERSE_SOURCE,
            PARAMETERIZED_DATAVERSE_SOURCE,
            "Dataverse connector parameter",
        )
    if agent_expression.count(PARAMETERIZED_DATAVERSE_SOURCE) != 1:
        raise ValueError(
            "Dataverse connector must reference the Environment URL parameter "
            "exactly once."
        )
    if LEGACY_DATAVERSE_SOURCE in agent_expression:
        raise ValueError(
            "Dataverse connector still uses a computed URL instead of the "
            "Environment URL parameter."
        )
    partition["source"]["expression"] = store_expression(
        partition["source"]["expression"],
        agent_expression,
    )
    query_expressions["Agent Performance"] = agent_expression

    org_table = tables["Chat + Agent Org Data"]
    if org_data_url is None:
        org_expression = empty_partition_expression(org_table)
    else:
        org_expression = expression_text(
            desktop_source_payload()["queries"]["Chat + Agent Org Data"]
        ).replace(
            f'#"{ORG_DATA_PARAMETER}"',
            m_text(org_data_url),
        )
        org_expression = order_org_loader_before_result(org_expression)
        desktop_source = '''            IsSharePoint = Text.StartsWith(Text.Lower(FilePath), "http"),

            // SCHEDULED / AUTO-REFRESH REQUIREMENT (see Agent Performance for detail):
            // call Web.Contents with a static base URL (site origin) + RelativePath so the
            // Fabric service can identify and authenticate the source. Passing the whole
            // URL as one string makes it a "dynamic data source" and blocks refresh.
            _AfterScheme = Text.AfterDelimiter(FilePath, "://"),
            _Origin      = Text.BeforeDelimiter(FilePath, "://") & "://" & Text.BeforeDelimiter(_AfterScheme, "/"),
            _Relative    = Text.AfterDelimiter(_AfterScheme, "/"),

            Source = if IsSharePoint then
                Csv.Document(
                    Web.Contents(_Origin, [RelativePath = _Relative]),
                    [Delimiter = ",", Encoding = 1252, QuoteStyle = QuoteStyle.None]
                )
            else
                Csv.Document(
                    File.Contents(FilePath),
                    [Delimiter = ",", Encoding = 1252, QuoteStyle = QuoteStyle.None]
                ),'''
        site_url, folder_url, file_name = sharepoint_file_location(org_data_url)
        service_source = f'''            // Customer-specific Service builds use the native SharePoint
            // connector so Desktop and Service expose an Organizational account
            // credential instead of treating the source as hand-authored Web content.
            SharePointFiles = SharePoint.Files({m_text(site_url)}, [ApiVersion = 15]),
            MatchingFiles = Table.SelectRows(
                SharePointFiles,
                each [Name] = {m_text(file_name)}
                    and Text.Lower(Text.TrimEnd([Folder Path], "/"))
                        = Text.Lower(Text.TrimEnd({m_text(folder_url)}, "/"))
            ),
            SourceBinary =
                if Table.RowCount(MatchingFiles) = 1 then
                    MatchingFiles{{0}}[Content]
                else if Table.IsEmpty(MatchingFiles) then
                    error "Organization CSV was not found at the configured SharePoint path."
                else
                    error "More than one organization CSV matched the configured SharePoint path.",

            Source = Csv.Document(
                SourceBinary,
                [Delimiter = ",", Encoding = 1252, QuoteStyle = QuoteStyle.None]
            ),'''
        org_expression = replace_once(
            org_expression,
            desktop_source,
            service_source,
            "Service organization SharePoint source",
        )
        if "File.Contents" in org_expression:
            raise ValueError(
                "Service organization query still contains a local file source"
            )
    org_partition = org_table["partitions"][0]
    org_partition["source"]["expression"] = store_expression(
        org_partition["source"]["expression"],
        org_expression,
    )
    query_expressions["Chat + Agent Org Data"] = org_expression

    credits_table = tables["AgentCredits"]
    credits_expression = empty_partition_expression(credits_table)
    credits_partition = credits_table["partitions"][0]
    credits_partition["source"]["expression"] = store_expression(
        credits_partition["source"]["expression"],
        credits_expression,
    )
    query_expressions["AgentCredits"] = credits_expression

    return query_expressions


def update_parameter_metadata(
    schema: dict,
    environment_url: str,
    mode: str,
    registry_json: str | None,
    org_data_file: Path | None = None,
    credits_file: Path | None = None,
    overrides_json: str | None = None,
    conversation_topics_json: str | None = None,
    feedback_json: str | None = None,
) -> None:
    parameter_expression = (
        f"{m_text(environment_url)} meta "
        '[IsParameterQuery=true, Type="Text", IsParameterQueryRequired=true]'
    )
    schema_expressions = {
        item["name"]: item
        for item in schema["model"]["expressions"]
    }
    environment = schema_expressions[ENVIRONMENT_PARAMETER]
    environment["expression"] = parameter_expression
    environment["description"] = ENVIRONMENT_DESCRIPTION
    for annotation in environment.get("annotations", []):
        if annotation["name"] == "PBI_ResultType":
            annotation["value"] = "Text"
    for name, parameter_description in PARAMETER_DESCRIPTIONS.items():
        if name in schema_expressions:
            schema_expressions[name]["description"] = parameter_description
    if mode == "service-direct":
        schema_expressions[FEEDBACK_PARAMETER]["description"] = (
            DIRECT_FEEDBACK_DESCRIPTION
        )

    if registry_json is not None:
        registry_expression = m_text(registry_json)
        registry = schema_expressions[REGISTRY_EXPRESSION]
        registry["expression"] = registry_expression

    parameter_values = {
        ORG_DATA_PARAMETER: (
            str(org_data_file.resolve()) if org_data_file is not None else None
        ),
        CREDITS_PARAMETER: (
            str(credits_file.resolve()) if credits_file is not None else None
        ),
        OVERRIDES_PARAMETER: overrides_json,
        CONVERSATION_TOPICS_PARAMETER: conversation_topics_json,
        FEEDBACK_PARAMETER: feedback_json,
    }
    for name, value in parameter_values.items():
        if value is None or name not in schema_expressions:
            continue
        schema_expressions[name]["expression"] = (
            f"{m_text(value)} meta "
            '[IsParameterQuery=true, Type="Text", IsParameterQueryRequired=false]'
        )
    reviewed_digest = None
    if conversation_topics_json is not None:
        reviewed_rows = json.loads(conversation_topics_json)
        if reviewed_rows:
            reviewed_digest = reviewed_rows[0]["ReviewDigest"]
    if CONVERSATION_REVIEW_DIGEST in schema_expressions:
        schema_expressions[CONVERSATION_REVIEW_DIGEST]["expression"] = (
            m_text(reviewed_digest)
            if reviewed_digest is not None
            else "null"
        )

    if mode in SERVICE_MODES:
        schema["model"]["expressions"] = [
            item
            for item in schema["model"]["expressions"]
            if item["name"] not in DISABLED_FILE_PARAMETERS
        ]


def remove_unapplied_changes(
    entries: list[zipfile.ZipInfo],
    payloads: dict[str, bytes],
) -> list[zipfile.ZipInfo]:
    payloads.pop("UnappliedChanges")

    ET.register_namespace("", CONTENT_TYPES_NAMESPACE)
    content_types = ET.fromstring(payloads["[Content_Types].xml"])
    overrides = content_types.findall(
        f"{{{CONTENT_TYPES_NAMESPACE}}}Override"
    )
    removed_overrides = 0
    for override in overrides:
        if override.get("PartName") == "/UnappliedChanges":
            content_types.remove(override)
            removed_overrides += 1
    if removed_overrides != 1:
        raise ValueError(
            "Expected one /UnappliedChanges content-type override, found "
            f"{removed_overrides}"
        )
    payloads["[Content_Types].xml"] = ET.tostring(
        content_types,
        encoding="utf-8",
        xml_declaration=True,
    )

    relationships_path = "_rels/.rels"
    if relationships_path in payloads:
        ET.register_namespace("", RELATIONSHIPS_NAMESPACE)
        relationships = ET.fromstring(payloads[relationships_path])
        for relationship in relationships.findall(
            f"{{{RELATIONSHIPS_NAMESPACE}}}Relationship"
        ):
            if relationship.get("Target", "").lstrip("/") == "UnappliedChanges":
                relationships.remove(relationship)
        payloads[relationships_path] = ET.tostring(
            relationships,
            encoding="utf-8",
            xml_declaration=True,
        )

    return [
        entry
        for entry in entries
        if entry.filename != "UnappliedChanges"
    ]


def build_package(
    input_path: Path,
    output_path: Path,
    environment_url: str,
    registry_json: str | None = None,
    *,
    mode: str = "service-refresh",
    org_data_file: Path | None = None,
    org_data_url: str | None = None,
    credits_file: Path | None = None,
    overrides_json: str | None = None,
    conversation_topics_json: str | None = None,
    feedback_json: str | None = None,
) -> None:
    if mode not in BUILD_MODES:
        raise ValueError(f"Build mode must be one of: {', '.join(BUILD_MODES)}")
    if mode in SERVICE_MODES and (org_data_file or credits_file):
        raise ValueError(
            "Org Data and Agent Credits files are not supported in Service-refresh "
            "mode. Use --mode desktop-validation or Fabric."
        )
    if mode == "desktop-validation" and org_data_url:
        raise ValueError(
            "Organization Data URL is supported only in Service modes. Use "
            "--org-data-file for Desktop validation."
        )
    if org_data_url is not None:
        org_data_url = normalize_org_data_url(org_data_url)
    if mode == "service-direct" and any(
        (
            environment_url,
            registry_json,
            org_data_url,
            overrides_json,
            conversation_topics_json,
            feedback_json,
        )
    ):
        raise ValueError(
            "Service-direct mode must remain customer-neutral. Enter the Environment "
            "URL in Power BI and use the guided setup for optional embedded inputs."
        )
    with zipfile.ZipFile(input_path, "r") as source:
        entries = source.infolist()
        payloads = {
            entry.filename: source.read(entry.filename)
            for entry in entries
        }

    schema = json.loads(
        payloads["DataModelSchema"].decode("utf-16-le")
    )
    schema = strip_packaged_placeholder_examples(schema)
    if "UnappliedChanges" in payloads:
        changes = json.loads(
            payloads["UnappliedChanges"].decode("utf-16-le")
        )
        changes = strip_packaged_placeholder_examples(changes)
        materialize_unapplied_queries(schema, changes)
    if mode == "desktop-validation":
        restore_desktop_sources(schema)
    schema["name"] = str(uuid.uuid4())
    if mode in SERVICE_MODES:
        build_query_expressions(schema, org_data_url)
    update_parameter_metadata(
        schema,
        environment_url,
        mode,
        registry_json,
        org_data_file,
        credits_file,
        overrides_json,
        conversation_topics_json,
        feedback_json,
    )

    payloads["DataModelSchema"] = json.dumps(
        schema,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-16-le")
    if "UnappliedChanges" in payloads:
        entries = remove_unapplied_changes(entries, payloads)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary_name = tempfile.mkstemp(
        prefix=f"{output_path.stem}.",
        suffix=".tmp.pbit",
        dir=output_path.parent,
    )
    os.close(handle)
    temporary_path = Path(temporary_name)
    try:
        with zipfile.ZipFile(temporary_path, "w") as destination:
            for entry in entries:
                destination.writestr(entry, payloads[entry.filename])
        with zipfile.ZipFile(temporary_path, "r") as result:
            if result.testzip() is not None:
                raise ValueError("The generated PBIT is corrupt")
        os.replace(temporary_path, output_path)
    finally:
        temporary_path.unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Build either a gateway-free Service-refresh PBIT or a prevalidated "
            "Desktop PBIT with optional local source files."
        )
    )
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--environment-url")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument(
        "--mode",
        choices=BUILD_MODES,
        default="service-refresh",
        help=(
            "service-refresh removes local file sources and prefills a validated URL; "
            "service-direct leaves the required URL blank for a generic publishable "
            "template; desktop-validation preserves local file sources."
        ),
    )
    parser.add_argument(
        "--agent-registry-json",
        type=Path,
        help=(
            "Optional validated agent-registry.json to embed for advanced "
            "Microsoft 365 feedback or custom identity mapping."
        ),
    )
    parser.add_argument(
        "--org-data-file",
        type=Path,
        help="Desktop-validation Org Data CSV.",
    )
    parser.add_argument(
        "--org-data-url",
        help=(
            "Service-refresh direct HTTPS URL to an Org Data CSV in "
            "SharePoint Online or OneDrive for Business."
        ),
    )
    parser.add_argument(
        "--agent-credits-file",
        type=Path,
        help="Desktop-validation User-Level Credit Consumption CSV.",
    )
    parser.add_argument(
        "--topic-overrides-json",
        type=Path,
        help="Validated customer-topic-overrides.json to embed.",
    )
    parser.add_argument(
        "--conversation-topics-json",
        type=Path,
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--feedback-events-json",
        type=Path,
        help="Validated feedback-events.json to embed.",
    )
    args = parser.parse_args()

    if args.mode == "service-direct":
        if args.environment_url:
            raise ValueError(
                "--environment-url is not accepted in service-direct mode. Enter it "
                "when the generated PBIT opens in Power BI."
            )
        environment_url = ""
    else:
        if not args.environment_url:
            parser.error(
                "--environment-url is required unless --mode service-direct is used"
            )
        environment_url = normalize_environment_url(args.environment_url)
    if args.mode in SERVICE_MODES and (
        args.org_data_file or args.agent_credits_file
    ):
        raise ValueError(
            "--org-data-file and --agent-credits-file are Desktop-only. "
            "Use --mode desktop-validation or Fabric."
        )
    if args.mode == "service-direct" and (
        args.agent_registry_json
        or args.org_data_url
        or args.topic_overrides_json
        or args.conversation_topics_json
        or args.feedback_events_json
    ):
        raise ValueError(
            "Service-direct mode does not embed customer-specific inputs. Use "
            "service-refresh through the guided setup for those enhancements."
        )

    registry_rows, registry_json = serialize_registry(args.agent_registry_json)
    validation = {
        "environmentUrl": environment_url,
        "mode": args.mode,
        "organizationDataUrl": (
            normalize_org_data_url(args.org_data_url)
            if args.org_data_url
            else ""
        ),
        "registryAliases": len(registry_rows or []),
        "sources": [],
        "warnings": [],
    }
    if args.org_data_file:
        result = validate_org_data(args.org_data_file)
        validation["sources"].append(result)
        if result["warning"]:
            validation["warnings"].append(result["warning"])
    if args.agent_credits_file:
        result = validate_credits(args.agent_credits_file, registry_rows)
        validation["sources"].append(result)
        if result["warning"]:
            validation["warnings"].append(result["warning"])

    overrides_json = None
    if args.topic_overrides_json:
        overrides_json, result = validate_topic_overrides(
            args.topic_overrides_json
        )
        validation["sources"].append(result)

    conversation_topics_json = None
    if args.conversation_topics_json:
        conversation_topics_json, result = validate_conversation_topics(
            args.conversation_topics_json
        )
        validation["sources"].append(result)

    feedback_json = None
    if args.feedback_events_json:
        feedback_json, result = validate_feedback_events(
            args.feedback_events_json,
            registry_rows,
        )
        validation["sources"].append(result)

    build_package(
        args.input.resolve(),
        args.output.resolve(),
        environment_url,
        registry_json,
        mode=args.mode,
        org_data_file=args.org_data_file,
        org_data_url=args.org_data_url,
        credits_file=args.agent_credits_file,
        overrides_json=overrides_json,
        conversation_topics_json=conversation_topics_json,
        feedback_json=feedback_json,
    )
    validation["output"] = str(args.output.resolve())
    print(json.dumps(validation, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
