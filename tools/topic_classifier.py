import csv
import re
from pathlib import Path


CLASSIFIER_VERSION = "ESS-TOPICS-2026.10"
RULE_COLUMNS = ("Locale", "Vertical", "CanonicalTopic", "Keywords", "Exclusions", "Priority")
SEPARATORS = re.compile(r"""[\s.,;:!?()\[\]{}<>/\\\-_+=*&^%$#@~`'"]+""")


def normalize(value: str | None) -> str:
    return " ".join(part for part in SEPARATORS.split((value or "").lower()) if part)


def language_prefix(locale: str | None) -> str:
    return (locale or "").strip().lower()[:2]


def contains_term(text: str, term: str, language: str) -> bool:
    normalized_term = normalize(term)
    if not normalized_term:
        return False
    if language == "zh":
        return normalized_term in text
    return f" {normalized_term} " in f" {text} "


def term_weight(term: str, language: str) -> int:
    normalized_term = normalize(term)
    if language == "zh":
        return 3 if len(normalized_term) >= 4 else 2
    if len(normalized_term.split()) >= 2:
        return 3
    return 1 if len(normalized_term) <= 2 else 2


def load_rules(path: Path, *, enabled_only: bool = False, rule_source: str = "BuiltIn") -> list[dict]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)
        fieldnames = set(reader.fieldnames or [])

    missing = set(RULE_COLUMNS) - fieldnames
    if missing:
        raise ValueError(f"{path} is missing taxonomy columns: {sorted(missing)}")

    rules = []
    for row_number, row in enumerate(rows, start=2):
        if enabled_only and not _is_enabled(row.get("Enabled")):
            continue
        if not row["Keywords"].strip():
            if enabled_only:
                continue
            raise ValueError(f"{path}:{row_number} has no keywords")
        if not row["Vertical"].strip() or not row["CanonicalTopic"].strip():
            raise ValueError(f"{path}:{row_number} must specify Vertical and CanonicalTopic")
        try:
            priority = int(row["Priority"])
        except (TypeError, ValueError) as error:
            raise ValueError(f"{path}:{row_number} has an invalid Priority") from error
        rules.append(
            {
                "Locale": row["Locale"].strip().lower() or "*",
                "Vertical": row["Vertical"].strip(),
                "CanonicalTopic": row["CanonicalTopic"].strip(),
                "Keywords": row["Keywords"].strip(),
                "Exclusions": row["Exclusions"].strip(),
                "Priority": priority,
                "RuleSource": row.get("RuleSource", "").strip() or rule_source,
            }
        )
    return rules


def classify(prompt: str | None, locale: str | None, rules: list[dict]) -> dict:
    text = normalize(prompt)
    language = language_prefix(locale)
    if not text:
        return _result(
            topic="No User Intent",
            vertical="System-Init",
            language=language,
            source="no-user-intent",
            confidence=1.0,
        )

    scored = []
    for rule in rules:
        if rule["Locale"] not in {"*", language}:
            continue
        keywords = [value.strip() for value in rule["Keywords"].split("|") if value.strip()]
        exclusions = [value.strip() for value in rule["Exclusions"].split("|") if value.strip()]
        hits = [term for term in keywords if contains_term(text, term, language)]
        excluded = any(contains_term(text, term, language) for term in exclusions)
        score = 0 if excluded else sum(term_weight(term, language) for term in hits)
        if score:
            scored.append((score, int(rule["Priority"]), rule, hits))

    if not scored:
        return _result(
            topic="Other / Uncategorized",
            vertical="Unknown",
            language=language,
            source="uncategorized",
        )

    scored.sort(key=lambda item: (-item[0], -item[1], item[2]["CanonicalTopic"]))
    top_score, top_priority = scored[0][0], scored[0][1]
    tied = [item for item in scored if item[0] == top_score and item[1] == top_priority]
    tied_topics = {(item[2]["Vertical"], item[2]["CanonicalTopic"]) for item in tied}
    if len(tied_topics) > 1:
        terms = sorted({term for item in tied for term in item[3]})
        return _result(
            topic="Other / Uncategorized",
            vertical="Unknown",
            matched_terms=" | ".join(terms),
            score=float(top_score),
            confidence=0.4,
            ambiguous=True,
            language=language,
            source="uncategorized",
        )

    _, _, rule, hits = scored[0]
    confidence = 0.98 if top_score >= 6 else 0.93 if top_score >= 4 else 0.85 if top_score >= 2 else 0.70
    rule_source = rule.get("RuleSource", "BuiltIn")
    version = CLASSIFIER_VERSION + ("+CUSTOMER" if rule_source == "Customer" else "")
    return _result(
        topic=rule["CanonicalTopic"],
        vertical=rule["Vertical"],
        matched_terms=" | ".join(hits),
        score=float(top_score),
        confidence=confidence,
        language=language,
        source="keyword",
        rule_source=rule_source,
        version=version,
    )


def _result(
    *,
    topic: str,
    vertical: str,
    language: str,
    source: str,
    matched_terms: str = "",
    score: float = 0.0,
    confidence: float = 0.0,
    ambiguous: bool = False,
    rule_source: str = "",
    version: str = CLASSIFIER_VERSION,
) -> dict:
    return {
        "topic": topic,
        "vertical": vertical,
        "matched_terms": matched_terms,
        "score": score,
        "confidence": confidence,
        "ambiguous": ambiguous,
        "language": language,
        "source": source,
        "rule_source": rule_source,
        "version": version,
    }


def _is_enabled(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "y"}
