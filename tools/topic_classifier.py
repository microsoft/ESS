import csv
import re
from pathlib import Path


CLASSIFIER_VERSION = "ESS-TOPICS-2026.10"
RULE_COLUMNS = ("Locale", "Vertical", "CanonicalTopic", "Keywords", "Exclusions", "Priority")
SEPARATOR_UNICODE_VERSION = "16.0.0"
_SEPARATOR_RANGE_SPEC = (
    "0009-000D 001C-002F 003A-0040 005B-0060 007B 007D-007E 0085 00A0-00A1 00A7 00AB 00B6-00B7 00BB 00BF 037E "
    "0387 055A-055F 0589-058A 05BE 05C0 05C3 05C6 05F3-05F4 0609-060A 060C-060D 061B 061D-061F 066A-066D 06D4 "
    "0700-070D 07F7-07F9 0830-083E 085E 0964-0965 0970 09FD 0A76 0AF0 0C77 0C84 0DF4 0E4F 0E5A-0E5B 0F04-0F12 "
    "0F14 0F3A-0F3D 0F85 0FD0-0FD4 0FD9-0FDA 104A-104F 10FB 1360-1368 1400 166E 1680 169B-169C 16EB-16ED "
    "1735-1736 17D4-17D6 17D8-17DA 1800-180A 1944-1945 1A1E-1A1F 1AA0-1AA6 1AA8-1AAD 1B4E-1B4F 1B5A-1B60 "
    "1B7D-1B7F 1BFC-1BFF 1C3B-1C3F 1C7E-1C7F 1CC0-1CC7 1CD3 2000-200A 2010-2029 202F-2043 2045-2051 2053-205F "
    "207D-207E 208D-208E 2308-230B 2329-232A 2768-2775 27C5-27C6 27E6-27EF 2983-2998 29D8-29DB 29FC-29FD "
    "2CF9-2CFC 2CFE-2CFF 2D70 2E00-2E2E 2E30-2E4F 2E52-2E5D 3000-3003 3008-3011 3014-301F 3030 303D 30A0 30FB "
    "A4FE-A4FF A60D-A60F A673 A67E A6F2-A6F7 A874-A877 A8CE-A8CF A8F8-A8FA A8FC A92E-A92F A95F A9C1-A9CD "
    "A9DE-A9DF AA5C-AA5F AADE-AADF AAF0-AAF1 ABEB FD3E-FD3F FE10-FE19 FE30-FE52 FE54-FE61 FE63 FE68 FE6A-FE6B "
    "FF01-FF03 FF05-FF0A FF0C-FF0F FF1A-FF1B FF1F-FF20 FF3B-FF3D FF3F FF5B FF5D FF5F-FF65 10100-10102 1039F "
    "103D0 1056F 10857 1091F 1093F 10A50-10A58 10A7F 10AF0-10AF6 10B39-10B3F 10B99-10B9C 10D6E 10EAD "
    "10F55-10F59 10F86-10F89 11047-1104D 110BB-110BC 110BE-110C1 11140-11143 11174-11175 111C5-111C8 111CD "
    "111DB 111DD-111DF 11238-1123D 112A9 113D4-113D5 113D7-113D8 1144B-1144F 1145A-1145B 1145D 114C6 "
    "115C1-115D7 11641-11643 11660-1166C 116B9 1173C-1173E 1183B 11944-11946 119E2 11A3F-11A46 11A9A-11A9C "
    "11A9E-11AA2 11B00-11B09 11BE1 11C41-11C45 11C70-11C71 11EF7-11EF8 11F43-11F4F 11FFF 12470-12474 "
    "12FF1-12FF2 16A6E-16A6F 16AF5 16B37-16B3B 16B44 16D6D-16D6F 16E97-16E9A 16FE2 1BC9F 1DA87-1DA8B 1E5FF "
    "1E95E-1E95F"
)


def _separator_characters() -> str:
    characters = []
    for value in _SEPARATOR_RANGE_SPEC.split():
        bounds = value.split("-", maxsplit=1)
        start = int(bounds[0], 16)
        end = int(bounds[-1], 16)
        characters.extend(chr(codepoint) for codepoint in range(start, end + 1))
    return "".join(characters)


SEPARATOR_CHARACTERS = _separator_characters()
SEPARATORS = re.compile("[" + re.escape(SEPARATOR_CHARACTERS) + "]+")


def normalize(value: str | None) -> str:
    return " ".join(part for part in SEPARATORS.split((value or "").lower()) if part)


def language_prefix(locale: str | None) -> str:
    return (locale or "").strip().lower()[:2]


def rule_locale(locale: str | None) -> str:
    return language_prefix(locale) or "*"


def canonical_terms(value: str | None) -> str:
    return "|".join(dict.fromkeys(term for raw in (value or "").split("|") if (term := normalize(raw))))


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
        if not canonical_terms(row["Keywords"]):
            raise ValueError(f"{path}:{row_number} has no keywords after normalization")
        if not row["Vertical"].strip() or not row["CanonicalTopic"].strip():
            raise ValueError(f"{path}:{row_number} must specify Vertical and CanonicalTopic")
        try:
            priority = int(row["Priority"])
        except (TypeError, ValueError) as error:
            raise ValueError(f"{path}:{row_number} has an invalid Priority") from error
        rules.append(
            {
                "Locale": rule_locale(row["Locale"]),
                "Vertical": row["Vertical"].strip(),
                "CanonicalTopic": row["CanonicalTopic"].strip(),
                "Keywords": canonical_terms(row["Keywords"]),
                "Exclusions": canonical_terms(row["Exclusions"]),
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
        if rule_locale(rule["Locale"]) not in {"*", language}:
            continue
        keywords = canonical_terms(rule["Keywords"]).split("|") if canonical_terms(rule["Keywords"]) else []
        exclusions = canonical_terms(rule["Exclusions"]).split("|") if canonical_terms(rule["Exclusions"]) else []
        hits = [term for term in keywords if contains_term(text, term, language)]
        excluded = any(contains_term(text, term, language) for term in exclusions)
        score = 0 if excluded else sum(term_weight(term, language) for term in hits)
        if score:
            source_rank = 1 if rule.get("RuleSource") == "Customer" else 0
            scored.append((source_rank, score, int(rule["Priority"]), rule, hits))

    if not scored:
        return _result(
            topic="Other / Uncategorized",
            vertical="Unknown",
            language=language,
            source="uncategorized",
        )

    scored.sort(key=lambda item: (-item[0], -item[1], -item[2], item[3]["CanonicalTopic"]))
    top_source_rank, top_score, top_priority = scored[0][0], scored[0][1], scored[0][2]
    tied = [
        item
        for item in scored
        if item[0] == top_source_rank and item[1] == top_score and item[2] == top_priority
    ]
    tied_topics = {(item[3]["Vertical"], item[3]["CanonicalTopic"]) for item in tied}
    if len(tied_topics) > 1:
        terms = sorted({term for item in tied for term in item[4]})
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

    _, _, _, rule, hits = scored[0]
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
