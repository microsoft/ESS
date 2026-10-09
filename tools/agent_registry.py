import argparse
import csv
import json
import re
import sys
from collections import Counter
from pathlib import Path


REGISTRY_COLUMNS = (
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
ALIAS_TYPES = {"TranscriptId", "TranscriptSchema", "CreditId", "M365Title"}
SCOPE_MODES = {"ESS Safe", "Selected Agents", "All Agents"}


def parse_bool(value, field_name: str) -> bool:
    if isinstance(value, bool):
        return value
    normalized = str(value or "").strip().casefold()
    if normalized in {"true", "1", "yes"}:
        return True
    if normalized in {"false", "0", "no"}:
        return False
    raise ValueError(f"{field_name} must be true or false, not {value!r}")


def normalize_scope_mode(value: str) -> str:
    lookup = {mode.casefold(): mode for mode in SCOPE_MODES}
    normalized = lookup.get(str(value or "").strip().casefold())
    if not normalized:
        raise ValueError(
            f"Agent scope mode must be one of: {', '.join(sorted(SCOPE_MODES))}"
        )
    return normalized


def normalize_alias(alias_type: str, value: str) -> str:
    normalized = str(value or "").strip()
    if alias_type in {"TranscriptId", "CreditId"}:
        normalized = normalized.strip("{}")
        if alias_type == "CreditId" and normalized.casefold().startswith("p_"):
            normalized = normalized[2:]
    return normalized.casefold()


def _read_rows(path: Path) -> list[dict]:
    if path.suffix.casefold() == ".json":
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
        if not isinstance(payload, list):
            raise ValueError("Agent registry JSON must contain an array")
        return [item for item in payload if isinstance(item, dict)]
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise ValueError(f"{path} has no header")
        missing = sorted(set(REGISTRY_COLUMNS) - set(reader.fieldnames))
        if missing:
            raise ValueError(f"Agent registry is missing columns: {missing}")
        return list(reader)


def validate_registry(rows: list[dict]) -> list[dict]:
    normalized_rows = []
    metadata_by_key = {}
    alias_assignments = {}
    for row_number, row in enumerate(rows, start=2):
        version = str(row.get("RegistryVersion") or "").strip()
        agent_key = str(row.get("AgentKey") or "").strip()
        agent_label = str(row.get("AgentLabel") or "").strip()
        alias_type = str(row.get("AliasType") or "").strip()
        alias_value = str(row.get("AliasValue") or "").strip()
        environment_key = str(row.get("EnvironmentKey") or "").strip()
        if version != "1":
            raise ValueError(f"Agent registry row {row_number} has unsupported version {version!r}")
        if not agent_key or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]*", agent_key):
            raise ValueError(f"Agent registry row {row_number} has invalid AgentKey")
        if not agent_label:
            raise ValueError(f"Agent registry row {row_number} has no AgentLabel")
        if alias_type not in ALIAS_TYPES:
            raise ValueError(
                f"Agent registry row {row_number} AliasType must be one of: "
                f"{', '.join(sorted(ALIAS_TYPES))}"
            )
        alias_normalized = normalize_alias(alias_type, alias_value)
        if not alias_normalized:
            raise ValueError(f"Agent registry row {row_number} has no AliasValue")

        normalized = {
            "RegistryVersion": "1",
            "AgentKey": agent_key,
            "AgentLabel": agent_label,
            "IsEss": parse_bool(row.get("IsEss"), "IsEss"),
            "Selected": parse_bool(row.get("Selected"), "Selected"),
            "Enabled": parse_bool(row.get("Enabled"), "Enabled"),
            "EnvironmentKey": environment_key,
            "EnvironmentName": str(row.get("EnvironmentName") or "").strip(),
            "EnvironmentUrl": str(row.get("EnvironmentUrl") or "").strip(),
            "AliasType": alias_type,
            "AliasValue": alias_value,
            "AliasValueNormalized": alias_normalized,
        }
        metadata = (
            normalized["AgentLabel"],
            normalized["IsEss"],
            normalized["Selected"],
            normalized["Enabled"],
        )
        previous_metadata = metadata_by_key.setdefault(agent_key.casefold(), metadata)
        if previous_metadata != metadata:
            raise ValueError(f"Agent registry has conflicting metadata for AgentKey {agent_key!r}")

        alias_key = (
            environment_key.casefold(),
            alias_type.casefold(),
            alias_normalized,
        )
        previous_agent = alias_assignments.setdefault(alias_key, agent_key)
        if previous_agent.casefold() != agent_key.casefold():
            raise ValueError(
                "Agent registry alias maps to multiple agents: "
                f"{environment_key or '*'} / {alias_type} / {alias_value}"
            )
        normalized_rows.append(normalized)

    return normalized_rows


def load_registry(path: Path) -> list[dict]:
    if not path.exists():
        raise ValueError(f"Agent registry not found: {path}")
    rows = validate_registry(_read_rows(path))
    if not rows:
        raise ValueError("Agent registry has no rows")
    return rows


def active_agent_keys(rows: list[dict], scope_mode: str) -> set[str]:
    mode = normalize_scope_mode(scope_mode)
    keys = set()
    for row in rows:
        if not row["Enabled"]:
            continue
        if mode == "ESS Safe" and not row["IsEss"]:
            continue
        if mode == "Selected Agents" and not row["Selected"]:
            continue
        keys.add(row["AgentKey"])
    if mode != "All Agents" and not keys:
        raise ValueError(f"Agent registry has no enabled agents for scope mode {mode!r}")
    return keys


def agent_metadata(rows: list[dict]) -> dict[str, dict]:
    metadata = {}
    for row in rows:
        metadata.setdefault(
            row["AgentKey"],
            {
                "AgentKey": row["AgentKey"],
                "AgentLabel": row["AgentLabel"],
                "IsEss": row["IsEss"],
                "Selected": row["Selected"],
                "Enabled": row["Enabled"],
            },
        )
    return metadata


def resolve_alias(
    rows: list[dict],
    alias_type: str,
    alias_value: str,
    active_keys: set[str] | None = None,
    environment_key: str = "",
) -> dict | None:
    if alias_type not in ALIAS_TYPES:
        raise ValueError(f"Unsupported agent alias type: {alias_type}")
    normalized = normalize_alias(alias_type, alias_value)
    environment = str(environment_key or "").strip().casefold()
    candidates = [
        row
        for row in rows
        if row["Enabled"]
        and row["AliasType"] == alias_type
        and row["AliasValueNormalized"] == normalized
        and (not active_keys or row["AgentKey"] in active_keys)
    ]
    if environment:
        exact = [
            row for row in candidates if row["EnvironmentKey"].casefold() == environment
        ]
        candidates = exact or [
            row for row in candidates if not row["EnvironmentKey"]
        ]
    agent_keys = {row["AgentKey"] for row in candidates}
    if len(agent_keys) > 1:
        raise ValueError(
            f"Agent alias is ambiguous without an environment: {alias_type} / {alias_value}"
        )
    return candidates[0] if candidates else None


def registry_audit(rows: list[dict], scope_mode: str) -> dict:
    active = active_agent_keys(rows, scope_mode)
    return {
        "registryRows": len(rows),
        "agents": len({row["AgentKey"] for row in rows}),
        "activeAgents": sorted(active, key=str.casefold),
        "scopeMode": normalize_scope_mode(scope_mode),
        "aliasCounts": dict(sorted(Counter(row["AliasType"] for row in rows).items())),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate an ESS agent registry and produce Formula Firewall-safe JSON."
    )
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument("--scope-mode", default="ESS Safe")
    parser.add_argument(
        "--environment-key",
        help=(
            "Optional direct-template environment scope. Includes rows for this EnvironmentKey "
            "plus environment-neutral rows."
        ),
    )
    args = parser.parse_args()

    rows = load_registry(args.input)
    if args.environment_key:
        environment = args.environment_key.strip().casefold()
        rows = [
            row
            for row in rows
            if not row["EnvironmentKey"]
            or row["EnvironmentKey"].casefold() == environment
        ]
        if not rows:
            raise ValueError(
                f"Agent registry has no rows for EnvironmentKey {args.environment_key!r}"
            )
    audit = registry_audit(rows, args.scope_mode)
    output_rows = [{column: row[column] for column in REGISTRY_COLUMNS} for row in rows]
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(
        json.dumps(output_rows, ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(audit, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, ValueError, csv.Error, json.JSONDecodeError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        sys.exit(2)
