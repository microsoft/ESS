import argparse
import csv
import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

from topic_classifier import CLASSIFIER_VERSION, RULE_COLUMNS, classify, language_prefix, load_rules, normalize


OVERRIDE_COLUMNS = (
    "Enabled",
    *RULE_COLUMNS,
    "Frequency",
    "ReviewStatus",
    "Notes",
)
PLACEHOLDER_TOPICS = {"", "No Topic Detected", "No User Intent", "Other / Uncategorized"}
TRUE_VALUES = {"1", "true", "yes", "y"}
STOPWORDS = {
    "en": {
        "about", "after", "again", "also", "been", "before", "being", "can", "could", "does", "from",
        "have", "help", "here", "how", "into", "just", "latest", "more", "need", "please", "show", "some",
        "tell", "that", "the", "their", "there", "these", "they", "thing", "this", "those", "update", "want",
        "what", "when", "where", "which", "with", "would", "you", "your",
    },
    "es": {
        "algo", "aqui", "como", "con", "cual", "cuando", "donde", "esta", "este", "esto", "favor", "hay",
        "informacion", "mas", "mostrar", "necesito", "para", "pero", "puede", "quiero", "sobre", "tengo",
        "una", "usted",
    },
}
PII_PATTERNS = {
    "email": re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE),
    "url": re.compile(r"\bhttps?://\S+\b", re.IGNORECASE),
    "guid": re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\b", re.IGNORECASE),
    "ipv4": re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"),
    "phone": re.compile(r"(?<!\w)(?:\+?\d[\d ().-]{7,}\d)(?!\w)"),
    "long_number": re.compile(r"\b\d{4,}\b"),
}


def parse_args() -> argparse.Namespace:
    default_taxonomy = Path(__file__).resolve().parents[1] / "taxonomy" / "topics-taxonomy.csv"
    parser = argparse.ArgumentParser(
        description="Analyze ESS transcripts locally and create privacy-reduced topic override candidates."
    )
    parser.add_argument("--input", type=Path, required=True, help="Raw transcript CSV or flat session CSV.")
    parser.add_argument("--taxonomy", type=Path, default=default_taxonomy)
    parser.add_argument("--overrides", type=Path, help="Previously reviewed customer-topic-overrides.csv.")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--input-format", choices=("auto", "transcript", "flat"), default="auto")
    parser.add_argument("--prompt-column")
    parser.add_argument("--locale-column")
    parser.add_argument("--id-column")
    parser.add_argument("--native-topic-column")
    parser.add_argument("--min-frequency", type=int, default=5)
    parser.add_argument("--max-candidates", type=int, default=50)
    parser.add_argument("--hash-salt", default="")
    parser.add_argument("--skip-invalid", action="store_true")
    return parser.parse_args()


def read_csv(path: Path) -> tuple[list[str], list[dict]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)
        return list(reader.fieldnames or []), rows


def resolve_column(
    fieldnames: list[str],
    explicit: str | None,
    candidates: tuple[str, ...],
    *,
    required: bool,
) -> str | None:
    lookup = {name.lower(): name for name in fieldnames}
    if explicit:
        column = lookup.get(explicit.lower())
        if not column:
            raise ValueError(f"Column not found: {explicit}")
        return column
    for candidate in candidates:
        if candidate.lower() in lookup:
            return lookup[candidate.lower()]
    if required:
        raise ValueError(f"None of the required columns were found: {', '.join(candidates)}")
    return None


def load_input(args: argparse.Namespace) -> tuple[list[dict], dict]:
    fieldnames, rows = read_csv(args.input)
    content_column = resolve_column(
        fieldnames,
        None,
        ("content", "msdyn_content", "Content"),
        required=False,
    )
    input_format = args.input_format
    if input_format == "auto":
        input_format = "transcript" if content_column else "flat"

    records = []
    invalid = []
    if input_format == "transcript":
        content_column = content_column or resolve_column(
            fieldnames, None, ("content", "msdyn_content", "Content"), required=True
        )
        id_column = resolve_column(
            fieldnames,
            args.id_column,
            ("conversationtranscriptid", "msdyn_conversationtranscriptid", "conversationid", "session_id"),
            required=False,
        )
        for row_number, row in enumerate(rows, start=2):
            try:
                prompt, locale, native_topic = parse_transcript(row.get(content_column, ""))
            except (json.JSONDecodeError, TypeError, ValueError) as error:
                invalid.append({"row": row_number, "error": str(error)})
                continue
            records.append(
                {
                    "id": row.get(id_column, "") if id_column else f"row-{row_number}",
                    "prompt": prompt,
                    "locale": locale,
                    "native_topic": native_topic,
                }
            )
    else:
        prompt_column = resolve_column(
            fieldnames,
            args.prompt_column,
            ("first_user_prompt", "FirstUserMessage", "Prompt", "prompt"),
            required=True,
        )
        locale_column = resolve_column(
            fieldnames,
            args.locale_column,
            ("locale", "Locale", "language", "Language"),
            required=False,
        )
        id_column = resolve_column(
            fieldnames,
            args.id_column,
            ("session_id", "conversation_id", "ConversationId", "conversationtranscriptid", "CaseId"),
            required=False,
        )
        native_column = resolve_column(
            fieldnames,
            args.native_topic_column,
            ("primary_topic_name", "PrimaryTopic", "NativeTopic", "native_topic"),
            required=False,
        )
        for row_number, row in enumerate(rows, start=2):
            records.append(
                {
                    "id": row.get(id_column, "") if id_column else f"row-{row_number}",
                    "prompt": row.get(prompt_column, ""),
                    "locale": row.get(locale_column, "") if locale_column else "",
                    "native_topic": row.get(native_column, "") if native_column else "",
                }
            )

    if invalid and not args.skip_invalid:
        first = invalid[0]
        raise ValueError(
            f"{len(invalid)} invalid transcript row(s); first failure is CSV row {first['row']}: {first['error']}. "
            "Fix the export or rerun with --skip-invalid."
        )
    return records, {"input_format": input_format, "input_rows": len(rows), "invalid_rows": invalid}


def parse_transcript(content: str) -> tuple[str, str, str]:
    payload = json.loads(content)
    activities = payload.get("activities", []) if isinstance(payload, dict) else []
    if not isinstance(activities, list):
        raise ValueError("content.activities is not a list")

    prompt = ""
    locale = str(payload.get("locale") or "") if isinstance(payload, dict) else ""
    native_topic = ""
    for activity in activities:
        if not isinstance(activity, dict):
            continue
        value = activity.get("value") if isinstance(activity.get("value"), dict) else {}
        if activity.get("name") == "pvaSetContext" and value.get("locale"):
            locale = str(value["locale"])
        elif not locale and activity.get("locale"):
            locale = str(activity["locale"])

        sender = activity.get("from") if isinstance(activity.get("from"), dict) else {}
        role = sender.get("role")
        if not prompt and activity.get("type") == "message" and role in {1, "1", "user", "User"}:
            prompt = str(activity.get("text") or "")

        if activity.get("valueType") == "IntentRecognition" or activity.get("name") == "IntentRecognition":
            title = value.get("intentTitle") or value.get("topicName")
            if title:
                native_topic = str(title)
    return prompt, locale, native_topic


def classify_records(records: list[dict], rules: list[dict], salt: str) -> tuple[list[dict], list[dict], list[dict]]:
    enrichments = []
    audits = []
    uncategorized = []
    for index, record in enumerate(records, start=1):
        native_topic = str(record.get("native_topic") or "").strip()
        if native_topic not in PLACEHOLDER_TOPICS:
            result = {
                "topic": native_topic,
                "vertical": "Native",
                "matched_terms": "",
                "score": "",
                "confidence": 1.0,
                "ambiguous": False,
                "language": language_prefix(record.get("locale")),
                "source": "native",
                "rule_source": "Native",
                "version": "Native",
            }
        else:
            result = classify(record.get("prompt"), record.get("locale"), rules)

        conversation_hash = hash_identifier(str(record.get("id") or f"row-{index}"), salt)
        enrichments.append(
            {
                "ConversationHash": conversation_hash,
                "Topic": result["topic"],
                "Vertical": result["vertical"],
                "Language": result["language"],
                "Confidence": result["confidence"],
                "Source": result["source"],
                "RuleSource": result["rule_source"],
                "ClassifierVersion": result["version"],
            }
        )
        audits.append(
            {
                "ConversationHash": conversation_hash,
                "NativeTopic": native_topic,
                "PredictedTopic": result["topic"],
                "PredictedVertical": result["vertical"],
                "Language": result["language"],
                "MatchedTerms": result["matched_terms"],
                "MatchScore": result["score"],
                "Confidence": result["confidence"],
                "Ambiguous": result["ambiguous"],
                "Source": result["source"],
                "RuleSource": result["rule_source"],
                "ClassifierVersion": result["version"],
            }
        )
        if result["source"] == "uncategorized" and not result["ambiguous"] and str(record.get("prompt") or "").strip():
            uncategorized.append(record)
    return enrichments, audits, uncategorized


def hash_identifier(value: str, salt: str) -> str:
    return hashlib.sha256((salt + "\0" + value).encode("utf-8")).hexdigest()


def redact_text(value: str, counts: Counter) -> str:
    redacted = value
    for name, pattern in PII_PATTERNS.items():
        redacted, replacements = pattern.subn(" ", redacted)
        counts[name] += replacements
    return redacted


def candidate_terms(
    records: list[dict],
    rules: list[dict],
    *,
    min_frequency: int,
    max_candidates: int,
) -> tuple[list[dict], Counter]:
    existing = {
        normalize(term)
        for rule in rules
        for term in str(rule["Keywords"]).split("|")
        if normalize(term)
    }
    frequencies: dict[str, Counter] = defaultdict(Counter)
    pii_counts = Counter()
    for record in records:
        language = language_prefix(record.get("locale")) or "*"
        redacted = redact_text(str(record.get("prompt") or ""), pii_counts)
        terms = extract_terms(redacted, language)
        for term in set(terms):
            if term not in existing:
                frequencies[language][term] += 1

    ranked = []
    for language, counts in frequencies.items():
        items = [(term, count) for term, count in counts.items() if count >= min_frequency]
        items.sort(key=lambda item: (-item[1], -len(item[0].split()), -len(item[0]), item[0]))
        selected: list[tuple[str, int]] = []
        for term, count in items:
            if any(term in chosen and count <= chosen_count for chosen, chosen_count in selected):
                continue
            selected.append((term, count))
        ranked.extend((language, term, count) for term, count in selected)

    ranked.sort(key=lambda item: (-item[2], item[0], -len(item[1].split()), item[1]))
    rows = []
    for index, (language, term, count) in enumerate(ranked[:max_candidates], start=1):
        rows.append(
            {
                "Enabled": "false",
                "Locale": language,
                "Vertical": "",
                "CanonicalTopic": "",
                "Keywords": term,
                "Exclusions": "",
                "Priority": "110",
                "Frequency": str(count),
                "ReviewStatus": "Candidate",
                "Notes": f"C{index:03d}: review locally; set Vertical, CanonicalTopic, and Enabled=true to approve.",
            }
        )
    return rows, pii_counts


def extract_terms(value: str, language: str) -> list[str]:
    if language == "zh":
        terms = []
        for chunk in re.findall(r"[\u3400-\u9fff]{2,}", value):
            for width in (4, 3, 2):
                terms.extend(chunk[index : index + width] for index in range(max(0, len(chunk) - width + 1)))
        return terms

    tokens = [
        token
        for token in re.findall(r"[^\W\d_]{3,}", value.lower(), flags=re.UNICODE)
        if token not in STOPWORDS.get(language, set()) and len(token) <= 40
    ]
    terms = list(tokens)
    for width in (3, 2):
        terms.extend(" ".join(tokens[index : index + width]) for index in range(max(0, len(tokens) - width + 1)))
    return terms


def read_override_rows(path: Path | None) -> list[dict]:
    if path is None:
        return []
    fieldnames, rows = read_csv(path)
    missing = set(OVERRIDE_COLUMNS) - set(fieldnames)
    if missing:
        raise ValueError(f"{path} is missing override columns: {sorted(missing)}")
    return [{column: row.get(column, "") for column in OVERRIDE_COLUMNS} for row in rows]


def approved_rules(path: Path | None) -> list[dict]:
    return load_rules(path, enabled_only=True, rule_source="Customer") if path else []


def write_csv(path: Path, rows: list[dict], fieldnames: tuple[str, ...]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    args = parse_args()
    if args.min_frequency < 2:
        raise ValueError("--min-frequency must be at least 2 to suppress unique or rare phrases")
    if args.max_candidates < 1:
        raise ValueError("--max-candidates must be positive")

    built_in_rules = load_rules(args.taxonomy)
    existing_override_rows = read_override_rows(args.overrides)
    customer_rules = approved_rules(args.overrides)
    records, input_stats = load_input(args)
    all_rules = customer_rules + built_in_rules
    enrichments, audits, uncategorized = classify_records(records, all_rules, args.hash_salt)
    candidates, pii_counts = candidate_terms(
        uncategorized,
        all_rules,
        min_frequency=args.min_frequency,
        max_candidates=args.max_candidates,
    )

    existing_keywords = {
        normalize(term)
        for row in existing_override_rows
        for term in row.get("Keywords", "").split("|")
        if normalize(term)
    }
    candidates = [row for row in candidates if normalize(row["Keywords"]) not in existing_keywords]
    override_rows = existing_override_rows + candidates

    output_dir = args.output_dir
    write_csv(output_dir / "topic-enrichment.csv", enrichments, tuple(enrichments[0].keys()) if enrichments else (
        "ConversationHash", "Topic", "Vertical", "Language", "Confidence", "Source", "RuleSource", "ClassifierVersion"
    ))
    write_csv(output_dir / "classification-audit.csv", audits, tuple(audits[0].keys()) if audits else (
        "ConversationHash", "NativeTopic", "PredictedTopic", "PredictedVertical", "Language", "MatchedTerms",
        "MatchScore", "Confidence", "Ambiguous", "Source", "RuleSource", "ClassifierVersion"
    ))
    write_csv(output_dir / "customer-topic-overrides.csv", override_rows, OVERRIDE_COLUMNS)

    public_rules = [
        {column: rule[column] for column in RULE_COLUMNS}
        for rule in customer_rules
    ]
    (output_dir / "customer-topic-overrides.json").write_text(
        json.dumps(public_rules, ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )

    source_counts = Counter(row["Source"] for row in enrichments)
    language_counts = Counter(row["Language"] or "unknown" for row in enrichments)
    report = {
        "classifierVersion": CLASSIFIER_VERSION,
        "inputFormat": input_stats["input_format"],
        "inputRows": input_stats["input_rows"],
        "processedRows": len(records),
        "invalidRowsSkipped": len(input_stats["invalid_rows"]),
        "classificationCounts": dict(sorted(source_counts.items())),
        "languageCounts": dict(sorted(language_counts.items())),
        "uncategorizedRowsAnalyzed": len(uncategorized),
        "minimumCandidateFrequency": args.min_frequency,
        "candidateRulesGenerated": len(candidates),
        "approvedCustomerRules": len(customer_rules),
        "piiPatternsRedactedBeforeCandidateExtraction": dict(sorted(pii_counts.items())),
        "rawTranscriptTextWritten": False,
        "warning": (
            "Candidate keywords are privacy-reduced, not guaranteed anonymous. They can still contain repeated "
            "business-sensitive terms. Review locally before sharing."
        ),
    }
    (output_dir / "privacy-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, ValueError, csv.Error) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        sys.exit(2)
