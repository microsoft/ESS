import argparse
import csv
import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

from topic_classifier import (
    CLASSIFIER_VERSION,
    RULE_COLUMNS,
    classify,
    contains_term,
    language_prefix,
    load_rules,
    normalize,
)


TUNER_VERSION = "ESS-TOPIC-TUNER-2026.12"
OVERRIDE_COLUMNS = (
    "Enabled",
    *RULE_COLUMNS,
    "Frequency",
    "ReviewStatus",
    "Notes",
)
LEARNING_AUDIT_COLUMNS = (
    "Locale",
    "NativeTopic",
    "AssignedVertical",
    "SupportingConversations",
    "MatchedConversations",
    "FalsePositiveConversations",
    "EstimatedPrecision",
    "EstimatedCoverage",
    "ValidationMethod",
    "ValidationConversations",
    "ValidationMatchedConversations",
    "ValidationFalsePositiveConversations",
    "ValidationPrecision",
    "ValidationCoverage",
    "ValidationStatus",
    "CandidateKeywords",
    "AutoEnabled",
    "Status",
)
PLACEHOLDER_TOPICS = {"", "No Topic Detected", "No User Intent", "Other / Uncategorized"}
PLACEHOLDER_TOPIC_KEYS = {normalize(topic) for topic in PLACEHOLDER_TOPICS}
NON_LEARNABLE_NATIVE_TOPICS = {
    "conversation start",
    "conversational boosting",
    "end of conversation",
    "escalate",
    "fallback",
    "goodbye",
    "greeting",
    "multiple topics matched",
    "on error",
    "reset conversation",
    "start over",
    "unknown intent",
    "unknownintent",
}
TRUE_VALUES = {"1", "true", "yes", "y"}
STOPWORDS = {
    "en": {
        "about", "after", "again", "also", "been", "before", "being", "book", "can", "change", "could",
        "does", "find", "for", "from", "get", "have", "help", "here", "how", "into", "issue", "just",
        "latest", "looks", "make", "many", "month", "more", "need", "new", "next", "open", "please",
        "problem", "process",
        "question", "replace", "request", "requests", "show", "some", "start", "status", "submit", "tell",
        "that", "the", "their", "there", "these", "they", "thing", "this", "those", "today", "tomorrow",
        "update", "want", "week", "what", "when", "where", "which", "with", "would", "wrong", "you",
        "your", "reset",
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
        description=(
            "Analyze ESS transcripts locally, learn high-precision customer rules from native topic evidence, "
            "and create privacy-reduced review candidates for remaining gaps."
        )
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
    parser.add_argument(
        "--min-native-topic-precision",
        type=float,
        default=0.90,
        help="Minimum observed cross-topic precision required to auto-enable a native-topic rule.",
    )
    parser.add_argument(
        "--max-native-keywords",
        type=int,
        default=8,
        help="Maximum privacy-reduced keywords learned for each native topic and language.",
    )
    parser.add_argument(
        "--validation-folds",
        type=int,
        default=5,
        help=(
            "Deterministic conversation-level folds used to validate learned rules "
            "on conversations excluded from each fold's training data."
        ),
    )
    parser.add_argument(
        "--min-validation-conversations",
        type=int,
        default=3,
        help="Minimum correctly matched out-of-fold conversations required to auto-enable a rule.",
    )
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
                prompt, locale, native_topic, training_examples = parse_transcript_details(
                    row.get(content_column, "")
                )
            except (json.JSONDecodeError, TypeError, ValueError) as error:
                invalid.append({"row": row_number, "error": str(error)})
                continue
            record_id = (
                str(row.get(id_column) or f"row-{row_number}")
                if id_column
                else f"row-{row_number}"
            )
            for example in training_examples:
                example["record_id"] = record_id
            records.append(
                {
                    "id": record_id,
                    "prompt": prompt,
                    "locale": locale,
                    "native_topic": native_topic,
                    "training_examples": training_examples,
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
            record_id = (
                str(row.get(id_column) or f"row-{row_number}")
                if id_column
                else f"row-{row_number}"
            )
            prompt = row.get(prompt_column, "")
            locale = row.get(locale_column, "") if locale_column else ""
            native_topic = row.get(native_column, "") if native_column else ""
            records.append(
                {
                    "id": record_id,
                    "prompt": prompt,
                    "locale": locale,
                    "native_topic": native_topic,
                    "training_examples": (
                        [
                            {
                                "record_id": record_id,
                                "prompt": prompt,
                                "locale": locale,
                                "native_topic": native_topic,
                            }
                        ]
                        if is_learnable_native_topic(native_topic)
                        else []
                    ),
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
    prompt, locale, native_topic, _ = parse_transcript_details(content)
    return prompt, locale, native_topic


def parse_transcript_details(content: str) -> tuple[str, str, str, list[dict]]:
    payload = json.loads(content)
    activities = payload.get("activities", []) if isinstance(payload, dict) else []
    if not isinstance(activities, list):
        raise ValueError("content.activities is not a list")

    prompt = ""
    locale = str(payload.get("locale") or "") if isinstance(payload, dict) else ""
    native_topics = []
    training_examples = []
    pending_prompt = ""
    pending_example_index = None
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
        if activity.get("type") == "message" and role in {1, "1", "user", "User"}:
            pending_prompt = str(activity.get("text") or "").strip()
            pending_example_index = None
            if not prompt:
                prompt = pending_prompt

        if activity.get("valueType") == "IntentRecognition" or activity.get("name") == "IntentRecognition":
            title = value.get("intentTitle") or value.get("topicName")
            if title:
                topic = str(title).strip()
                native_topics.append(topic)
                if pending_prompt:
                    example = {
                        "prompt": pending_prompt,
                        "locale": locale,
                        "native_topic": topic,
                    }
                    if pending_example_index is None:
                        training_examples.append(example)
                        pending_example_index = len(training_examples) - 1
                    elif (
                        not is_learnable_native_topic(
                            training_examples[pending_example_index]["native_topic"]
                        )
                        and is_learnable_native_topic(topic)
                    ):
                        training_examples[pending_example_index] = example
    native_topic = next((topic for topic in native_topics if is_usable_native_topic(topic)), "")
    return prompt, locale, native_topic, training_examples


def is_usable_native_topic(value: str | None) -> bool:
    topic = str(value or "").strip()
    return bool(topic) and normalize(topic) not in PLACEHOLDER_TOPIC_KEYS


def is_learnable_native_topic(value: str | None) -> bool:
    return is_usable_native_topic(value) and normalize(value) not in NON_LEARNABLE_NATIVE_TOPICS


def classify_records(records: list[dict], rules: list[dict], salt: str) -> tuple[list[dict], list[dict], list[dict]]:
    enrichments = []
    audits = []
    uncategorized = []
    for index, record in enumerate(records, start=1):
        native_topic = str(record.get("native_topic") or "").strip()
        if is_usable_native_topic(native_topic):
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
        for token in re.findall(r"[^\W\d_]+", value.lower(), flags=re.UNICODE)
        if len(token) <= 40
    ]
    stopwords = STOPWORDS.get(language, set())

    def meaningful(token: str) -> bool:
        return len(token) >= 3 and token not in stopwords

    terms = [token for token in tokens if meaningful(token)]
    for width in (3, 2):
        for index in range(max(0, len(tokens) - width + 1)):
            phrase_tokens = tokens[index : index + width]
            if meaningful(phrase_tokens[0]) and meaningful(phrase_tokens[-1]):
                terms.append(" ".join(phrase_tokens))
    return terms


def build_term_indexes(
    examples: list[dict],
) -> tuple[
    dict[tuple[str, str], set[str]],
    dict[tuple[str, str], dict[str, set[str]]],
]:
    topic_conversations: dict[tuple[str, str], set[str]] = defaultdict(set)
    term_topic_conversations: dict[
        tuple[str, str], dict[str, set[str]]
    ] = defaultdict(lambda: defaultdict(set))
    for example in examples:
        key = (example["language"], example["native_topic"])
        topic_conversations[key].add(example["record_id"])
        for term in example["terms"]:
            term_topic_conversations[
                (example["language"], term)
            ][example["native_topic"]].add(example["record_id"])
    return topic_conversations, term_topic_conversations


def select_topic_terms(
    language: str,
    topic: str,
    supporting_ids: set[str],
    term_topic_conversations: dict[
        tuple[str, str], dict[str, set[str]]
    ],
    *,
    min_frequency: int,
    min_precision: float,
    max_keywords: int,
) -> tuple[list[tuple[str, int, int, float]], list[tuple[str, int, int, float]]]:
    candidates = []
    for (term_language, term), topic_counts in term_topic_conversations.items():
        if term_language != language:
            continue
        support = len(topic_counts.get(topic, set()))
        if support < min_frequency:
            continue
        false_positives = sum(
            len(record_ids)
            for other_topic, record_ids in topic_counts.items()
            if other_topic != topic
        )
        precision = support / (support + false_positives)
        candidates.append((term, support, false_positives, precision))

    candidates.sort(
        key=lambda item: (
            -item[3],
            -item[1],
            _term_specificity_rank(item[0]),
            -len(item[0]),
            item[0],
        )
    )
    high_precision = [
        item
        for item in candidates
        if item[3] >= min_precision
        and _is_auto_term_specific(item[0], item[1], len(supporting_ids))
    ]
    return (
        _select_distinct_terms(high_precision, max_keywords),
        candidates,
    )


def evaluate_topic_terms(
    examples: list[dict],
    language: str,
    topic: str,
    selected_terms: list[str],
) -> tuple[set[str], set[tuple[str, str]], set[str]]:
    target_ids = {
        example["record_id"]
        for example in examples
        if example["language"] == language
        and example["native_topic"] == topic
    }
    matched_target = set()
    false_positive_pairs = set()
    if not selected_terms:
        return matched_target, false_positive_pairs, target_ids
    for example in examples:
        if example["language"] != language:
            continue
        if not any(
            contains_term(example["normalized_text"], term, language)
            for term in selected_terms
        ):
            continue
        pair = (example["native_topic"], example["record_id"])
        if example["native_topic"] == topic:
            matched_target.add(example["record_id"])
        else:
            false_positive_pairs.add(pair)
    return matched_target, false_positive_pairs, target_ids


def assign_validation_folds(examples: list[dict], folds: int) -> dict[str, int]:
    signatures_by_record = defaultdict(set)
    for example in examples:
        signatures_by_record[example["record_id"]].add(
            (example["language"], example["native_topic"])
        )

    records_by_signature = defaultdict(list)
    for record_id, signature in signatures_by_record.items():
        records_by_signature[tuple(sorted(signature))].append(record_id)

    fold_by_record = {}
    for signature, record_ids in records_by_signature.items():
        signature_text = "\0".join(
            f"{language}\0{topic}" for language, topic in signature
        )
        offset = int(
            hash_identifier(signature_text, "validation-fold-offset")[:16],
            16,
        ) % folds
        ordered_ids = sorted(
            record_ids,
            key=lambda value: hash_identifier(
                value,
                "validation-fold-record",
            ),
        )
        for index, record_id in enumerate(ordered_ids):
            fold_by_record[record_id] = (offset + index) % folds
    return fold_by_record


def cross_validate_topic_rule(
    examples: list[dict],
    language: str,
    topic: str,
    *,
    folds: int,
    min_frequency: int,
    min_precision: float,
    max_keywords: int,
) -> dict:
    fold_by_record = assign_validation_folds(examples, folds)
    fold_min_frequency = max(
        2,
        (min_frequency * (folds - 1) + folds - 1) // folds,
    )
    matched_target = set()
    false_positive_pairs = set()
    validation_target = set()
    for fold in range(folds):
        training = [
            example
            for example in examples
            if fold_by_record[example["record_id"]] != fold
        ]
        validation = [
            example
            for example in examples
            if fold_by_record[example["record_id"]] == fold
        ]
        topic_conversations, term_topic_conversations = build_term_indexes(
            training
        )
        supporting_ids = topic_conversations.get((language, topic), set())
        selected, _ = select_topic_terms(
            language,
            topic,
            supporting_ids,
            term_topic_conversations,
            min_frequency=fold_min_frequency,
            min_precision=min_precision,
            max_keywords=max_keywords,
        )
        fold_matched, fold_false_positives, fold_targets = (
            evaluate_topic_terms(
                validation,
                language,
                topic,
                [item[0] for item in selected],
            )
        )
        matched_target.update(fold_matched)
        false_positive_pairs.update(fold_false_positives)
        validation_target.update(fold_targets)

    false_positive_count = len(false_positive_pairs)
    precision = (
        len(matched_target) / (len(matched_target) + false_positive_count)
        if matched_target or false_positive_count
        else 0.0
    )
    coverage = (
        len(matched_target) / len(validation_target)
        if validation_target
        else 0.0
    )
    return {
        "conversations": len(validation_target),
        "matched": len(matched_target),
        "false_positives": false_positive_count,
        "precision": precision,
        "coverage": coverage,
    }


def learn_native_topic_rules(
    records: list[dict],
    built_in_rules: list[dict],
    existing_override_rows: list[dict],
    *,
    min_frequency: int,
    min_precision: float,
    max_keywords: int,
    validation_folds: int,
    min_validation_conversations: int,
) -> tuple[list[dict], list[dict], list[dict], Counter]:
    pii_counts = Counter()
    examples = []
    for record in records:
        for example in record.get("training_examples", []):
            topic = str(example.get("native_topic") or "").strip()
            if not is_learnable_native_topic(topic):
                continue
            language = language_prefix(example.get("locale")) or "*"
            redacted = redact_text(str(example.get("prompt") or ""), pii_counts)
            terms = set(extract_terms(redacted, language))
            if not terms:
                continue
            examples.append(
                {
                    "record_id": str(example.get("record_id") or record.get("id") or ""),
                    "prompt": str(example.get("prompt") or ""),
                    "locale": str(example.get("locale") or ""),
                    "language": language,
                    "native_topic": topic,
                    "normalized_text": normalize(redacted),
                    "terms": terms,
                }
            )

    topic_conversations, term_topic_conversations = build_term_indexes(
        examples
    )

    existing_topic_keys = {
        (
            str(row.get("Locale") or "*").strip().lower() or "*",
            normalize(row.get("CanonicalTopic")),
        )
        for row in existing_override_rows
        if str(row.get("CanonicalTopic") or "").strip()
    }
    generated_rows = []
    auto_rows = []
    audit_rows = []
    for (language, topic), supporting_ids in sorted(topic_conversations.items()):
        topic_key = (language, normalize(topic))
        selected, candidates = select_topic_terms(
            language,
            topic,
            supporting_ids,
            term_topic_conversations,
            min_frequency=min_frequency,
            min_precision=min_precision,
            max_keywords=max_keywords,
        )
        review_terms = selected or _select_distinct_terms(candidates, max_keywords)
        selected_terms = [item[0] for item in review_terms]

        matched_target, false_positive_pairs, _ = evaluate_topic_terms(
            examples,
            language,
            topic,
            selected_terms,
        )

        false_positive_count = len(false_positive_pairs)
        observed_precision = (
            len(matched_target) / (len(matched_target) + false_positive_count)
            if matched_target or false_positive_count
            else 0.0
        )
        coverage = len(matched_target) / len(supporting_ids) if supporting_ids else 0.0
        validation = cross_validate_topic_rule(
            examples,
            language,
            topic,
            folds=validation_folds,
            min_frequency=min_frequency,
            min_precision=min_precision,
            max_keywords=max_keywords,
        )
        if validation["matched"] < min_validation_conversations:
            validation_status = "InsufficientMatches"
        elif validation["precision"] < min_precision:
            validation_status = "LowPrecision"
        else:
            validation_status = "Passed"
        vertical = infer_vertical(
            [
                example
                for example in examples
                if example["language"] == language and example["native_topic"] == topic
            ],
            built_in_rules,
        )

        if topic_key in existing_topic_keys:
            status = "ExistingOverride"
            auto_enabled = False
        elif (
            selected
            and len(matched_target) >= min_frequency
            and observed_precision >= min_precision
            and validation_status == "Passed"
        ):
            status = "AutoValidated"
            auto_enabled = True
        elif candidates:
            status = "NeedsReview"
            auto_enabled = False
        else:
            status = "InsufficientEvidence"
            auto_enabled = False

        audit_rows.append(
            {
                "Locale": language,
                "NativeTopic": topic,
                "AssignedVertical": vertical,
                "SupportingConversations": str(len(supporting_ids)),
                "MatchedConversations": str(len(matched_target)),
                "FalsePositiveConversations": str(false_positive_count),
                "EstimatedPrecision": f"{observed_precision:.4f}",
                "EstimatedCoverage": f"{coverage:.4f}",
                "ValidationMethod": (
                    f"Deterministic conversation-level {validation_folds}-fold"
                ),
                "ValidationConversations": str(
                    validation["conversations"]
                ),
                "ValidationMatchedConversations": str(
                    validation["matched"]
                ),
                "ValidationFalsePositiveConversations": str(
                    validation["false_positives"]
                ),
                "ValidationPrecision": f"{validation['precision']:.4f}",
                "ValidationCoverage": f"{validation['coverage']:.4f}",
                "ValidationStatus": validation_status,
                "CandidateKeywords": "|".join(selected_terms),
                "AutoEnabled": str(auto_enabled).lower(),
                "Status": status,
            }
        )
        if status not in {"AutoValidated", "NeedsReview"}:
            continue

        row = {
            "Enabled": str(auto_enabled).lower(),
            "Locale": language,
            "Vertical": vertical,
            "CanonicalTopic": topic,
            "Keywords": "|".join(selected_terms),
            "Exclusions": "",
            "Priority": "120",
            "Frequency": str(len(matched_target)),
            "ReviewStatus": status,
            "Notes": (
                "Learned locally from native topic evidence across "
                f"{len(supporting_ids)} distinct conversation(s); out-of-fold precision "
                f"{validation['precision']:.1%}, coverage {validation['coverage']:.1%}."
            ),
        }
        generated_rows.append(row)
        if auto_enabled:
            auto_rows.append(row)

    return generated_rows, rules_from_override_rows(auto_rows), audit_rows, pii_counts


def _select_distinct_terms(
    candidates: list[tuple[str, int, int, float]],
    limit: int,
) -> list[tuple[str, int, int, float]]:
    selected = []
    for candidate in candidates:
        term = candidate[0]
        if any(f" {term} " in f" {chosen[0]} " for chosen in selected):
            continue
        selected.append(candidate)
        if len(selected) >= limit:
            break
    return selected


def _term_specificity_rank(term: str) -> int:
    word_count = len(term.split())
    if word_count == 2:
        return 0
    if word_count >= 3:
        return 1
    return 2


def _is_auto_term_specific(term: str, support: int, topic_conversations: int) -> bool:
    if len(term.split()) > 1:
        return True
    coverage = support / topic_conversations if topic_conversations else 0.0
    return (len(term) >= 4 and coverage >= 0.60) or (len(term) >= 3 and coverage >= 0.80)


def infer_vertical(examples: list[dict], built_in_rules: list[dict]) -> str:
    verticals = Counter()
    for example in examples:
        result = classify(example["prompt"], example["locale"], built_in_rules)
        if result["source"] == "keyword" and result["vertical"] not in {"Unknown", "Native"}:
            verticals[result["vertical"]] += 1
    if not verticals:
        return "Customer"
    vertical, count = verticals.most_common(1)[0]
    return vertical if count / sum(verticals.values()) >= 0.75 else "Customer"


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


def rules_from_override_rows(rows: list[dict]) -> list[dict]:
    rules = []
    for row in rows:
        if str(row.get("Enabled") or "").strip().lower() not in TRUE_VALUES:
            continue
        if not str(row.get("Vertical") or "").strip():
            raise ValueError("Enabled override row must specify Vertical")
        if not str(row.get("CanonicalTopic") or "").strip():
            raise ValueError("Enabled override row must specify CanonicalTopic")
        if not str(row.get("Keywords") or "").strip():
            raise ValueError("Enabled override row must specify Keywords")
        try:
            priority = int(row.get("Priority") or "")
        except (TypeError, ValueError) as error:
            raise ValueError("Enabled override row has an invalid Priority") from error
        rules.append(
            {
                "Locale": str(row.get("Locale") or "*").strip().lower() or "*",
                "Vertical": str(row["Vertical"]).strip(),
                "CanonicalTopic": str(row["CanonicalTopic"]).strip(),
                "Keywords": str(row["Keywords"]).strip(),
                "Exclusions": str(row.get("Exclusions") or "").strip(),
                "Priority": priority,
                "RuleSource": "Customer",
            }
        )
    return rules


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
    if not 0.5 <= args.min_native_topic_precision <= 1.0:
        raise ValueError("--min-native-topic-precision must be between 0.5 and 1.0")
    if args.max_native_keywords < 1:
        raise ValueError("--max-native-keywords must be positive")
    if args.validation_folds < 2:
        raise ValueError("--validation-folds must be at least 2")
    if args.min_validation_conversations < 1:
        raise ValueError("--min-validation-conversations must be positive")

    built_in_rules = load_rules(args.taxonomy)
    existing_override_rows = read_override_rows(args.overrides)
    approved_customer_rules = approved_rules(args.overrides)
    records, input_stats = load_input(args)
    learned_rows, learned_rules, learning_audit, learning_pii_counts = learn_native_topic_rules(
        records,
        built_in_rules,
        existing_override_rows,
        min_frequency=args.min_frequency,
        min_precision=args.min_native_topic_precision,
        max_keywords=args.max_native_keywords,
        validation_folds=args.validation_folds,
        min_validation_conversations=args.min_validation_conversations,
    )
    customer_rules = approved_customer_rules + learned_rules
    all_rules = customer_rules + built_in_rules
    enrichments, audits, uncategorized = classify_records(records, all_rules, args.hash_salt)
    candidates, candidate_pii_counts = candidate_terms(
        uncategorized,
        all_rules,
        min_frequency=args.min_frequency,
        max_candidates=args.max_candidates,
    )

    existing_keywords = {
        normalize(term)
        for row in existing_override_rows + learned_rows
        for term in row.get("Keywords", "").split("|")
        if normalize(term)
    }
    candidates = [row for row in candidates if normalize(row["Keywords"]) not in existing_keywords]
    override_rows = existing_override_rows + learned_rows + candidates

    output_dir = args.output_dir
    write_csv(output_dir / "topic-enrichment.csv", enrichments, tuple(enrichments[0].keys()) if enrichments else (
        "ConversationHash", "Topic", "Vertical", "Language", "Confidence", "Source", "RuleSource", "ClassifierVersion"
    ))
    write_csv(output_dir / "classification-audit.csv", audits, tuple(audits[0].keys()) if audits else (
        "ConversationHash", "NativeTopic", "PredictedTopic", "PredictedVertical", "Language", "MatchedTerms",
        "MatchScore", "Confidence", "Ambiguous", "Source", "RuleSource", "ClassifierVersion"
    ))
    write_csv(output_dir / "topic-learning-audit.csv", learning_audit, LEARNING_AUDIT_COLUMNS)
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
    pii_counts = learning_pii_counts + candidate_pii_counts
    auto_validated_rules = sum(row["ReviewStatus"] == "AutoValidated" for row in learned_rows)
    review_required_rules = sum(row["ReviewStatus"] == "NeedsReview" for row in learned_rows)
    report = {
        "tunerVersion": TUNER_VERSION,
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
        "approvedCustomerRules": len(approved_customer_rules),
        "nativeTopicTrainingExamples": sum(
            is_learnable_native_topic(example.get("native_topic"))
            for record in records
            for example in record.get("training_examples", [])
        ),
        "nativeTopicsObserved": len(learning_audit),
        "nativeTopicLearningStatuses": dict(
            sorted(Counter(row["Status"] for row in learning_audit).items())
        ),
        "minimumNativeTopicPrecision": args.min_native_topic_precision,
        "nativeTopicValidationMethod": (
            f"Deterministic conversation-level {args.validation_folds}-fold"
        ),
        "minimumValidationConversations": args.min_validation_conversations,
        "autoValidatedNativeTopicRules": auto_validated_rules,
        "nativeTopicRulesNeedingReview": review_required_rules,
        "enabledCustomerRulesWritten": len(customer_rules),
        "piiPatternsRedactedBeforeTopicLearning": dict(sorted(learning_pii_counts.items())),
        "piiPatternsRedactedBeforeCandidateExtraction": dict(
            sorted(candidate_pii_counts.items())
        ),
        "piiPatternsRedactedTotal": dict(sorted(pii_counts.items())),
        "rawTranscriptTextWritten": False,
        "warning": (
            "Learned and candidate keywords are privacy-reduced, not guaranteed anonymous. They can still contain "
            "repeated business-sensitive terms. Keep outputs inside the customer environment and review before sharing."
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
