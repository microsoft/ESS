import argparse
import csv
import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path

from agent_registry import (
    active_agent_keys,
    load_registry,
    normalize_scope_mode,
    resolve_alias,
)


CANONICAL_COLUMNS = (
    "FeedbackEventId",
    "ConversationId",
    "AgentId",
    "AgentName",
    "Channel",
    "FeedbackSource",
    "FeedbackVerdict",
    "FeedbackComment",
    "SubmittedUtc",
    "UserId",
    "UserEmail",
    "Prompt",
    "Response",
    "App",
    "AppLanguage",
    "Platform",
    "SourceType",
    "AdditionalMetadata",
    "MatchStatus",
)
POSITIVE_VALUES = {
    "1", "true", "like", "liked", "positive", "helpful", "thumbsup", "thumbs up", "up", "yes", "good",
}
NEGATIVE_VALUES = {
    "0", "false", "dislike", "disliked", "negative", "unhelpful", "thumbsdown", "thumbs down", "down",
    "no", "bad",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Normalize Microsoft 365 Product Feedback and Copilot reaction exports into ESS feedback events."
    )
    parser.add_argument("--input", type=Path, action="append", required=True, help="Input CSV; repeat for multiple files.")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--audit", type=Path)
    parser.add_argument(
        "--agent-id",
        action="append",
        default=[],
        help=(
            "Allowed Microsoft 365 Product Feedback Agent ID. Repeat for multiple ESS agents. "
            "Required when a Product Feedback export is provided."
        ),
    )
    parser.add_argument(
        "--agent-registry",
        type=Path,
        help=(
            "Agent registry CSV or JSON. Product Feedback title IDs are filtered and "
            "rewritten to canonical AgentKey values."
        ),
    )
    parser.add_argument(
        "--scope-mode",
        default="ESS Safe",
        choices=("ESS Safe", "Selected Agents", "All Agents"),
        help="Registry scope applied when --agent-registry is used.",
    )
    return parser.parse_args()


def normalized_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.lower())


def row_get(row: dict, *aliases: str) -> str:
    lookup = {normalized_key(key): value for key, value in row.items()}
    for alias in aliases:
        value = lookup.get(normalized_key(alias))
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def parse_metadata(value: str) -> object:
    current: object = value
    for _ in range(2):
        if not isinstance(current, str) or not current.strip():
            break
        try:
            current = json.loads(current)
        except json.JSONDecodeError:
            break
    return current


def find_metadata_value(value: object, *keys: str) -> str:
    wanted = {normalized_key(key) for key in keys}
    if isinstance(value, dict):
        for key, item in value.items():
            if normalized_key(str(key)) in wanted and item not in (None, ""):
                if isinstance(item, (dict, list)):
                    continue
                return str(item)
        for item in value.values():
            found = find_metadata_value(item, *keys)
            if found:
                return found
    elif isinstance(value, list):
        for item in value:
            found = find_metadata_value(item, *keys)
            if found:
                return found
    return ""


def normalize_verdict(value: str) -> str:
    normalized = re.sub(r"[_-]+", " ", value.strip().lower())
    compact = normalized.replace(" ", "")
    if normalized in POSITIVE_VALUES or compact in {"copilotthumbsup", "thumbsup", "like"}:
        return "Thumbs Up"
    if normalized in NEGATIVE_VALUES or compact in {"copilotthumbsdown", "thumbsdown", "dislike"}:
        return "Thumbs Down"
    if "thumb" in normalized and "up" in normalized:
        return "Thumbs Up"
    if "thumb" in normalized and "down" in normalized:
        return "Thumbs Down"
    return ""


def infer_channel(*values: str) -> str:
    combined = " ".join(value for value in values if value).lower()
    if "teams" in combined:
        return "Microsoft Teams"
    if any(token in combined for token in ("m365", "microsoft 365", "copilot chat", "office copilot")):
        return "Microsoft 365 Copilot Chat"
    if "copilot studio" in combined or "custom" in combined or "power virtual agents" in combined:
        return "Copilot Studio"
    return "Unknown"


def is_product_feedback_export(fieldnames) -> bool:
    keys = {normalized_key(str(key)) for key in fieldnames if key is not None}
    return {
        "feedbackid",
        "feedbacktype",
        "microsoftresponsestatus",
    }.issubset(keys)


def parse_agent_ids(value: str) -> list[str]:
    parsed = parse_metadata(value)
    values = []
    if isinstance(parsed, list):
        values = [str(item).strip() for item in parsed if not isinstance(item, (dict, list))]
    elif isinstance(parsed, dict):
        values = [
            str(parsed[key]).strip()
            for key in ("agentId", "AgentId", "id", "Id")
            if key in parsed and not isinstance(parsed[key], (dict, list))
        ]
    elif isinstance(parsed, str):
        values = [item.strip() for item in re.split(r"[;,]", parsed)]

    unique = []
    seen = set()
    for item in values:
        if not item:
            continue
        key = item.casefold()
        if key not in seen:
            seen.add(key)
            unique.append(item)
    return unique


def raw_verdict(row: dict) -> str:
    return row_get(
        row,
        "Feedback Verdict",
        "Feedback Type",
        "Sentiment",
        "Reaction",
        "Reaction Type",
        "Vote",
        "Helpful",
        "Rating",
    )


def normalize_row(row: dict, input_name: str) -> dict | None:
    metadata_text = row_get(row, "Additional Metadata", "AdditionalMetadata", "Metadata")
    metadata = parse_metadata(metadata_text)
    verdict = normalize_verdict(raw_verdict(row))
    if not verdict:
        return None

    product_feedback = is_product_feedback_export(row.keys())
    conversation_id = row_get(row, "Conversation Id", "ConversationId", "Session Id", "SessionId")
    if not conversation_id:
        conversation_id = find_metadata_value(
            metadata,
            "conversationId",
            "conversation_id",
            "sessionId",
            "conversationTranscriptId",
        )
    agent_ids = parse_agent_ids(row_get(row, "Agent Id", "AgentId", "Bot Id", "BotId"))
    agent_id = (agent_ids[0] if agent_ids else "") or find_metadata_value(metadata, "essAgentId", "agentId", "botId")
    agent_name = row_get(row, "Agent Name", "AgentName") or find_metadata_value(
        metadata, "agentName", "aiAgentName", "Name"
    )
    platform = row_get(row, "Platform", "Channel", "Surface", "Ui Host", "UiHost")
    app = row_get(row, "App", "Application", "Product")
    source_type = row_get(row, "Source Type", "SourceType") or "External feedback export"
    copilot_type = find_metadata_value(metadata, "copilotType", "UiHost", "Type")
    channel = row_get(row, "Channel") or infer_channel(platform, app, source_type, copilot_type)
    submitted = row_get(
        row,
        "Date Submitted UTC",
        "DateSubmittedUTC",
        "Submitted UTC",
        "Timestamp",
        "Created Date",
        "CreatedDateTime",
    )
    user_id = row_get(row, "User Id", "UserId", "AAD Object Id", "AadObjectId")
    user_email = row_get(row, "User Email", "UserEmail", "UPN")
    event_id = row_get(row, "Feedback Id", "FeedbackId", "Feedback Event Id", "FeedbackEventId", "Reaction Id")
    if not event_id:
        event_id = hashlib.sha256(
            "\0".join(
                (
                    conversation_id,
                    agent_id,
                    verdict,
                    submitted,
                    user_id or user_email,
                    row_get(row, "Comment", "Feedback Comment", "FeedbackComment"),
                )
            ).encode("utf-8")
        ).hexdigest()

    return {
        "FeedbackEventId": event_id,
        "ConversationId": conversation_id,
        "AgentId": agent_id,
        "AgentName": agent_name,
        "Channel": channel,
        "FeedbackSource": row_get(row, "Feedback Source", "FeedbackSource")
        or ("Microsoft 365 Product Feedback" if product_feedback else input_name),
        "FeedbackVerdict": verdict,
        "FeedbackComment": row_get(row, "Comment", "Feedback Comment", "FeedbackComment"),
        "SubmittedUtc": submitted,
        "UserId": user_id,
        "UserEmail": user_email,
        "Prompt": row_get(row, "AI Context Prompt", "AIContextPrompt", "Prompt"),
        "Response": row_get(
            row,
            "AI Context Response Message",
            "AIContextResponse",
            "Response",
        ),
        "App": app,
        "AppLanguage": row_get(row, "App Language", "AppLanguage", "Locale"),
        "Platform": platform,
        "SourceType": source_type,
        "AdditionalMetadata": metadata_text,
        "MatchStatus": (
            "Pending template reconciliation"
            if conversation_id
            else "Agent ID match"
            if product_feedback and agent_id
            else "No conversation identifier"
        ),
    }


def normalize_files(
    paths: list[Path],
    allowed_agent_ids: set[str] | None = None,
    registry_rows: list[dict] | None = None,
    scope_mode: str = "ESS Safe",
) -> tuple[list[dict], dict]:
    events = []
    skipped = Counter()
    if registry_rows and allowed_agent_ids:
        raise ValueError("Use --agent-registry or --agent-id, not both")
    normalized_scope = normalize_scope_mode(scope_mode)
    registry_active_keys = (
        active_agent_keys(registry_rows, normalized_scope) if registry_rows else set()
    )
    allowed_lookup = {
        agent_id.strip().casefold(): agent_id.strip()
        for agent_id in (allowed_agent_ids or set())
        if agent_id.strip()
    }
    product_feedback_files = []
    discovered_product_agent_ids = Counter()
    product_feedback_reaction_rows = 0
    included_product_feedback_rows = 0
    excluded_outside_allowlist = 0
    excluded_without_agent_id = 0
    for path in paths:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            if not reader.fieldnames:
                raise ValueError(f"{path} has no CSV header")
            product_feedback = is_product_feedback_export(reader.fieldnames)
            if product_feedback:
                product_feedback_files.append(str(path))
            for row_number, row in enumerate(reader, start=2):
                if not normalize_verdict(raw_verdict(row)):
                    skipped[path.name] += 1
                    continue
                if product_feedback:
                    product_feedback_reaction_rows += 1
                    agent_ids = parse_agent_ids(row_get(row, "Agent Id", "AgentId"))
                    discovered_product_agent_ids.update(agent_ids)
                    if not agent_ids:
                        excluded_without_agent_id += 1
                        continue
                    matched_agent_ids = []
                    matched_registry_row = None
                    if registry_rows:
                        registry_matches = [
                            match
                            for agent_id in agent_ids
                            if (
                                match := resolve_alias(
                                    registry_rows,
                                    "M365Title",
                                    agent_id,
                                    registry_active_keys,
                                )
                            )
                        ]
                        matched_keys = {
                            match["AgentKey"] for match in registry_matches
                        }
                        if len(matched_keys) > 1:
                            raise ValueError(
                                "Product Feedback row maps to multiple active registry agents: "
                                f"{sorted(matched_keys)}"
                            )
                        if registry_matches:
                            matched_registry_row = registry_matches[0]
                            matched_agent_ids = [matched_registry_row["AgentKey"]]
                    else:
                        matched_agent_ids = [
                            allowed_lookup[agent_id.casefold()]
                            for agent_id in agent_ids
                            if agent_id.casefold() in allowed_lookup
                        ]
                    if not matched_agent_ids:
                        excluded_outside_allowlist += 1
                        continue
                    row = dict(row)
                    row["Agent ID"] = matched_agent_ids[0]
                    if matched_registry_row:
                        row["Agent Name"] = matched_registry_row["AgentLabel"]
                        metadata = parse_metadata(
                            row_get(row, "Additional Metadata", "AdditionalMetadata", "Metadata")
                        )
                        metadata_record = metadata if isinstance(metadata, dict) else {}
                        metadata_record = {
                            **metadata_record,
                            "sourceAgentIds": agent_ids,
                            "registryAgentKey": matched_registry_row["AgentKey"],
                        }
                        row["Additional Metadata"] = json.dumps(
                            metadata_record, ensure_ascii=False, separators=(",", ":")
                        )
                    included_product_feedback_rows += 1
                event = normalize_row(row, path.name)
                if event is None:
                    continue
                event["_InputFile"] = path.name
                event["_InputRow"] = row_number
                events.append(event)

    if product_feedback_reaction_rows and not allowed_lookup and not registry_rows:
        discovered = ", ".join(
            f"{agent_id} ({count})"
            for agent_id, count in sorted(discovered_product_agent_ids.items())
        ) or "none"
        raise ValueError(
            "Microsoft 365 Product Feedback input requires --agent-registry or at least one "
            "--agent-id so tenant-wide feedback is not misreported as ESS feedback. "
            f"Discovered Agent IDs: {discovered}. "
            f"Rows without Agent ID: {excluded_without_agent_id}."
        )
    if product_feedback_reaction_rows and not included_product_feedback_rows:
        discovered = ", ".join(
            f"{agent_id} ({count})"
            for agent_id, count in sorted(discovered_product_agent_ids.items())
        ) or "none"
        raise ValueError(
            "No Microsoft 365 Product Feedback rows matched the supplied --agent-id allowlist. "
            f"Discovered Agent IDs: {discovered}."
        )

    deduplicated = []
    seen = set()
    duplicate_count = 0
    for event in events:
        key = event["FeedbackEventId"].strip().lower()
        if key in seen:
            duplicate_count += 1
            continue
        seen.add(key)
        deduplicated.append({column: event[column] for column in CANONICAL_COLUMNS})

    audit = {
        "inputFiles": [str(path) for path in paths],
        "inputReactionRows": len(events),
        "outputFeedbackEvents": len(deduplicated),
        "duplicatesRemoved": duplicate_count,
        "rowsSkippedWithoutRecognizedVerdict": dict(sorted(skipped.items())),
        "productFeedbackFiles": product_feedback_files,
        "allowedAgentIds": sorted(allowed_lookup.values(), key=str.casefold),
        "agentRegistryKeys": sorted(registry_active_keys, key=str.casefold),
        "scopeMode": normalized_scope if registry_rows else None,
        "discoveredProductFeedbackAgentIds": dict(sorted(discovered_product_agent_ids.items())),
        "productFeedbackRowsIncludedByAllowlist": included_product_feedback_rows,
        "productFeedbackRowsExcludedOutsideAllowlist": excluded_outside_allowlist,
        "productFeedbackRowsExcludedWithoutAgentId": excluded_without_agent_id,
        "channelCounts": dict(sorted(Counter(row["Channel"] for row in deduplicated).items())),
        "verdictCounts": dict(sorted(Counter(row["FeedbackVerdict"] for row in deduplicated).items())),
        "sourceCounts": dict(sorted(Counter(row["FeedbackSource"] for row in deduplicated).items())),
    }
    return deduplicated, audit


def main() -> int:
    args = parse_args()
    registry_rows = load_registry(args.agent_registry) if args.agent_registry else None
    events, audit = normalize_files(
        args.input,
        set(args.agent_id),
        registry_rows,
        args.scope_mode,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CANONICAL_COLUMNS)
        writer.writeheader()
        writer.writerows(events)
    args.output.with_suffix(".json").write_text(
        json.dumps(events, ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    audit_path = args.audit or args.output.with_suffix(".audit.json")
    audit_path.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(audit, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, ValueError, csv.Error) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        sys.exit(2)
