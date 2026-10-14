#!/usr/bin/env python3
"""Build an environment-specific Dataverse PBIT for Power BI Service refresh."""

from __future__ import annotations

import argparse
import json
import os
import re
import tempfile
import uuid
import zipfile
from pathlib import Path
from urllib.parse import urlparse


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
DISABLED_FILE_PARAMETERS = (
    "Org Data File",
    "Agent Credits  (optional)",
)
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


def expression_text(value: object) -> str:
    if isinstance(value, list):
        return "\n".join(value)
    if isinstance(value, str):
        return value
    raise TypeError("Unexpected Power Query expression type")


def store_expression(original: object, value: str) -> object:
    return value.split("\n") if isinstance(original, list) else value


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
    changes: dict,
    environment_url: str,
) -> None:
    parameter_expression = (
        f"{m_text(environment_url)} meta "
        '[IsParameterQuery=true, Type="Text", IsParameterQueryRequired=true]'
    )
    description = STATIC_DESCRIPTION.format(url=environment_url)

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
    queries = {
        query["name"]: query
        for query in changes["queries"]
    }
    environment_query = queries[ENVIRONMENT_PARAMETER]
    environment_query["text"] = [parameter_expression]
    environment_query["description"] = description
    environment_query["resultType"] = "Text"

    schema["model"]["expressions"] = [
        item
        for item in schema["model"]["expressions"]
        if item["name"] not in DISABLED_FILE_PARAMETERS
    ]
    changes["queries"] = [
        query
        for query in changes["queries"]
        if query["name"] not in DISABLED_FILE_PARAMETERS
    ]


def update_unapplied_changes(
    changes: dict,
    query_expressions: dict[str, str],
) -> None:
    queries = {
        query["name"]: query
        for query in changes["queries"]
    }
    for name, expression in query_expressions.items():
        query = queries[name]
        query["text"] = store_expression(query["text"], expression)
        loaded_text = query.get("lastLoadedAsTableFormulaText")
        if loaded_text:
            loaded = json.loads(loaded_text)
            loaded["RootFormulaText"] = expression.replace("\n", "\r\n")
            query["lastLoadedAsTableFormulaText"] = json.dumps(
                loaded,
                ensure_ascii=False,
                separators=(",", ":"),
            )


def build_package(
    input_path: Path,
    output_path: Path,
    environment_url: str,
) -> None:
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
    schema["name"] = str(uuid.uuid4())
    query_expressions = build_query_expressions(
        schema,
        environment_url,
    )
    update_unapplied_changes(changes, query_expressions)
    update_parameter_metadata(schema, changes, environment_url)

    payloads["DataModelSchema"] = json.dumps(
        schema,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-16-le")
    payloads["UnappliedChanges"] = json.dumps(
        changes,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-16-le")

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
            "Build a Dataverse PBIT with a static environment endpoint so "
            "Power BI Service can schedule refresh."
        )
    )
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--environment-url", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    environment_url = normalize_environment_url(args.environment_url)
    build_package(
        args.input.resolve(),
        args.output.resolve(),
        environment_url,
    )
    print(f"Built Service-refresh template: {args.output.resolve()}")


if __name__ == "__main__":
    main()
