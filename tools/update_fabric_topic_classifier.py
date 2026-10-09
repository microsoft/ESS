import argparse
import csv
import json
import uuid
import zipfile
from pathlib import Path

from update_topic_classifier import CLASSIFIER_VERSION, replace_query_text_raw


SESSION_COLUMNS = (
    ("locale", "string"),
    ("primary_topic_native", "string"),
    ("topic_vertical_derived", "string"),
    ("topic_classification_source", "string"),
    ("topic_matched_terms", "string"),
    ("topic_match_score", "double"),
    ("topic_confidence", "double"),
    ("topic_ambiguous", "boolean"),
    ("topic_language", "string"),
    ("topic_rule_source", "string"),
    ("topic_classifier_version", "string"),
)


def read_taxonomy(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    return [
        {
            "locale": row["Locale"].strip().lower(),
            "vertical": row["Vertical"].strip(),
            "topic": row["CanonicalTopic"].strip(),
            "keywords": [value.strip() for value in row["Keywords"].split("|") if value.strip()],
            "exclusions": [value.strip() for value in row["Exclusions"].split("|") if value.strip()],
            "priority": int(row["Priority"]),
            "rule_source": "BuiltIn",
        }
        for row in rows
    ]


def build_stage_one(taxonomy: list[dict]) -> str:
    taxonomy_json = json.dumps(taxonomy, ensure_ascii=False, indent=4)
    return f"""# === 7c-1. SHARED MULTILINGUAL TOPIC CLASSIFICATION (offline) ===
# Generated from taxonomy/topics-taxonomy.csv. No transcript data leaves Fabric.
TOPIC_CLASSIFIER_VERSION = {CLASSIFIER_VERSION!r}
TOPIC_TAXONOMY = {taxonomy_json}
_TOPIC_SEPARATORS = re.compile(r'''[\\s.,;:!?()\\[\\]{{}}<>/\\\\\\-_+=*&^%$#@~`'"]+''')

def _load_customer_topic_rules(path):
    if not path:
        return []
    from pathlib import Path as _Path
    _path = _Path(path)
    if not _path.exists():
        print(f'Customer topic overrides not found at {{path}}; using built-in taxonomy only.')
        return []
    _frame = pd.read_csv(_path, keep_default_na=False)
    _required = {{'Enabled', 'Locale', 'Vertical', 'CanonicalTopic', 'Keywords', 'Exclusions', 'Priority'}}
    _missing = sorted(_required - set(_frame.columns))
    if _missing:
        raise ValueError(f'Customer topic overrides are missing columns: {{_missing}}')
    _enabled = _frame[_frame['Enabled'].astype(str).str.strip().str.lower().isin({{'1', 'true', 'yes', 'y'}})]
    _rules = []
    for _row_number, _row in _enabled.iterrows():
        _vertical = str(_row['Vertical']).strip()
        _topic = str(_row['CanonicalTopic']).strip()
        _keywords = [value.strip() for value in str(_row['Keywords']).split('|') if value.strip()]
        if not _vertical or not _topic or not _keywords:
            raise ValueError(f'Enabled customer topic rule at row {{_row_number + 2}} is incomplete.')
        _rules.append({{
            'locale': str(_row['Locale']).strip().lower() or '*',
            'vertical': _vertical,
            'topic': _topic,
            'keywords': _keywords,
            'exclusions': [value.strip() for value in str(_row['Exclusions']).split('|') if value.strip()],
            'priority': int(_row['Priority']),
            'rule_source': 'Customer',
        }})
    print(f'Loaded {{len(_rules):,}} approved customer topic override rule(s).')
    return _rules

CUSTOMER_TOPIC_RULES = _load_customer_topic_rules(TOPIC_OVERRIDES_FILE)
TOPIC_RULES = CUSTOMER_TOPIC_RULES + TOPIC_TAXONOMY

def _normalize_topic_text(value):
    return ' '.join(part for part in _TOPIC_SEPARATORS.split(str(value or '').lower()) if part)

def _topic_language(locale):
    return str(locale or '').strip().lower()[:2]

def _contains_topic_term(normalized_text, term, language):
    normalized_term = _normalize_topic_text(term)
    if not normalized_term:
        return False
    if language == 'zh':
        return normalized_term in normalized_text
    return f' {{normalized_term}} ' in f' {{normalized_text}} '

def _topic_term_weight(term, language):
    normalized_term = _normalize_topic_text(term)
    if language == 'zh':
        return 3 if len(normalized_term) >= 4 else 2
    if len(normalized_term.split()) >= 2:
        return 3
    return 1 if len(normalized_term) <= 2 else 2

def classify_topic_keyword(text, locale, taxonomy):
    normalized_text = _normalize_topic_text(text)
    language = _topic_language(locale)
    if not normalized_text:
        return {{
            'topic': 'No User Intent',
            'vertical': 'System-Init',
            'matched_terms': None,
            'score': 0.0,
            'confidence': 1.0,
            'ambiguous': False,
            'language': language,
            'source': 'no-user-intent',
            'rule_source': '',
            'version': TOPIC_CLASSIFIER_VERSION,
        }}

    scored = []
    for rule in taxonomy:
        if rule['locale'] not in ('*', language):
            continue
        hits = [term for term in rule['keywords']
                if _contains_topic_term(normalized_text, term, language)]
        excluded = any(_contains_topic_term(normalized_text, term, language)
                       for term in rule['exclusions'])
        score = 0 if excluded else sum(_topic_term_weight(term, language) for term in hits)
        if score:
            scored.append((score, rule['priority'], rule, hits))

    if not scored:
        return {{
            'topic': 'Other / Uncategorized',
            'vertical': 'Unknown',
            'matched_terms': None,
            'score': 0.0,
            'confidence': 0.0,
            'ambiguous': False,
            'language': language,
            'source': 'uncategorized',
            'rule_source': '',
            'version': TOPIC_CLASSIFIER_VERSION,
        }}

    scored.sort(key=lambda item: (-item[0], -item[1], item[2]['topic']))
    top_score, top_priority = scored[0][0], scored[0][1]
    tied = [item for item in scored if item[0] == top_score and item[1] == top_priority]
    tied_topics = {{(item[2]['vertical'], item[2]['topic']) for item in tied}}
    ambiguous = len(tied_topics) > 1
    confidence = (0.4 if ambiguous else
                  0.98 if top_score >= 6 else
                  0.93 if top_score >= 4 else
                  0.85 if top_score >= 2 else 0.70)

    if ambiguous:
        return {{
            'topic': 'Other / Uncategorized',
            'vertical': 'Unknown',
            'matched_terms': ' | '.join(sorted({{term for item in tied for term in item[3]}})),
            'score': float(top_score),
            'confidence': confidence,
            'ambiguous': True,
            'language': language,
            'source': 'uncategorized',
            'rule_source': '',
            'version': TOPIC_CLASSIFIER_VERSION,
        }}

    _, _, rule, hits = scored[0]
    rule_source = rule.get('rule_source', 'BuiltIn')
    return {{
        'topic': rule['topic'],
        'vertical': rule['vertical'],
        'matched_terms': ' | '.join(hits),
        'score': float(top_score),
        'confidence': confidence,
        'ambiguous': False,
        'language': language,
        'source': 'keyword',
        'rule_source': rule_source,
        'version': TOPIC_CLASSIFIER_VERSION + ('+CUSTOMER' if rule_source == 'Customer' else ''),
    }}

def classify_topic_row(row):
    native_topic = str(row.get('primary_topic_native') or '').strip()
    if native_topic and native_topic not in ('No Topic Detected', 'No User Intent', 'Other / Uncategorized'):
        return {{
            'topic': native_topic,
            'vertical': 'Native',
            'matched_terms': None,
            'score': None,
            'confidence': 1.0,
            'ambiguous': False,
            'language': _topic_language(row.get('locale')),
            'source': 'native',
            'rule_source': 'Native',
            'version': 'Native',
        }}
    return classify_topic_keyword(row.get('first_user_prompt'), row.get('locale'), TOPIC_RULES)

_classified = sessions.apply(classify_topic_row, axis=1)
sessions['primary_topic_derived'] = [item['topic'] for item in _classified]
sessions['topic_vertical_derived'] = [item['vertical'] for item in _classified]
sessions['topic_classification_source'] = [item['source'] for item in _classified]
sessions['topic_matched_terms'] = [item['matched_terms'] for item in _classified]
sessions['topic_match_score'] = [item['score'] for item in _classified]
sessions['topic_confidence'] = [item['confidence'] for item in _classified]
sessions['topic_ambiguous'] = [item['ambiguous'] for item in _classified]
sessions['topic_language'] = [item['language'] for item in _classified]
sessions['topic_rule_source'] = [item['rule_source'] for item in _classified]
sessions['topic_classifier_version'] = [item['version'] for item in _classified]

_source_counts = sessions['topic_classification_source'].value_counts()
print(f"Stage 1 classification: {{int(_source_counts.get('keyword', 0)):,}} matched / "
      f"{{int(_source_counts.get('native', 0)):,}} native / {{len(sessions):,}} total; "
      f"{{int(_source_counts.get('uncategorized', 0)):,}} uncategorized")
"""


def build_stage_two() -> str:
    return f"""# === 7c-2. LOCAL MULTILINGUAL DISCOVERY FALLBACK (offline) ===
ENABLE_SEMANTIC_FALLBACK = True
MIN_UNCATEGORIZED_FOR_CLUSTERING = 20
N_TERMS_PER_CLUSTER_LABEL = 3

_uncategorized_mask = sessions['topic_classification_source'] == 'uncategorized'
_uncategorized_count = int(_uncategorized_mask.sum())

if not ENABLE_SEMANTIC_FALLBACK:
    print(f'Stage 2 disabled -- {{_uncategorized_count:,}} row(s) remain uncategorized.')
elif _uncategorized_count < MIN_UNCATEGORIZED_FOR_CLUSTERING:
    print(f'Stage 2 skipped -- only {{_uncategorized_count:,}} uncategorized row(s).')
else:
    try:
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.cluster import KMeans
    except ImportError as _import_err:
        print(f'Stage 2 skipped -- scikit-learn unavailable ({{_import_err}}).')
    else:
        _texts = sessions.loc[_uncategorized_mask, 'first_user_prompt'].fillna('')
        _nonblank_mask = _texts.str.strip() != ''
        _cluster_texts = _texts[_nonblank_mask]
        if len(_cluster_texts) < MIN_UNCATEGORIZED_FOR_CLUSTERING:
            print(f'Stage 2 skipped -- only {{len(_cluster_texts):,}} nonblank rows.')
        else:
            _n_clusters = max(2, min(10, len(_cluster_texts) // 10))
            try:
                # Character n-grams work for English, whitespace languages, and CJK without
                # downloading a model or sending prompts outside the workspace.
                _vectorizer = TfidfVectorizer(
                    analyzer='char_wb',
                    ngram_range=(2, 5),
                    max_df=0.95,
                    min_df=2,
                    lowercase=True)
                _matrix = _vectorizer.fit_transform(_cluster_texts)
                _kmeans = KMeans(n_clusters=_n_clusters, random_state=42, n_init=10)
                _cluster_ids = _kmeans.fit_predict(_matrix)
            except ValueError as _cluster_err:
                print(f'Stage 2 skipped -- clustering failed ({{_cluster_err}}).')
            else:
                _terms = _vectorizer.get_feature_names_out()
                _cluster_labels = {{}}
                _cluster_terms = {{}}
                for _cid in range(_n_clusters):
                    _center = _kmeans.cluster_centers_[_cid]
                    _top_idx = _center.argsort()[::-1][:N_TERMS_PER_CLUSTER_LABEL]
                    _top_terms = [_terms[i].strip() for i in _top_idx if _center[i] > 0 and _terms[i].strip()]
                    _cluster_terms[_cid] = _top_terms
                    _cluster_labels[_cid] = ('Auto-Discovered: ' + ', '.join(_top_terms)) if _top_terms else 'Auto-Discovered: (unlabeled cluster)'

                for _index, _cluster_id in zip(_cluster_texts.index, _cluster_ids):
                    sessions.at[_index, 'primary_topic_derived'] = _cluster_labels[_cluster_id]
                    sessions.at[_index, 'topic_classification_source'] = 'auto-discovered'
                    sessions.at[_index, 'topic_matched_terms'] = ' | '.join(_cluster_terms[_cluster_id])
                    sessions.at[_index, 'topic_match_score'] = 0.0
                    sessions.at[_index, 'topic_confidence'] = 0.50
                    sessions.at[_index, 'topic_ambiguous'] = False
                    sessions.at[_index, 'topic_rule_source'] = 'AutoDiscovered'
                    sessions.at[_index, 'topic_classifier_version'] = TOPIC_CLASSIFIER_VERSION + '+TFIDF'
                print(f'Stage 2: {{len(_cluster_texts):,}} row(s) clustered into {{_n_clusters}} candidate topic(s).')

_final_counts = sessions['topic_classification_source'].value_counts()
print('\\nTopic classification summary:')
for _source in ('keyword', 'auto-discovered', 'uncategorized', 'no-user-intent'):
    print(f'  {{_source:16}} {{int(_final_counts.get(_source, 0)):>7,}}')
"""


def update_sessions_cell(source: str) -> str:
    if "'locale': session_locale," not in source:
        prompt_block = """        first_prompt = ''
        for a in user_msgs:
            if a.get('text', ''):
                first_prompt = a['text'][:TEXT_TRUNCATE]
                break
"""
        locale_block = prompt_block + """        session_locale = ''
        for a in acts:
            if not isinstance(a, dict):
                continue
            if a.get('name') == 'pvaSetContext':
                session_locale = str((a.get('value') or {}).get('locale') or '')
                if session_locale:
                    break
            if not session_locale and a.get('locale'):
                session_locale = str(a.get('locale'))
        if not session_locale:
            session_locale = str(r.get('locale') or '')
"""
        if prompt_block not in source:
            raise ValueError("build_sessions prompt block not found")
        source = source.replace(prompt_block, locale_block, 1)
        source = source.replace(
            "            'feedback_comment': comment,\n            'first_user_prompt': first_prompt,",
            "            'feedback_comment': comment,\n            'locale': session_locale,\n            'first_user_prompt': first_prompt,",
            1,
        )
        source = source.replace(
            "'feedback_verdict', 'feedback_comment', 'first_user_prompt',",
            "'feedback_verdict', 'feedback_comment', 'locale', 'first_user_prompt',",
            1,
        )

    if "'primary_topic_native': primary_topic_native," not in source:
        locale_tail = """        if not session_locale:
            session_locale = str(r.get('locale') or '')
"""
        native_block = locale_tail + """        _native_noise = {
            'logging', 'greeting', 'goodbye', 'end of conversation', 'start over',
            'escalate', 'sign in', 'signin', 'reset conversation', 'on error',
            'multiple topics matched', 'fallback', 'conversational boosting',
            'thumbs up', 'thumbs down'}
        _native_topics = []
        for a in acts:
            if not isinstance(a, dict):
                continue
            if a.get('valueType') != 'IntentRecognition' and a.get('name') != 'IntentRecognition':
                continue
            title = str((a.get('value') or {}).get('intentTitle') or '').strip()
            if (title and not title.startswith(('[System]', '[Internal]', '[Admin]', '[Debug]', '[Test]'))
                    and title.lower() not in _native_noise):
                _native_topics.append(title)
        primary_topic_native = _native_topics[0] if _native_topics else None
"""
        if locale_tail not in source:
            raise ValueError("build_sessions locale block not found")
        source = source.replace(locale_tail, native_block, 1)
        source = source.replace(
            "            'locale': session_locale,\n            'first_user_prompt': first_prompt,",
            "            'locale': session_locale,\n            'primary_topic_native': primary_topic_native,\n            'first_user_prompt': first_prompt,",
            1,
        )
        source = source.replace(
            "'feedback_verdict', 'feedback_comment', 'locale', 'first_user_prompt',",
            "'feedback_verdict', 'feedback_comment', 'locale', 'primary_topic_native', 'first_user_prompt',",
            1,
        )
    return source


def update_config_cell(source: str) -> str:
    if "TOPIC_OVERRIDES_FILE" not in source:
        marker = "TRANSCRIPTS_FILE  = f'{SOURCE_DIR}/conversationtranscripts.csv'   # used only when SOURCE_MODE='files'\n"
        if marker not in source:
            raise ValueError("CONFIG transcript file marker not found")
        block = marker + (
            "TOPIC_OVERRIDES_FILE = '/lakehouse/default/Files/config/customer-topic-overrides.csv'  "
            "# optional output from tools/ess_topic_tuner.py\n"
        )
        source = source.replace(marker, block, 1)

    source = source.replace(
        "WRITE_MODE    = 'overwrite'  # 'overwrite' = full snapshot; 'append' = add rows; 'merge' = upsert on natural keys (safe multi-env incremental, no duplicates)",
        "WRITE_MODE    = 'merge'      # safe default for scheduled incremental pulls; use overwrite only with a full Dataverse pull",
    )
    source = source.replace(
        "RAW_TABLE     = 'dbo.conversationtranscripts_raw'",
        "RAW_TABLE     = 'conversationtranscripts_raw'",
    )
    source = source.replace(
        "OUTPUT_PREFIX = 'dbo'        # Delta schema. Tables: dbo.agent_sessions, dbo.agent_turns, ...",
        "OUTPUT_PREFIX = ''           # Spark table prefix. Leave blank for standard Lakehouses; use 'dbo' only when schemas are enabled.",
    )
    guard_marker = "# __INCREMENTAL_OVERWRITE_GUARD__"
    if guard_marker not in source:
        output_marker = "TEXT_TRUNCATE = 500          # max chars kept for free-text fields (PII-safe preview)\n"
        if output_marker not in source:
            raise ValueError("CONFIG output marker not found")
        guard = output_marker + f"""

{guard_marker}
if SOURCE_MODE == 'dataverse' and LOOKBACK_DAYS > 0 and WRITE_MODE == 'overwrite':
    raise ValueError(
        "Unsafe configuration: overwrite with a bounded Dataverse lookback would delete older history. "
        "Use WRITE_MODE='merge', or set LOOKBACK_DAYS=0 for an intentional full snapshot.")
"""
        source = source.replace(output_marker, guard, 1)
    return source


def update_role_mapping(source: str) -> str:
    return source.replace("(0, 'user')", "(1, 'user')").replace("(1, 'bot')", "(0, 'bot')")


def patch_notebook(notebook_path: Path, taxonomy: list[dict]) -> None:
    notebook = json.loads(notebook_path.read_text(encoding="utf-8"))
    overview = "".join(notebook["cells"][1]["source"]).replace(
        "For incremental reruns use `WRITE_MODE='merge'`; full snapshots use `LOOKBACK_DAYS=0` with `'overwrite'`.",
        "`WRITE_MODE='merge'` is the safe default for bounded incremental reruns; full snapshots use `LOOKBACK_DAYS=0` with `'overwrite'`.",
    )
    notebook["cells"][1]["source"] = overview.splitlines(True)
    notebook["cells"][3]["source"] = update_config_cell("".join(notebook["cells"][3]["source"])).splitlines(True)
    for index in (10, 12, 14, 25):
        notebook["cells"][index]["source"] = update_role_mapping(
            "".join(notebook["cells"][index]["source"])
        ).splitlines(True)
    notebook["cells"][12]["source"] = update_sessions_cell("".join(notebook["cells"][12]["source"])).splitlines(True)
    notebook["cells"][22]["source"] = build_stage_one(taxonomy).splitlines(True)
    notebook["cells"][23]["source"] = build_stage_two().splitlines(True)
    notebook["cells"][21]["source"] = [
        "## 7c. Shared multilingual topic classification\n",
        "\n",
        "Runs fully inside Fabric. Stage 1 uses the same customer-neutral taxonomy and scoring contract as CSV/Dataverse. Stage 2 groups remaining uncategorized prompts with multilingual character n-grams and labels them as auto-discovered candidates.\n",
    ]
    notebook_path.write_text(json.dumps(notebook, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    compile("".join(notebook["cells"][12]["source"]), "build_sessions", "exec")
    compile("".join(notebook["cells"][22]["source"]), "topic_stage_one", "exec")
    compile("".join(notebook["cells"][23]["source"]), "topic_stage_two", "exec")


def patch_agent_sessions_query(expression: str) -> str:
    required_columns = (
        "locale",
        "primary_topic_native",
        "primary_topic_derived",
        "topic_vertical_derived",
        "topic_classification_source",
        "topic_matched_terms",
        "topic_match_score",
        "topic_confidence",
        "topic_ambiguous",
        "topic_language",
        "topic_rule_source",
        "topic_classifier_version",
    )
    ensured_start = expression.find("    Ensured = List.Accumulate(")
    ensured_end = expression.find("        Promoted,", ensured_start)
    if ensured_start < 0 or ensured_end < 0:
        raise ValueError("Agent Sessions Ensured list not found")
    ensured = expression[ensured_start:ensured_end]
    for column in required_columns:
        if f'"{column}"' not in ensured:
            if '"agent_name"' not in ensured:
                raise ValueError("Agent Sessions Ensured insertion marker not found")
            ensured = ensured.replace('"agent_name"', f'"{column}", "agent_name"', 1)
    expression = expression[:ensured_start] + ensured + expression[ensured_end:]

    type_map = {
        "locale": "type text",
        "primary_topic_native": "type text",
        "primary_topic_derived": "type text",
        "topic_vertical_derived": "type text",
        "topic_classification_source": "type text",
        "topic_matched_terms": "type text",
        "topic_match_score": "type number",
        "topic_confidence": "type number",
        "topic_ambiguous": "type logical",
        "topic_language": "type text",
        "topic_rule_source": "type text",
        "topic_classifier_version": "type text",
    }
    type_marker = '        {"agent_name", type text},'
    if type_marker not in expression:
        raise ValueError("Agent Sessions type insertion marker not found")
    additions = []
    for column, m_type in type_map.items():
        if f'{{"{column}",' not in expression:
            additions.append(f'        {{"{column}", {m_type}}},')
    if additions:
        expression = expression.replace(type_marker, "\n".join(additions) + "\n" + type_marker, 1)
    return expression


def patch_fabric_pbit(source: Path, destination: Path) -> None:
    with zipfile.ZipFile(source, "r") as archive:
        infos = archive.infolist()
        parts = {info.filename: archive.read(info.filename) for info in infos}

    schema = json.loads(parts["DataModelSchema"].decode("utf-16-le"))
    table = next(item for item in schema["model"]["tables"] if item["name"] == "Agent Sessions")
    partition = table["partitions"][0]["source"]
    original_expression = partition["expression"]
    expression = "\n".join(original_expression) if isinstance(original_expression, list) else original_expression
    expression = patch_agent_sessions_query(expression)
    partition["expression"] = expression.splitlines() if isinstance(original_expression, list) else expression

    existing = {column["name"] for column in table["columns"]}
    for name, data_type in SESSION_COLUMNS:
        if name in existing:
            continue
        table["columns"].append(
            {
                "name": name,
                "dataType": data_type,
                "sourceColumn": name,
                "lineageTag": str(uuid.uuid5(uuid.NAMESPACE_URL, f"https://github.com/microsoft/ESS/fabric/{name}")),
                "summarizeBy": "none",
                "annotations": [{"name": "SummarizationSetBy", "value": "Automatic"}],
            }
        )

    parts["DataModelSchema"] = json.dumps(schema, ensure_ascii=False, separators=(",", ":")).encode("utf-16-le")
    unapplied_raw = parts["UnappliedChanges"].decode("utf-16-le")
    unapplied_raw = replace_query_text_raw(unapplied_raw, "Agent Sessions", patch_agent_sessions_query)
    json.loads(unapplied_raw)
    parts["UnappliedChanges"] = unapplied_raw.encode("utf-16-le")

    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as archive:
        for info in infos:
            archive.writestr(info, parts[info.filename])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--taxonomy", type=Path, required=True)
    parser.add_argument("--notebook", type=Path, required=True)
    parser.add_argument("--source-pbit", type=Path, required=True)
    parser.add_argument("--output-pbit", type=Path, required=True)
    args = parser.parse_args()

    taxonomy = read_taxonomy(args.taxonomy)
    patch_notebook(args.notebook, taxonomy)
    patch_fabric_pbit(args.source_pbit, args.output_pbit)
    print(
        json.dumps(
            {
                "classifierVersion": CLASSIFIER_VERSION,
                "taxonomyRules": len(taxonomy),
                "notebook": str(args.notebook),
                "pbit": str(args.output_pbit),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
