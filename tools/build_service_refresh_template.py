#!/usr/bin/env python3
"""Build validated Desktop or Service-refresh Dataverse PBIT packages."""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import re
import tempfile
import uuid
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import urlparse

from agent_registry import load_registry


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
FEEDBACK_PARAMETER = "Feedback Events JSON (optional)"
DISABLED_FILE_PARAMETERS = (
    ORG_DATA_PARAMETER,
    CREDITS_PARAMETER,
)
BUILD_MODES = ("service-refresh", "desktop-validation")
TOPIC_RULE_COLUMNS = (
    "Locale",
    "Vertical",
    "CanonicalTopic",
    "Keywords",
    "Exclusions",
    "Priority",
)
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
STATIC_DESCRIPTION = (
    "Required. This Service-refresh build is fixed to {url}. To target another "
    "environment, rebuild the PBIT with tools/build_service_refresh_template.py."
)
DESKTOP_DESCRIPTION = (
    "Required. Dataverse Environment URL used by this Desktop validation build. "
    "The connector remains parameterized; use the Service-refresh mode before publishing."
)
CONTENT_TYPES_NAMESPACE = (
    "http://schemas.openxmlformats.org/package/2006/content-types"
)
RELATIONSHIPS_NAMESPACE = (
    "http://schemas.openxmlformats.org/package/2006/relationships"
)


def m_text(value: str) -> str:
    return f'"{value.replace(chr(34), chr(34) * 2)}"'


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


def validate_topic_overrides(path: Path) -> tuple[str, dict]:
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
        try:
            int(row["Priority"])
        except (TypeError, ValueError) as error:
            raise ValueError(
                f"Customer Topic Overrides rule {row_number} has an invalid Priority."
            ) from error
    return (
        json.dumps(rows, ensure_ascii=False, separators=(",", ":")),
        {"contract": "Customer Topic Overrides", "enabledRules": len(rows)},
    )


def validate_feedback_events(
    path: Path,
    registry_rows: list[dict] | None,
) -> tuple[str, dict]:
    if not registry_rows:
        raise ValueError(
            "Feedback Events require --agent-registry-json so external AgentId "
            "values can be mapped safely."
        )
    rows = load_json_array(path, "Feedback Events")
    for row_number, row in enumerate(rows, start=1):
        missing = sorted(FEEDBACK_REQUIRED_COLUMNS - set(row))
        if missing:
            raise ValueError(
                f"Feedback Events row {row_number} is missing: {missing}"
            )
    active_keys = {
        row["AgentKey"]
        for row in registry_rows
        if row["Enabled"]
    }
    unknown = sorted(
        {
            str(row.get("AgentId") or "").strip()
            for row in rows
            if str(row.get("AgentId") or "").strip() not in active_keys
        }
    )
    if unknown:
        raise ValueError(
            "Feedback Events contains AgentId values that are not enabled registry "
            f"AgentKey values: {unknown}"
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
    environment_url: str,
) -> dict[str, str]:
    tables = {
        table["name"]: table
        for table in schema["model"]["tables"]
    }
    query_expressions = {}

    agent_table = tables["Agent Performance"]
    partition = agent_table["partitions"][0]
    agent_expression = expression_text(partition["source"]["expression"])
    agent_expression = replace_once(
        agent_expression,
        (
            '    _EnvUrl = (let _raw = '
            '#"Dataverse Environment URL (required)" in if _raw = null '
            'then null else Text.Trim(Text.From(_raw), '
            '{" ", "#(tab)", "#(cr)", "#(lf)", """", "\'"})),'
        ),
        f"    _EnvUrl = {m_text(environment_url)},",
        "Dataverse environment constant",
    )
    source_old = 'Source       = Cds.Entities(_EnvUrl, null),'
    if source_old not in agent_expression:
        source_old = (
            'Source       = Cds.Entities('
            '#"Dataverse Environment URL (required)", null),'
        )
    agent_expression = replace_once(
        agent_expression,
        source_old,
        f"Source       = Cds.Entities({m_text(environment_url)}, null),",
        "Dataverse connector constant",
    )
    partition["source"]["expression"] = store_expression(
        partition["source"]["expression"],
        agent_expression,
    )
    query_expressions["Agent Performance"] = agent_expression

    for table_name in ("Chat + Agent Org Data", "AgentCredits"):
        table = tables[table_name]
        expression = empty_partition_expression(table)
        partition = table["partitions"][0]
        partition["source"]["expression"] = store_expression(
            partition["source"]["expression"],
            expression,
        )
        query_expressions[table_name] = expression

    return query_expressions


def update_parameter_metadata(
    schema: dict,
    environment_url: str,
    mode: str,
    registry_json: str | None,
    org_data_file: Path | None = None,
    credits_file: Path | None = None,
    overrides_json: str | None = None,
    feedback_json: str | None = None,
) -> None:
    parameter_expression = (
        f"{m_text(environment_url)} meta "
        '[IsParameterQuery=true, Type="Text", IsParameterQueryRequired=true]'
    )
    description = (
        STATIC_DESCRIPTION.format(url=environment_url)
        if mode == "service-refresh"
        else DESKTOP_DESCRIPTION
    )

    schema_expressions = {
        item["name"]: item
        for item in schema["model"]["expressions"]
    }
    environment = schema_expressions[ENVIRONMENT_PARAMETER]
    environment["expression"] = parameter_expression
    environment["description"] = description
    for annotation in environment.get("annotations", []):
        if annotation["name"] == "PBI_ResultType":
            annotation["value"] = "Text"
    if registry_json is not None:
        registry_expression = m_text(registry_json)
        registry = schema_expressions[REGISTRY_EXPRESSION]
        registry["expression"] = registry_expression
        registry["description"] = (
            "Embedded advanced agent mapping generated from a validated "
            "agent-registry.json file."
        )

    parameter_values = {
        ORG_DATA_PARAMETER: (
            str(org_data_file.resolve()) if org_data_file is not None else None
        ),
        CREDITS_PARAMETER: (
            str(credits_file.resolve()) if credits_file is not None else None
        ),
        OVERRIDES_PARAMETER: overrides_json,
        FEEDBACK_PARAMETER: feedback_json,
    }
    for name, value in parameter_values.items():
        if value is None or name not in schema_expressions:
            continue
        schema_expressions[name]["expression"] = (
            f"{m_text(value)} meta "
            '[IsParameterQuery=true, Type="Text", IsParameterQueryRequired=false]'
        )

    if mode == "service-refresh":
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
    credits_file: Path | None = None,
    overrides_json: str | None = None,
    feedback_json: str | None = None,
) -> None:
    if mode not in BUILD_MODES:
        raise ValueError(f"Build mode must be one of: {', '.join(BUILD_MODES)}")
    if mode == "service-refresh" and (org_data_file or credits_file):
        raise ValueError(
            "Org Data and Agent Credits files are not supported in Service-refresh "
            "mode. Use --mode desktop-validation or Fabric."
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
    changes = json.loads(
        payloads["UnappliedChanges"].decode("utf-16-le")
    )
    materialize_unapplied_queries(schema, changes)
    schema["name"] = str(uuid.uuid4())
    if mode == "service-refresh":
        build_query_expressions(
            schema,
            environment_url,
        )
    update_parameter_metadata(
        schema,
        environment_url,
        mode,
        registry_json,
        org_data_file,
        credits_file,
        overrides_json,
        feedback_json,
    )

    payloads["DataModelSchema"] = json.dumps(
        schema,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-16-le")
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
    parser.add_argument("--environment-url", required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument(
        "--mode",
        choices=BUILD_MODES,
        default="service-refresh",
        help="service-refresh removes local file sources; desktop-validation preserves them.",
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
        "--feedback-events-json",
        type=Path,
        help="Validated feedback-events.json to embed.",
    )
    args = parser.parse_args()

    environment_url = normalize_environment_url(args.environment_url)
    if args.mode == "service-refresh" and (
        args.org_data_file or args.agent_credits_file
    ):
        raise ValueError(
            "--org-data-file and --agent-credits-file are Desktop-only. "
            "Use --mode desktop-validation or Fabric."
        )

    registry_rows, registry_json = serialize_registry(args.agent_registry_json)
    validation = {
        "environmentUrl": environment_url,
        "mode": args.mode,
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
        credits_file=args.agent_credits_file,
        overrides_json=overrides_json,
        feedback_json=feedback_json,
    )
    validation["output"] = str(args.output.resolve())
    print(json.dumps(validation, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
