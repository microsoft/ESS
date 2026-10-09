import argparse
import json
import re
import uuid
import zipfile
from pathlib import Path

from update_topic_classifier import replace_query_text_raw


REGISTRY_CONFIG = """# === AGENT REGISTRY CONFIG (generated) ===
AGENT_REGISTRY_FILE = '/lakehouse/default/Files/config/agent-registry.csv'
AGENT_SCOPE_MODE = 'ESS Safe'
_AGENT_SCOPE_MODES = {'ESS Safe', 'Selected Agents', 'All Agents'}
if AGENT_SCOPE_MODE not in _AGENT_SCOPE_MODES:
    raise ValueError(
        'AGENT_SCOPE_MODE must be exactly one of: ESS Safe, Selected Agents, All Agents')
# === END AGENT REGISTRY CONFIG ===
"""

IDENTITY_COLUMNS = [
    "conversation_natural_key",
    "canonical_agent_key",
    "canonical_agent_name",
    "canonical_environment_key",
    "agent_mapping_status",
    "raw_agent_id",
    "raw_agent_schema",
    "raw_agent_name",
    "raw_environment",
    "source_environment",
]

TRANSCRIPT_REGISTRY_RUNTIME = r'''# === AGENT REGISTRY RUNTIME (generated) ===
import csv as _registry_csv
import hashlib as _registry_hashlib

_REGISTRY_COLUMNS = {
    'RegistryVersion', 'AgentKey', 'AgentLabel', 'IsEss', 'Selected', 'Enabled',
    'EnvironmentKey', 'EnvironmentName', 'EnvironmentUrl', 'AliasType', 'AliasValue'}
_REGISTRY_ALIAS_TYPES = {'TranscriptId', 'TranscriptSchema', 'CreditId', 'M365Title'}
_IDENTITY_COLUMNS = [
    'conversation_natural_key', 'canonical_agent_key', 'canonical_agent_name',
    'canonical_environment_key', 'agent_mapping_status', 'raw_agent_id',
    'raw_agent_schema', 'raw_agent_name', 'raw_environment', 'source_environment']

def _registry_bool(value, field):
    normalized = str(value or '').strip().casefold()
    if normalized in {'true', '1', 'yes'}:
        return True
    if normalized in {'false', '0', 'no'}:
        return False
    raise ValueError(f'{field} must be true or false, not {value!r}')

def normalize_agent_alias(alias_type, value):
    normalized = str(value or '').strip()
    if alias_type in {'TranscriptId', 'CreditId'}:
        normalized = normalized.strip('{}')
        if alias_type == 'CreditId' and normalized.casefold().startswith('p_'):
            normalized = normalized[2:]
    return normalized.casefold()

def load_agent_registry(path):
    try:
        with open(path, 'r', encoding='utf-8-sig', newline='') as handle:
            reader = _registry_csv.DictReader(handle)
            if not reader.fieldnames:
                raise ValueError(f'Agent registry has no header: {path}')
            missing = sorted(_REGISTRY_COLUMNS - set(reader.fieldnames))
            if missing:
                raise ValueError(f'Agent registry is missing columns: {missing}')
            source_rows = list(reader)
    except FileNotFoundError as error:
        raise ValueError(f'Agent registry not found: {path}') from error

    rows, metadata_by_key, aliases = [], {}, {}
    for row_number, row in enumerate(source_rows, start=2):
        version = str(row.get('RegistryVersion') or '').strip()
        agent_key = str(row.get('AgentKey') or '').strip()
        agent_label = str(row.get('AgentLabel') or '').strip()
        alias_type = str(row.get('AliasType') or '').strip()
        alias_value = str(row.get('AliasValue') or '').strip()
        environment_key = str(row.get('EnvironmentKey') or '').strip()
        if version != '1':
            raise ValueError(
                f'Agent registry row {row_number} has unsupported version {version!r}')
        if not agent_key or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._:-]*', agent_key):
            raise ValueError(f'Agent registry row {row_number} has invalid AgentKey')
        if not agent_label:
            raise ValueError(f'Agent registry row {row_number} has no AgentLabel')
        if alias_type not in _REGISTRY_ALIAS_TYPES:
            raise ValueError(f'Agent registry row {row_number} has invalid AliasType')
        alias_normalized = normalize_agent_alias(alias_type, alias_value)
        if not alias_normalized:
            raise ValueError(f'Agent registry row {row_number} has no AliasValue')
        normalized = {
            'RegistryVersion': '1',
            'AgentKey': agent_key,
            'AgentLabel': agent_label,
            'IsEss': _registry_bool(row.get('IsEss'), 'IsEss'),
            'Selected': _registry_bool(row.get('Selected'), 'Selected'),
            'Enabled': _registry_bool(row.get('Enabled'), 'Enabled'),
            'EnvironmentKey': environment_key,
            'EnvironmentName': str(row.get('EnvironmentName') or '').strip(),
            'EnvironmentUrl': str(row.get('EnvironmentUrl') or '').strip(),
            'AliasType': alias_type,
            'AliasValue': alias_value,
            'AliasValueNormalized': alias_normalized,
        }
        metadata = (
            normalized['AgentLabel'], normalized['IsEss'],
            normalized['Selected'], normalized['Enabled'])
        old_metadata = metadata_by_key.setdefault(agent_key.casefold(), metadata)
        if old_metadata != metadata:
            raise ValueError(
                f'Agent registry has conflicting metadata for AgentKey {agent_key!r}')
        alias_key = (
            environment_key.casefold(), alias_type.casefold(), alias_normalized)
        old_key = aliases.setdefault(alias_key, agent_key)
        if old_key.casefold() != agent_key.casefold():
            raise ValueError(
                'Agent registry alias maps to multiple agents: '
                f'{environment_key or "*"} / {alias_type} / {alias_value}')
        rows.append(normalized)
    if not rows:
        raise ValueError('Agent registry has no rows')
    return rows

def active_agent_keys(rows, scope_mode):
    if scope_mode not in _AGENT_SCOPE_MODES:
        raise ValueError(
            'AGENT_SCOPE_MODE must be exactly one of: ESS Safe, Selected Agents, All Agents')
    keys = {
        row['AgentKey'] for row in rows
        if row['Enabled']
        and (scope_mode != 'ESS Safe' or row['IsEss'])
        and (scope_mode != 'Selected Agents' or row['Selected'])
    }
    if scope_mode != 'All Agents' and not keys:
        raise ValueError(
            f'Agent registry has no enabled agents for scope mode {scope_mode!r}')
    return keys

def registry_environment_key(rows, raw_environment):
    raw = str(raw_environment or '').strip().rstrip('/').casefold()
    if not raw:
        return ''
    keys = {
        row['EnvironmentKey'] for row in rows
        if row['Enabled'] and any(
            raw == str(row[field] or '').strip().rstrip('/').casefold()
            for field in ('EnvironmentKey', 'EnvironmentName', 'EnvironmentUrl'))
    }
    if len(keys) > 1:
        raise ValueError(f'Agent registry environment is ambiguous: {raw_environment!r}')
    return next(iter(keys), '')

def resolve_registry_alias(rows, alias_type, alias_value, active_keys=None, environment_key=''):
    normalized = normalize_agent_alias(alias_type, alias_value)
    if not normalized:
        return None
    candidates = [
        row for row in rows
        if row['Enabled']
        and row['AliasType'] == alias_type
        and row['AliasValueNormalized'] == normalized
        and (active_keys is None or row['AgentKey'] in active_keys)
    ]
    environment = str(environment_key or '').strip().casefold()
    if environment:
        exact = [
            row for row in candidates
            if row['EnvironmentKey'].casefold() == environment]
        candidates = exact or [
            row for row in candidates if not row['EnvironmentKey']]
    keys = {row['AgentKey'] for row in candidates}
    if len(keys) > 1:
        raise ValueError(
            f'Agent alias is ambiguous without an environment: {alias_type} / {alias_value}')
    return candidates[0] if candidates else None

def _raw_canonical_key(kind, value, raw_environment=''):
    normalized = normalize_agent_alias(kind, value)
    material = (
        f'{str(raw_environment or "").strip().casefold()}|'
        f'{kind.casefold()}|{normalized}')
    digest = _registry_hashlib.sha256(material.encode('utf-8')).hexdigest()[:24]
    return f'raw:{kind.casefold()}:{digest}'

def _raw_environment_key(raw_environment):
    value = str(raw_environment or '').strip()
    return _raw_canonical_key('Environment', value) if value else ''

def _clean_raw_identity(value, max_length=256):
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ''
    value = str(value).strip()
    if not value or len(value) > max_length:
        return ''
    if any(char in value for char in ('{', '}', '"', '\n', '\t', '<', '>', '[', ']')):
        return ''
    return value

def _clean_raw_id(value):
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ''
    value = str(value).strip()
    if value.startswith('{') and value.endswith('}'):
        value = value[1:-1].strip()
    return _clean_raw_identity(value)

def _extract_transcript_identity(row):
    raw_schema = _clean_raw_identity(row.get('agent_schema_hint'), 128)
    raw_id = raw_name = ''
    transcript_metadata = row.get('metadata')
    if isinstance(transcript_metadata, str) and transcript_metadata.strip():
        try:
            transcript_metadata = json.loads(transcript_metadata)
        except Exception:
            transcript_metadata = {}
    if isinstance(transcript_metadata, dict):
        raw_id = (
            _clean_raw_id(transcript_metadata.get('BotId'))
            or _clean_raw_id(transcript_metadata.get('botId')))
        raw_name = (
            _clean_raw_identity(transcript_metadata.get('BotName'))
            or _clean_raw_identity(transcript_metadata.get('botName')))
        raw_schema = (
            raw_schema
            or _clean_raw_identity(transcript_metadata.get('BotSchemaName'), 128)
            or _clean_raw_identity(transcript_metadata.get('SchemaName'), 128)
            or _clean_raw_identity(transcript_metadata.get('botSchemaName'), 128))
    nested = row.get('bot_conversationtranscriptid')
    if isinstance(nested, dict):
        raw_schema = raw_schema or _clean_raw_identity(nested.get('schemaname'), 128)
        raw_id = _clean_raw_id(nested.get('botid'))
        raw_name = _clean_raw_identity(nested.get('name'))
    for column in ('bot_conversationtranscriptid.botid', 'botid', 'bot_botid'):
        raw_id = raw_id or _clean_raw_id(row.get(column))
    for column in ('bot_conversationtranscriptid.name', 'bot_name', 'name'):
        raw_name = raw_name or _clean_raw_identity(row.get(column))
    activities = row.get('content_json')
    if isinstance(activities, dict):
        activities = next(
            (activities[key] for key in ('activities', 'Activities', 'transcript', 'messages')
             if isinstance(activities.get(key), list)), [])
    if not isinstance(activities, list):
        activities = []
    for activity in activities:
        if not isinstance(activity, dict):
            continue
        value = activity.get('value') if isinstance(activity.get('value'), dict) else {}
        raw_schema = (
            raw_schema
            or _clean_raw_identity(value.get('parentBotSchemaName'), 128)
            or _clean_raw_identity(value.get('botSchemaName'), 128))
        if activity.get('type') == 'message':
            sender = activity.get('from') if isinstance(activity.get('from'), dict) else {}
            recipient = (
                activity.get('recipient')
                if isinstance(activity.get('recipient'), dict) else {})
            bot_party = sender if sender.get('role') in (0, 'bot') else recipient
            raw_id = raw_id or _clean_raw_id(bot_party.get('id'))
            raw_name = raw_name or _clean_raw_identity(bot_party.get('name'))
    return raw_id, raw_schema, raw_name

def resolve_transcript_agent(row, registry_rows, active_keys, scope_mode):
    raw_id, raw_schema, raw_name = _extract_transcript_identity(row)
    raw_environment = _clean_raw_identity(row.get('SourceEnvironment'))
    environment_key = registry_environment_key(registry_rows, raw_environment)
    match = (
        resolve_registry_alias(
            registry_rows, 'TranscriptId', raw_id, active_keys, environment_key)
        or resolve_registry_alias(
            registry_rows, 'TranscriptSchema', raw_schema, active_keys, environment_key)
    )
    if match:
        canonical_environment = (
            match['EnvironmentKey'] or environment_key
            or _raw_environment_key(raw_environment))
        return {
            'canonical_agent_key': match['AgentKey'],
            'canonical_agent_name': match['AgentLabel'],
            'canonical_environment_key': canonical_environment,
            'agent_mapping_status': 'RegistryMapped',
            'raw_agent_id': raw_id,
            'raw_agent_schema': raw_schema,
            'raw_agent_name': raw_name,
            'raw_environment': raw_environment,
            'source_environment': raw_environment,
        }
    if scope_mode != 'All Agents':
        return None
    raw_kind, raw_value = (
        ('TranscriptId', raw_id) if raw_id
        else ('TranscriptSchema', raw_schema) if raw_schema
        else ('TranscriptName', raw_name) if raw_name
        else ('TranscriptUnknown', row.get('conversationtranscriptid')))
    return {
        'canonical_agent_key': _raw_canonical_key(
            raw_kind, raw_value, raw_environment),
        'canonical_agent_name': raw_name or raw_schema or raw_id or 'Unknown agent',
        'canonical_environment_key': (
            environment_key or _raw_environment_key(raw_environment)),
        'agent_mapping_status': 'RawAllAgents',
        'raw_agent_id': raw_id,
        'raw_agent_schema': raw_schema,
        'raw_agent_name': raw_name,
        'raw_environment': raw_environment,
        'source_environment': raw_environment,
    }

def scope_transcript_rows(frame, registry_rows, scope_mode):
    active_keys = active_agent_keys(registry_rows, scope_mode)
    scoped_rows = []
    for _, row in frame.iterrows():
        identity = resolve_transcript_agent(
            row, registry_rows, active_keys, scope_mode)
        if identity is None:
            continue
        item = row.copy()
        for key, value in identity.items():
            item[key] = value
        conversation_id = str(row.get('conversationtranscriptid') or '').strip()
        item['conversation_natural_key'] = (
            f'{identity["canonical_environment_key"]}|{conversation_id}')
        scoped_rows.append(item)
    if scope_mode != 'All Agents' and len(frame) and not scoped_rows:
        raise ValueError(
            f'No transcript agents matched AGENT_SCOPE_MODE={scope_mode!r}')
    result = pd.DataFrame(
        scoped_rows,
        columns=list(dict.fromkeys(list(frame.columns) + _IDENTITY_COLUMNS)))
    if len(result) and result['conversation_natural_key'].duplicated().any():
        duplicates = sorted(
            result.loc[
                result['conversation_natural_key'].duplicated(keep=False),
                'conversation_natural_key'].astype(str).unique().tolist())
        raise ValueError(
            'Transcript source contains duplicate environment-aware conversation keys: '
            + ', '.join(duplicates[:10]))
    return result, active_keys

AGENT_REGISTRY_ROWS = load_agent_registry(AGENT_REGISTRY_FILE)
parsed, ACTIVE_AGENT_KEYS = scope_transcript_rows(
    parsed, AGENT_REGISTRY_ROWS, AGENT_SCOPE_MODE)
print(
    f'agent registry scope: {AGENT_SCOPE_MODE}; '
    f'{len(ACTIVE_AGENT_KEYS):,} active agent(s); {len(parsed):,} scoped transcript(s)')
# === END AGENT REGISTRY RUNTIME ===
'''

SUBAGENT_SUMMARY = r'''def summarize_subagents(subagent_frame):
    columns = [
        'conversation_natural_key', 'parent_agent_name', 'parent_agent_id',
        'child_agent_names', 'child_agent_schema_names', 'child_agent_ids',
        'child_agent_invocation_states', 'child_agent_dialogs', 'child_agent_plan_steps',
        'child_agent_invocation_count', 'child_agent_count', 'has_child_agent',
        'child_agent_detail']
    if subagent_frame.empty:
        return pd.DataFrame(columns=columns)

    def _present(value):
        return pd.notna(value) and str(value).strip() != ''

    def _first_present(*values):
        return next((value for value in values if _present(value)), None)

    def _join(values):
        return ' | '.join(dict.fromkeys(str(value) for value in values if _present(value)))

    summaries = []
    for conversation_key, group in subagent_frame.groupby(
            'conversation_natural_key', dropna=False):
        group = group.copy()
        first = group.iloc[0]
        initialize_sequence = completed_sequence = 0
        fallback_keys = []
        for event_type in group['event_type'].tolist():
            if event_type == 'initialize':
                initialize_sequence += 1
                fallback_keys.append(f'sequence:{initialize_sequence}')
            else:
                completed_sequence += 1
                fallback_keys.append(f'sequence:{completed_sequence}')
        group['_fallback_invocation_key'] = fallback_keys

        def _invocation_key(row):
            plan_step = _first_present(row.get('plan_step_id'))
            return f'plan:{plan_step}' if plan_step else row.get('_fallback_invocation_key')

        invocation_keys = list(dict.fromkeys(
            key for key in group.apply(_invocation_key, axis=1).tolist() if key))
        identities, details = [], []
        for invocation_key in invocation_keys:
            matching = group[group.apply(_invocation_key, axis=1) == invocation_key]
            identity = _first_present(
                *matching['connected_agent_schema'].tolist(),
                *matching['connected_agent_id'].tolist(),
                *matching['connected_agent_name'].tolist())
            if identity and identity not in identities:
                identities.append(identity)
            completed = matching[matching['event_type'] == 'completed']
            chosen = completed.iloc[-1] if not completed.empty else matching.iloc[-1]
            names = [
                value for value in matching['connected_agent_name'].tolist()
                if _present(value)]
            label = names[-1] if names else _first_present(
                chosen.get('connected_agent_schema'),
                chosen.get('connected_agent_id'), identity)
            details.append(
                f'{label} ({chosen.get("invocation_state") or chosen.get("event_type")})')
        summaries.append({
            'conversation_natural_key': conversation_key,
            'parent_agent_name': first.get('parent_agent_name'),
            'parent_agent_id': first.get('parent_agent_id'),
            'child_agent_names': _join(group['connected_agent_name']),
            'child_agent_schema_names': _join(group['connected_agent_schema']),
            'child_agent_ids': _join(group['connected_agent_id']),
            'child_agent_invocation_states': _join(group['invocation_state']),
            'child_agent_dialogs': _join(group['dialog_schema']),
            'child_agent_plan_steps': _join(group['plan_step_id']),
            'child_agent_invocation_count': len(invocation_keys),
            'child_agent_count': len(identities),
            'has_child_agent': bool(identities),
            'child_agent_detail': '; '.join(details),
        })
    return pd.DataFrame(summaries, columns=columns)

'''

AGENT_CATALOGUE_CELL = r'''# Registry-backed conformed agent dimension.
def build_agent_dim(session_frame, registry_rows):
    columns = [
        'canonical_agent_key', 'canonical_agent_name', 'canonical_environment_key',
        'agent_schema', 'agent_display_name', 'agent_class', 'raw_agent_id',
        'raw_agent_schema', 'raw_agent_name', 'agent_mapping_status',
        'source_environments']
    if session_frame.empty:
        return pd.DataFrame(columns=columns)
    metadata = {}
    for row in registry_rows:
        metadata.setdefault(row['AgentKey'], row)
    records = []
    for agent_key, group in session_frame.groupby(
            'canonical_agent_key', dropna=False, sort=True):
        first = group.iloc[0]
        registry = metadata.get(agent_key)
        environments = sorted({
            str(value) for value in group['canonical_environment_key']
            if pd.notna(value) and str(value)})
        source_environments = sorted({
            str(value) for value in group['source_environment']
            if pd.notna(value) and str(value)})
        agent_name = (
            registry['AgentLabel'] if registry
            else str(first.get('canonical_agent_name') or agent_key))
        records.append({
            'canonical_agent_key': agent_key,
            'canonical_agent_name': agent_name,
            'canonical_environment_key': '|'.join(environments),
            'agent_schema': first.get('raw_agent_schema'),
            'agent_display_name': agent_name,
            'agent_class': (
                'ESS' if registry and registry['IsEss']
                else 'Registry' if registry else 'Raw (All Agents)'),
            'raw_agent_id': first.get('raw_agent_id'),
            'raw_agent_schema': first.get('raw_agent_schema'),
            'raw_agent_name': first.get('raw_agent_name'),
            'agent_mapping_status': first.get('agent_mapping_status'),
            'source_environments': '|'.join(source_environments),
        })
    result = pd.DataFrame(records, columns=columns)
    if result['canonical_agent_key'].isna().any():
        raise ValueError('Agent catalogue contains a null canonical_agent_key')
    if result['canonical_agent_key'].duplicated().any():
        raise ValueError('Agent catalogue contains duplicate canonical_agent_key values')
    return result

agent_dim = build_agent_dim(sessions, AGENT_REGISTRY_ROWS)
print(f'unique canonical agents: {len(agent_dim):,}')
'''

SCOPE_CELL = r'''# Agent scope is applied to parsed transcripts before any facts or dimensions are built.
if len(sessions) and not sessions['canonical_agent_key'].notna().all():
    raise ValueError('Scoped sessions contain a missing canonical_agent_key')
print(f'agent registry scope already applied: sessions={len(sessions):,}, subagents={len(subagents):,}')
'''

FEEDBACK_BLOCK = r'''# --- Unified feedback events: transcript reactions + registry-mapped external exports ---
_USER_FEEDBACK_COLUMNS = [
    'Feedback Id', 'Comment', 'Translated Comment', 'Comment Language', 'Date Submitted UTC',
    'Feedback Type', 'Microsoft Response Status', 'App', 'App Language', 'Platform', 'Source Type',
    'Logs, Attachments', 'User Id', 'User Email', 'Browser', 'Browser Version', 'AI Context Prompt',
    'AI Context Response Message', 'Survey Question', 'Survey Response Option', 'Additional Metadata',
    'Date Submitted Date', 'Sentiment', 'Feedback Event Key', 'Conversation Id', 'Agent Id', 'Channel',
    'Feedback Source', 'Feedback Verdict', 'Match Status', 'canonical_agent_key',
    'canonical_agent_name', 'canonical_environment_key', 'agent_mapping_status',
    'raw_agent_id', 'raw_agent_schema', 'raw_agent_name', 'source_environment'
]
_FEEDBACK_QUARANTINE_COLUMNS = [
    'Feedback Event Key', 'Feedback Id', 'Conversation Id', 'Agent Id', 'Channel',
    'Feedback Source', 'Match Status', 'canonical_agent_key', 'canonical_agent_name',
    'canonical_environment_key', 'agent_mapping_status', 'raw_agent_id',
    'raw_agent_schema', 'raw_agent_name'
]

def _feedback_metadata(conversation_id, agent_id, agent_name, channel, existing=''):
    if existing:
        return existing
    return json.dumps({
        'conversationId': conversation_id or '',
        'essAgentId': agent_id or '',
        'aiAgents': [{'Name': agent_name or '', 'Type': 'Custom'}],
        'copilotType': 'm365' if channel == 'Microsoft 365 Copilot Chat' else 'custom',
        'UiHost': channel or '',
    }, ensure_ascii=False)

def _registry_key_match(value, registry_rows, active_keys):
    normalized = str(value or '').strip().casefold()
    matches = [
        row for row in registry_rows
        if row['Enabled']
        and row['AgentKey'] in active_keys
        and row['AgentKey'].casefold() == normalized]
    if not matches:
        return None
    result = dict(matches[0])
    environment_values = [
        str(row.get('EnvironmentKey') or '').strip() for row in matches]
    environments = set(environment_values)
    result['EnvironmentKey'] = (
        next(iter(environments))
        if all(environment_values) and len(environments) == 1
        else '')
    return result

def resolve_external_feedback_agent(
        item, session_frame, registry_rows, active_keys):
    raw_agent_id = str(item.get('AgentId') or '').strip()
    raw_agent_name = str(item.get('AgentName') or '').strip()
    match = (
        _registry_key_match(raw_agent_id, registry_rows, active_keys)
        or resolve_registry_alias(
            registry_rows, 'M365Title', raw_agent_id, active_keys))
    matched_session = None
    conversation_id = str(item.get('ConversationId') or '').strip()
    if conversation_id:
        candidates = session_frame[
            session_frame['conversation_id'].astype(str) == conversation_id]
        candidates = candidates[
            candidates['agent_mapping_status'].astype(str) == 'RegistryMapped']
        if match is not None:
            candidates = candidates[
                candidates['canonical_agent_key'].astype(str) == match['AgentKey']]
            registry_environment = str(match.get('EnvironmentKey') or '').strip()
            if registry_environment:
                candidates = candidates[
                    candidates['canonical_environment_key'].astype(str)
                    == registry_environment]
        if len(candidates) == 1:
            matched_session = candidates.iloc[0]
            if match is None:
                match = _registry_key_match(
                    matched_session.get('canonical_agent_key'),
                    registry_rows, active_keys)
    if match is None:
        return None, matched_session
    environment = match['EnvironmentKey']
    if matched_session is not None:
        environment = (
            str(matched_session.get('canonical_environment_key') or '')
            or environment)
    return {
        'canonical_agent_key': match['AgentKey'],
        'canonical_agent_name': match['AgentLabel'],
        'canonical_environment_key': environment,
        'agent_mapping_status': 'RegistryMapped',
        'raw_agent_id': raw_agent_id,
        'raw_agent_schema': '',
        'raw_agent_name': raw_agent_name,
        'source_environment': (
            str(matched_session.get('source_environment') or '')
            if matched_session is not None else ''),
    }, matched_session

def build_user_feedback(session_frame, external_path):
    rows, quarantine = [], []

    def _text(value):
        return '' if value is None or pd.isna(value) else str(value)

    from pathlib import Path as _Path
    if external_path and _Path(external_path).exists():
        external = pd.read_csv(external_path, keep_default_na=False)
        required = {
            'FeedbackEventId', 'ConversationId', 'AgentId', 'AgentName', 'Channel',
            'FeedbackSource', 'FeedbackVerdict', 'FeedbackComment', 'SubmittedUtc',
            'UserId', 'UserEmail', 'Prompt', 'Response', 'App', 'AppLanguage',
            'Platform', 'SourceType', 'AdditionalMetadata', 'MatchStatus'}
        missing = sorted(required - set(external.columns))
        if missing:
            raise ValueError(f'Feedback events file is missing columns: {missing}')
        for _, item in external.iterrows():
            conversation_id = _text(item.get('ConversationId')).strip()
            event_id = (
                _text(item.get('FeedbackEventId')).strip()
                or f'{conversation_id}|{_text(item.get("FeedbackVerdict"))}')
            event_key = f'External|{event_id}'
            identity, matched = resolve_external_feedback_agent(
                item, session_frame, AGENT_REGISTRY_ROWS, ACTIVE_AGENT_KEYS)
            if identity is None:
                quarantine.append({
                    'Feedback Event Key': event_key,
                    'Feedback Id': event_id,
                    'Conversation Id': conversation_id,
                    'Agent Id': _text(item.get('AgentId')),
                    'Channel': _text(item.get('Channel')) or 'Unknown',
                    'Feedback Source': _text(item.get('FeedbackSource')),
                    'Match Status': 'UnmappedRegistryAgent',
                    'canonical_agent_key': '',
                    'canonical_agent_name': '',
                    'canonical_environment_key': '',
                    'agent_mapping_status': 'UnmappedQuarantined',
                    'raw_agent_id': _text(item.get('AgentId')),
                    'raw_agent_schema': '',
                    'raw_agent_name': _text(item.get('AgentName')),
                })
                continue
            agent_id = identity['canonical_agent_key']
            agent_name = identity['canonical_agent_name']
            channel = _text(item.get('Channel')) or 'Unknown'
            metadata = _feedback_metadata(
                conversation_id, agent_id, agent_name, channel,
                _text(item.get('AdditionalMetadata')))
            row = {
                'Feedback Id': event_id,
                'Comment': _text(item.get('FeedbackComment')),
                'Translated Comment': '',
                'Comment Language': '',
                'Date Submitted UTC': _text(item.get('SubmittedUtc')),
                'Feedback Type': _text(item.get('FeedbackVerdict')),
                'Microsoft Response Status': 'Completed',
                'App': _text(item.get('App')) or agent_name,
                'App Language': _text(item.get('AppLanguage')),
                'Platform': _text(item.get('Platform')) or channel,
                'Source Type': _text(item.get('SourceType')),
                'Logs, Attachments': '',
                'User Id': _text(item.get('UserId')),
                'User Email': _text(item.get('UserEmail')),
                'Browser': '',
                'Browser Version': '',
                'AI Context Prompt': _text(item.get('Prompt')),
                'AI Context Response Message': _text(item.get('Response')),
                'Survey Question': '',
                'Survey Response Option': '',
                'Additional Metadata': metadata,
                'Date Submitted Date': _text(item.get('SubmittedUtc'))[:10],
                'Sentiment': _text(item.get('FeedbackVerdict')),
                'Feedback Event Key': event_key,
                'Conversation Id': conversation_id,
                'Agent Id': agent_id,
                'Channel': channel,
                'Feedback Source': _text(item.get('FeedbackSource')),
                'Feedback Verdict': _text(item.get('FeedbackVerdict')),
                'Match Status': (
                    'Exact conversation match' if matched is not None
                    else 'Registry agent match'),
                '_conversation_natural_key': (
                    _text(matched.get('conversation_natural_key'))
                    if matched is not None else ''),
                '_source_rank': 0,
            }
            row.update(identity)
            rows.append(row)
    elif external_path:
        print(f'External feedback events not found at {external_path}; using transcript reactions only.')

    for _, item in session_frame.iterrows():
        verdict = _text(item.get('feedback_verdict')).strip()
        if not verdict:
            continue
        display_verdict = (
            'Thumbs Up' if verdict == 'Positive'
            else 'Thumbs Down' if verdict == 'Negative' else verdict)
        conversation_id = _text(item.get('conversation_id'))
        agent_id = _text(item.get('canonical_agent_key'))
        agent_name = _text(item.get('canonical_agent_name'))
        submitted = _text(item.get('session_start_utc'))
        row = {
            'Feedback Id': conversation_id,
            'Comment': _text(item.get('feedback_comment')),
            'Translated Comment': '',
            'Comment Language': '',
            'Date Submitted UTC': submitted,
            'Feedback Type': display_verdict,
            'Microsoft Response Status': 'Completed',
            'App': agent_name,
            'App Language': _text(item.get('locale')),
            'Platform': 'Copilot Studio',
            'Source Type': 'Conversation Transcript',
            'Logs, Attachments': '',
            'User Id': _text(item.get('user_id_hash')),
            'User Email': '',
            'Browser': '',
            'Browser Version': '',
            'AI Context Prompt': _text(item.get('first_user_prompt')),
            'AI Context Response Message': '',
            'Survey Question': '',
            'Survey Response Option': '',
            'Additional Metadata': _feedback_metadata(
                conversation_id, agent_id, agent_name, 'Copilot Studio'),
            'Date Submitted Date': submitted[:10],
            'Sentiment': (
                'Positive' if display_verdict == 'Thumbs Up'
                else 'Negative' if display_verdict == 'Thumbs Down'
                else display_verdict),
            'Feedback Event Key': (
                f'Transcript|{item.get("conversation_natural_key")}|'
                f'{display_verdict.lower()}'),
            'Conversation Id': conversation_id,
            'Agent Id': agent_id,
            'Channel': 'Copilot Studio',
            'Feedback Source': 'Conversation Transcript',
            'Feedback Verdict': display_verdict,
            'Match Status': 'Native transcript',
            'canonical_agent_key': agent_id,
            'canonical_agent_name': agent_name,
            'canonical_environment_key': _text(item.get('canonical_environment_key')),
            'agent_mapping_status': _text(item.get('agent_mapping_status')),
            'raw_agent_id': _text(item.get('raw_agent_id')),
            'raw_agent_schema': _text(item.get('raw_agent_schema')),
            'raw_agent_name': _text(item.get('raw_agent_name')),
            'source_environment': _text(item.get('source_environment')),
            '_conversation_natural_key': _text(
                item.get('conversation_natural_key')),
            '_source_rank': 1,
        }
        rows.append(row)

    if rows:
        frame = pd.DataFrame(rows)
        external_rows = (
            frame[frame['_source_rank'] == 0]
            .drop_duplicates('Feedback Event Key', keep='first'))
        transcript_rows = frame[frame['_source_rank'] == 1].copy()
        external_pairs = {
            (str(row['_conversation_natural_key']).casefold(),
             str(row['canonical_agent_key']).casefold(),
             str(row['Feedback Verdict']).casefold())
            for _, row in external_rows.iterrows()
            if str(row['Match Status']) == 'Exact conversation match'
            and str(row['_conversation_natural_key'] or '')}
        transcript_rows = transcript_rows[
            ~transcript_rows.apply(
                lambda row: (
                    str(row['_conversation_natural_key']).casefold(),
                    str(row['canonical_agent_key']).casefold(),
                    str(row['Feedback Verdict']).casefold()) in external_pairs,
                axis=1)]
        user_feedback = pd.concat(
            [external_rows, transcript_rows], ignore_index=True)
        user_feedback = user_feedback[_USER_FEEDBACK_COLUMNS].reset_index(drop=True)
    else:
        user_feedback = pd.DataFrame(columns=_USER_FEEDBACK_COLUMNS)
    feedback_quarantine = (
        pd.DataFrame(quarantine, columns=_FEEDBACK_QUARANTINE_COLUMNS)
        .drop_duplicates('Feedback Event Key', keep='first')
        .reset_index(drop=True))
    return user_feedback, feedback_quarantine

user_feedback, user_feedback_quarantine = build_user_feedback(
    sessions, FEEDBACK_EVENTS_FILE)
print(
    f'unified feedback events: {len(user_feedback):,}; '
    f'quarantined identifiers: {len(user_feedback_quarantine):,}')
'''

CREDIT_HELPERS = r'''import os, glob, re, datetime, csv, hashlib
from pyspark.sql import functions as F

_LOAD_TS = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
_SCOPE_MODES = {'ESS Safe', 'Selected Agents', 'All Agents'}
_ALIAS_TYPES = {'TranscriptId', 'TranscriptSchema', 'CreditId', 'M365Title'}
_REGISTRY_COLUMNS = {
    'RegistryVersion', 'AgentKey', 'AgentLabel', 'IsEss', 'Selected', 'Enabled',
    'EnvironmentKey', 'EnvironmentName', 'EnvironmentUrl', 'AliasType', 'AliasValue'}

def _local(path):
    return path if path.startswith('/') else f'/lakehouse/default/{path}'

def _table(name):
    return f'{OUTPUT_PREFIX}.{name}' if OUTPUT_PREFIX else name

def _list_matches(pattern):
    rx = re.compile('^' + re.escape(pattern).replace('\\*', '.*') + '$', re.IGNORECASE)
    try:
        entries = notebookutils.fs.ls(SOURCE_DIR)
    except Exception:
        return []
    hits = [
        entry.name for entry in entries
        if not entry.isDir and rx.match(entry.name) and entry.name.lower().endswith('.csv')]
    return [f'{SOURCE_DIR}/{name}' for name in sorted(hits)]

def _read_csv(path):
    return (spark.read.option('header', True).option('multiLine', True)
            .option('escape', '"').option('encoding', 'UTF-8').csv(path))

_INVALID = re.compile(r'[ ,;{}()\n\t=/-]')
def _sanitize(df):
    return df.toDF(*[_INVALID.sub('_', column.lstrip('\ufeff')) for column in df.columns])

def normalize_agent_alias(alias_type, value):
    normalized = str(value or '').strip()
    if alias_type in {'TranscriptId', 'CreditId'}:
        normalized = normalized.strip('{}')
        if alias_type == 'CreditId' and normalized.casefold().startswith('p_'):
            normalized = normalized[2:]
    return normalized.casefold()

def _registry_bool(value, field):
    normalized = str(value or '').strip().casefold()
    if normalized in {'true', '1', 'yes'}:
        return True
    if normalized in {'false', '0', 'no'}:
        return False
    raise ValueError(f'{field} must be true or false, not {value!r}')

def load_agent_registry(path):
    try:
        with open(path, 'r', encoding='utf-8-sig', newline='') as handle:
            reader = csv.DictReader(handle)
            if not reader.fieldnames:
                raise ValueError(f'Agent registry has no header: {path}')
            missing = sorted(_REGISTRY_COLUMNS - set(reader.fieldnames))
            if missing:
                raise ValueError(f'Agent registry is missing columns: {missing}')
            source_rows = list(reader)
    except FileNotFoundError as error:
        raise ValueError(f'Agent registry not found: {path}') from error
    rows, metadata_by_key, aliases = [], {}, {}
    for row_number, row in enumerate(source_rows, start=2):
        version = str(row.get('RegistryVersion') or '').strip()
        agent_key = str(row.get('AgentKey') or '').strip()
        agent_label = str(row.get('AgentLabel') or '').strip()
        alias_type = str(row.get('AliasType') or '').strip()
        alias_value = str(row.get('AliasValue') or '').strip()
        environment_key = str(row.get('EnvironmentKey') or '').strip()
        if version != '1':
            raise ValueError(
                f'Agent registry row {row_number} has unsupported version {version!r}')
        if not agent_key or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._:-]*', agent_key):
            raise ValueError(f'Agent registry row {row_number} has invalid AgentKey')
        if not agent_label or alias_type not in _ALIAS_TYPES:
            raise ValueError(f'Agent registry row {row_number} is invalid')
        alias_normalized = normalize_agent_alias(alias_type, alias_value)
        if not alias_normalized:
            raise ValueError(f'Agent registry row {row_number} has no AliasValue')
        normalized = {
            'RegistryVersion': '1', 'AgentKey': agent_key,
            'AgentLabel': agent_label,
            'IsEss': _registry_bool(row.get('IsEss'), 'IsEss'),
            'Selected': _registry_bool(row.get('Selected'), 'Selected'),
            'Enabled': _registry_bool(row.get('Enabled'), 'Enabled'),
            'EnvironmentKey': environment_key,
            'EnvironmentName': str(row.get('EnvironmentName') or '').strip(),
            'EnvironmentUrl': str(row.get('EnvironmentUrl') or '').strip(),
            'AliasType': alias_type, 'AliasValue': alias_value,
            'AliasValueNormalized': alias_normalized}
        metadata = (
            normalized['AgentLabel'], normalized['IsEss'],
            normalized['Selected'], normalized['Enabled'])
        if metadata_by_key.setdefault(agent_key.casefold(), metadata) != metadata:
            raise ValueError(
                f'Agent registry has conflicting metadata for AgentKey {agent_key!r}')
        alias_key = (
            environment_key.casefold(), alias_type.casefold(), alias_normalized)
        if aliases.setdefault(alias_key, agent_key).casefold() != agent_key.casefold():
            raise ValueError(
                'Agent registry alias maps to multiple agents: '
                f'{environment_key or "*"} / {alias_type} / {alias_value}')
        rows.append(normalized)
    if not rows:
        raise ValueError('Agent registry has no rows')
    return rows

def active_agent_keys(rows, scope_mode):
    if scope_mode not in _SCOPE_MODES:
        raise ValueError(
            'AGENT_SCOPE_MODE must be exactly one of: ESS Safe, Selected Agents, All Agents')
    keys = {
        row['AgentKey'] for row in rows
        if row['Enabled']
        and (scope_mode != 'ESS Safe' or row['IsEss'])
        and (scope_mode != 'Selected Agents' or row['Selected'])}
    if scope_mode != 'All Agents' and not keys:
        raise ValueError(
            f'Agent registry has no enabled agents for scope mode {scope_mode!r}')
    return keys

def registry_environment_key(rows, environment_id='', environment_name=''):
    raw_values = {
        str(value or '').strip().rstrip('/').casefold()
        for value in (environment_id, environment_name) if str(value or '').strip()}
    if not raw_values:
        return ''
    keys = {
        row['EnvironmentKey'] for row in rows
        if row['Enabled'] and any(
            str(row[field] or '').strip().rstrip('/').casefold() in raw_values
            for field in ('EnvironmentKey', 'EnvironmentName', 'EnvironmentUrl'))}
    if len(keys) > 1:
        raise ValueError(
            f'Agent registry environment is ambiguous: {environment_id!r} / {environment_name!r}')
    return next(iter(keys), '')

def resolve_registry_alias(
        rows, alias_type, alias_value, active_keys=None, environment_key=''):
    normalized = normalize_agent_alias(alias_type, alias_value)
    if not normalized:
        return None
    candidates = [
        row for row in rows
        if row['Enabled'] and row['AliasType'] == alias_type
        and row['AliasValueNormalized'] == normalized
        and (active_keys is None or row['AgentKey'] in active_keys)]
    environment = str(environment_key or '').strip().casefold()
    if environment:
        exact = [
            row for row in candidates
            if row['EnvironmentKey'].casefold() == environment]
        candidates = exact or [
            row for row in candidates if not row['EnvironmentKey']]
    keys = {row['AgentKey'] for row in candidates}
    if len(keys) > 1:
        raise ValueError(
            f'Agent alias is ambiguous without an environment: {alias_type} / {alias_value}')
    return candidates[0] if candidates else None

def _raw_key(kind, value, environment=''):
    material = (
        f'{str(environment or "").strip().casefold()}|{kind.casefold()}|'
        f'{normalize_agent_alias(kind, value)}')
    return (
        f'raw:{kind.casefold()}:'
        f'{hashlib.sha256(material.encode("utf-8")).hexdigest()[:24]}')

def resolve_credit_agent(
        agent_id, environment_id='', environment_name='',
        registry_rows=None, active_keys=None, scope_mode=None):
    registry_rows = AGENT_REGISTRY_ROWS if registry_rows is None else registry_rows
    active_keys = ACTIVE_AGENT_KEYS if active_keys is None else active_keys
    scope_mode = AGENT_SCOPE_MODE if scope_mode is None else scope_mode
    raw_id = str(agent_id or '').strip()
    raw_environment_id = str(environment_id or '').strip()
    raw_environment_name = str(environment_name or '').strip()
    environment_key = registry_environment_key(
        registry_rows, raw_environment_id, raw_environment_name)
    match = resolve_registry_alias(
        registry_rows, 'CreditId', raw_id, active_keys, environment_key)
    if match:
        return {
            'canonical_agent_key': match['AgentKey'],
            'canonical_agent_name': match['AgentLabel'],
            'canonical_environment_key': (
                match['EnvironmentKey'] if environment_key else ''),
            'agent_mapping_status': 'RegistryMapped',
            'raw_agent_id': raw_id,
            'raw_environment_id': raw_environment_id,
            'raw_environment_name': raw_environment_name}
    if scope_mode == 'All Agents' and raw_id:
        return {
            'canonical_agent_key': _raw_key(
                'CreditId', raw_id, raw_environment_id),
            'canonical_agent_name': raw_id,
            'canonical_environment_key': (
                environment_key
                or (_raw_key('Environment', raw_environment_id)
                    if raw_environment_id else '')),
            'agent_mapping_status': 'RawAllAgents',
            'raw_agent_id': raw_id,
            'raw_environment_id': raw_environment_id,
            'raw_environment_name': raw_environment_name}
    return {
        'canonical_agent_key': '',
        'canonical_agent_name': '',
        'canonical_environment_key': '',
        'agent_mapping_status': 'UnmappedQuarantined',
        'raw_agent_id': raw_id,
        'raw_environment_id': raw_environment_id,
        'raw_environment_name': raw_environment_name}

AGENT_REGISTRY_ROWS = load_agent_registry(AGENT_REGISTRY_FILE)
ACTIVE_AGENT_KEYS = active_agent_keys(AGENT_REGISTRY_ROWS, AGENT_SCOPE_MODE)
print(f'Load timestamp: {_LOAD_TS}')
print(f'Source folder : {SOURCE_DIR}  (exists: {os.path.isdir(_local(SOURCE_DIR))})')
print(
    f'Agent registry: {len(AGENT_REGISTRY_ROWS):,} aliases; '
    f'{len(ACTIVE_AGENT_KEYS):,} active agent(s); scope={AGENT_SCOPE_MODE}')
'''

CREDIT_INGEST = r'''from pyspark.sql.types import (
    StructType, StructField, StringType, DecimalType)

EMPTY_SCHEMAS = {
    'credit_consumption_tenant': [
        'BillingPlan_Id','BillingPlan_Name','Environment_Id','Environment_Name',
        'Capacity_Type','Entitled_Quantity','Prepaid_Consumed_Quantity',
        'Pay_as_you_go_Consumed_Quantity','Usage_Date'],
    'credit_consumption_agent': [
        'Agent_Name','Agent_Id','Product','AI_Feature_Billable_Feature','Billed_credit',
        'Non_billed_credit','Channel','Knowledge_Sources','Tool_Used','LLM_Model',
        'Scenario_Name','Environment_Id','Environment_Name'],
    'credit_consumption_user': [
        'User_Id','User_Email','Agent_Id','Agent_Name','Billable_credit_used',
        'Credits_used','M365_Copilot_Licensed'],
}
CANONICAL_CREDIT_COLUMNS = [
    'canonical_agent_key', 'canonical_agent_name', 'canonical_environment_key',
    'agent_mapping_status', 'raw_agent_id', 'raw_environment_id',
    'raw_environment_name']
NUMERIC_COLUMNS = {
    'credit_consumption_tenant': [
        'Entitled_Quantity','Prepaid_Consumed_Quantity',
        'Pay_as_you_go_Consumed_Quantity'],
    'credit_consumption_agent': ['Billed_credit','Non_billed_credit'],
    'credit_consumption_user': ['Billable_credit_used','Credits_used'],
}

def _empty(columns, canonical=False):
    columns = list(columns) + (CANONICAL_CREDIT_COLUMNS if canonical else [])
    if ADD_LINEAGE:
        columns += ['SourceFile', 'LoadDate']
    numeric = {column for values in NUMERIC_COLUMNS.values() for column in values}
    return spark.createDataFrame([], StructType([
        StructField(
            column,
            DecimalType(38, 6) if column in numeric else StringType(),
            True)
        for column in columns]))

def _validate_and_cast(df, logical_table, path):
    missing = sorted(set(EMPTY_SCHEMAS[logical_table]) - set(df.columns))
    if missing:
        raise ValueError(
            f'{logical_table}: matched file "{path}" is malformed; '
            'missing required column(s) after sanitization: ' + ', '.join(missing))
    for column in NUMERIC_COLUMNS[logical_table]:
        df = df.withColumn(column, F.col(column).cast(DecimalType(38, 6)))
    return df

_identity_schema = StructType([
    StructField(column, StringType(), True)
    for column in CANONICAL_CREDIT_COLUMNS])

def _map_credit_rows(df, logical_table):
    if logical_table == 'credit_consumption_tenant':
        return df, None
    has_environment = logical_table == 'credit_consumption_agent'
    resolver = F.udf(
        lambda agent_id, environment_id, environment_name: resolve_credit_agent(
            agent_id, environment_id, environment_name),
        _identity_schema)
    environment_id = (
        F.col('Environment_Id') if has_environment else F.lit(''))
    environment_name = (
        F.col('Environment_Name') if has_environment else F.lit(''))
    mapped = df.withColumn(
        '_agent_identity',
        resolver(F.col('Agent_Id'), environment_id, environment_name))
    for column in CANONICAL_CREDIT_COLUMNS:
        mapped = mapped.withColumn(
            column, F.col(f'_agent_identity.{column}'))
    mapped = mapped.drop('_agent_identity')
    quarantine = (
        mapped.filter(F.col('agent_mapping_status') == 'UnmappedQuarantined')
        .select(
            F.lit(logical_table).alias('source_report'),
            'raw_agent_id', 'raw_environment_id', 'raw_environment_name',
            'agent_mapping_status'))
    curated = mapped.filter(
        F.col('agent_mapping_status') != 'UnmappedQuarantined')
    if (AGENT_SCOPE_MODE != 'All Agents'
            and df.limit(1).count() > 0
            and curated.limit(1).count() == 0):
        raise ValueError(
            f'{logical_table}: no credit agents matched '
            f'AGENT_SCOPE_MODE={AGENT_SCOPE_MODE!r}; no Delta table was changed.')
    return curated, quarantine

def _write(df, logical_table):
    table = _table(logical_table)
    (df.write.mode(WRITE_MODE)
        .option('overwriteSchema', 'true')
        .option('delta.columnMapping.mode', 'name')
        .option('delta.minReaderVersion', '2')
        .option('delta.minWriterVersion', '5')
        .format('delta').saveAsTable(table))

if WRITE_MODE == 'append':
    print(
        '⚠  APPEND stores snapshot history: overlapping rolling windows are not '
        'transactions. Use LoadDate-aware selection/deduplication and never sum '
        'snapshots blindly.')

prepared, quarantines = {}, []
for logical_table, pattern in REPORTS.items():
    matches = _list_matches(pattern)
    if not matches:
        raise FileNotFoundError(
            f'{logical_table}: no file matched "{pattern}". All three current '
            'Power Platform admin center exports are required; no existing Delta '
            'table was changed.')
    if len(matches) > 1:
        raise ValueError(
            f'{logical_table}: {len(matches)} files matched "{pattern}". Keep '
            'exactly one current tenant-level snapshot per report type; overlapping '
            'lookback exports cannot be unioned without double counting. Matched '
            'files: ' + ', '.join(matches))
    path = matches[0]
    df = _validate_and_cast(
        _sanitize(_read_csv(path)), logical_table, path)
    if ADD_LINEAGE:
        df = (
            df.withColumn('SourceFile', F.lit(os.path.basename(path)))
            .withColumn('LoadDate', F.lit(_LOAD_TS)))
    curated, quarantine = _map_credit_rows(df, logical_table)
    if quarantine is not None:
        quarantines.append(quarantine)
    prepared[logical_table] = (curated, 1, curated.count())

print('✓  Preflight passed for every report; starting Delta writes.')
summary = []
for logical_table in REPORTS:
    df, files, count = prepared[logical_table]
    _write(df, logical_table)
    summary.append((logical_table, files, count))
    print(
        f'✓  {_table(logical_table):34} — 1 current snapshot, '
        f'{count:,} scoped rows -> written ({WRITE_MODE})')

if quarantines:
    quarantine = quarantines[0]
    for frame in quarantines[1:]:
        quarantine = quarantine.unionByName(frame)
    quarantine = quarantine.dropDuplicates([
        'source_report', 'raw_agent_id',
        'raw_environment_id', 'raw_environment_name'])
else:
    quarantine = spark.createDataFrame([], StructType([
        StructField('source_report', StringType(), True),
        StructField('raw_agent_id', StringType(), True),
        StructField('raw_environment_id', StringType(), True),
        StructField('raw_environment_name', StringType(), True),
        StructField('agent_mapping_status', StringType(), True)]))
_write(quarantine, 'credit_consumption_quarantine')
print(
    f'✓  {_table("credit_consumption_quarantine"):34} — '
    f'{quarantine.count():,} identifier-only row(s)')
print(
    '\nDone. Credit-consumption Delta tables written. Refresh the supplied '
    'Import model through its SQL analytics endpoint to pick them up.')
'''


def replace_generated_block(source: str, start: str, end: str, block: str) -> str:
    if start in source:
        block_start = source.index(start)
        block_end = source.index(end, block_start) + len(end)
        if block_end < len(source) and source[block_end] == "\n":
            block_end += 1
        return source[:block_start] + block.rstrip() + "\n" + source[block_end:]
    return source.rstrip() + "\n\n" + block.rstrip() + "\n"


def inject_identity(cell: str, conversation_column: str) -> str:
    if "**_identity_fields(r)" not in cell:
        row_pattern = re.compile(
            rf"rows\.append\(\{{\n(?P<indent>\s*)'{re.escape(conversation_column)}'"
        )
        match = row_pattern.search(cell)
        if not match:
            raise ValueError(f"Row anchor not found for {conversation_column}")
        indent = match.group("indent")
        cell = row_pattern.sub(
            f"rows.append({{\n{indent}**_identity_fields(r),\n"
            f"{indent}'{conversation_column}'",
            cell,
            count=1,
        )
    columns_anchor = f"columns=['{conversation_column}'"
    if f"columns=_IDENTITY_COLUMNS + ['{conversation_column}'" not in cell:
        if columns_anchor not in cell:
            raise ValueError(f"Columns anchor not found for {conversation_column}")
        cell = cell.replace(
            columns_anchor,
            f"columns=_IDENTITY_COLUMNS + ['{conversation_column}'",
            1,
        )
    return cell


def patch_transcript_notebook(path: Path) -> None:
    notebook = json.loads(path.read_text(encoding="utf-8"))
    cells = notebook["cells"]
    introduction = "".join(cells[1]["source"])
    introduction = introduction.replace(
        "   agent_catalogue · agent_performance      (Delta tables)",
        "   agent_catalogue · agent_performance · user_feedback · user_feedback_quarantine",
    )
    introduction = introduction.replace(
        "| `agent_sessions` | one row per conversation |",
        "| `agent_sessions` | one row per environment-aware conversation |",
    )
    introduction = introduction.replace(
        "| `agent_catalogue` | agent dimension (one row per `botSchemaName`) |",
        "| `agent_catalogue` | conformed agent dimension (one row per `canonical_agent_key`) |",
    )
    feedback_rows = (
        "| `user_feedback` | registry-mapped transcript and external feedback |\n"
        "| `user_feedback_quarantine` | identifiers only for unmapped external feedback |"
    )
    while feedback_rows + "\n" + feedback_rows in introduction:
        introduction = introduction.replace(
            feedback_rows + "\n" + feedback_rows, feedback_rows
        )
    if "| `user_feedback` |" not in introduction:
        introduction = introduction.replace(
            "| `agent_performance` | per-conversation KPI fact |",
            "| `agent_performance` | per-conversation KPI fact |\n" + feedback_rows,
        )
    registry_note = (
        " The registry CSV is required, and `AGENT_SCOPE_MODE` defaults to "
        "fail-closed `ESS Safe`."
    )
    while registry_note + registry_note in introduction:
        introduction = introduction.replace(
            registry_note + registry_note, registry_note
        )
    if registry_note not in introduction:
        introduction = introduction.replace(
            "`WRITE_MODE='merge'` is the safe default for bounded incremental reruns; "
            "full snapshots use `LOOKBACK_DAYS=0` with `'overwrite'`.",
            "`WRITE_MODE='merge'` is the safe default for bounded incremental reruns; "
            "full snapshots use `LOOKBACK_DAYS=0` with `'overwrite'`."
            + registry_note,
        )
    cells[1]["source"] = introduction.splitlines(True)
    cells[2]["source"] = [
        "## 1. Configuration  ·  *(mark this as the pipeline `parameters` cell)*\n",
        "\n",
        "Set `SOURCE_MODE`, credentials, `AGENT_REGISTRY_FILE`, and the exact "
        "`AGENT_SCOPE_MODE` (`ESS Safe`, `Selected Agents`, or `All Agents`). "
        "Leave `OUTPUT_PREFIX=''` for a standard Lakehouse; use `dbo` only when "
        "Lakehouse schemas are enabled.\n",
        "\n",
        "For a scheduled run, toggle this cell as a parameter cell. In production, "
        "replace `CLIENT_SECRET` with `notebookutils.credentials.getSecret(...)`.\n",
    ]

    config = "".join(cells[3]["source"])
    config = replace_generated_block(
        config,
        "# === AGENT REGISTRY CONFIG (generated) ===",
        "# === END AGENT REGISTRY CONFIG ===",
        REGISTRY_CONFIG,
    )
    cells[3]["source"] = config.splitlines(True)

    parsing = "".join(cells[8]["source"])
    parsing = replace_generated_block(
        parsing,
        "# === AGENT REGISTRY RUNTIME (generated) ===",
        "# === END AGENT REGISTRY RUNTIME ===",
        TRANSCRIPT_REGISTRY_RUNTIME,
    )
    cells[8]["source"] = parsing.splitlines(True)

    helpers = "".join(cells[10]["source"])
    identity_helper = r'''# === CANONICAL IDENTITY HELPERS (generated) ===
def _identity_fields(row):
    return {column: row.get(column) for column in _IDENTITY_COLUMNS}
# === END CANONICAL IDENTITY HELPERS ===
'''
    helpers = replace_generated_block(
        helpers,
        "# === CANONICAL IDENTITY HELPERS (generated) ===",
        "# === END CANONICAL IDENTITY HELPERS ===",
        identity_helper,
    )
    cells[10]["source"] = helpers.splitlines(True)

    sessions = inject_identity("".join(cells[12]["source"]), "conversation_id")
    cells[12]["source"] = sessions.splitlines(True)
    turns = inject_identity("".join(cells[14]["source"]), "conversation_id")
    cells[14]["source"] = turns.splitlines(True)

    errors = "".join(cells[16]["source"])
    if errors.count("**_identity_fields(r)") < 2:
        errors = errors.replace(
            "rows.append({\n                'conversation_id'",
            "rows.append({\n                **_identity_fields(r),\n"
            "                'conversation_id'",
            2,
        )
    errors = errors.replace(
        "columns=['conversation_id'",
        "columns=_IDENTITY_COLUMNS + ['conversation_id'",
    )
    errors = errors.replace(
        "return pd.DataFrame(rows, columns=[\n        'conversation_id'",
        "return pd.DataFrame(rows, columns=_IDENTITY_COLUMNS + [\n"
        "        'conversation_id'",
        1,
    )
    start = errors.index("def summarize_subagents")
    end = errors.index("errors = build_errors", start)
    errors = errors[:start] + SUBAGENT_SUMMARY + errors[end:]
    old_merge = """if not child_summary.empty:
    sessions = sessions.merge(child_summary, on='conversation_id', how='left')
"""
    new_merge = """if not child_summary.empty:
    sessions = sessions.merge(
        child_summary, on='conversation_natural_key', how='left',
        validate='one_to_one')
"""
    if old_merge in errors:
        errors = errors.replace(old_merge, new_merge, 1)
    elif new_merge not in errors:
        raise ValueError("Session child-summary merge anchor not found")
    cells[16]["source"] = errors.splitlines(True)

    cells[18]["source"] = AGENT_CATALOGUE_CELL.splitlines(True)
    cells[19]["source"] = [
        "## 7b. Registry-backed agent scope\n",
        "\n",
        "Scoping is applied before any transcript-derived table is built.\n",
    ]
    cells[20]["source"] = SCOPE_CELL.splitlines(True)

    performance = inject_identity(
        "".join(cells[25]["source"]), "ConversationTranscriptId"
    )
    perf_start = performance.index("if not child_summary.empty:")
    perf_end = performance.index("_performance_child_defaults", perf_start)
    perf_merge = """if not child_summary.empty:
    _performance_child = child_summary.rename(columns={
        'parent_agent_name': 'ParentAgentName',
        'parent_agent_id': 'ParentAgentId',
        'child_agent_names': 'ChildAgentNames',
        'child_agent_schema_names': 'ChildAgentSchemaNames',
        'child_agent_ids': 'ChildAgentIds',
        'child_agent_invocation_states': 'ChildAgentInvocationStates',
        'child_agent_dialogs': 'ChildAgentDialogs',
        'child_agent_plan_steps': 'ChildAgentPlanSteps',
        'child_agent_invocation_count': 'ChildAgentInvocationCount',
        'child_agent_count': 'ChildAgentCount',
        'has_child_agent': 'HasChildAgent',
        'child_agent_detail': 'ChildAgentDetail',
    })
    agent_performance = agent_performance.merge(
        _performance_child, on='conversation_natural_key', how='left',
        validate='one_to_one')
"""
    performance = performance[:perf_start] + perf_merge + performance[perf_end:]
    cells[25]["source"] = performance.splitlines(True)

    writes = "".join(cells[27]["source"])
    feedback_start = writes.index("# --- Unified feedback events:")
    outputs_start = writes.index("outputs = {", feedback_start)
    writes = FEEDBACK_BLOCK.rstrip() + "\n\n" + writes[outputs_start:]
    outputs_block_start = writes.index("outputs = {")
    outputs_end = writes.index("_ws =", outputs_block_start)
    outputs = """outputs = {
    'agent_sessions':             sessions,
    'agent_turns':                turns,
    'agent_errors':               errors,
    'agent_subagents':            subagents,
    'agent_catalogue':            agent_dim,
    'agent_performance':          agent_performance,
    'user_feedback':              user_feedback,
    'user_feedback_quarantine':   user_feedback_quarantine,
}"""
    writes = (
        writes[:outputs_block_start] + outputs.rstrip() + "\n\n" + writes[outputs_end:]
    )
    merge_start = writes.index("MERGE_KEYS = {")
    merge_end = writes.index("def _merge_delta", merge_start)
    merge_keys = """MERGE_KEYS = {
    'agent_sessions':             ['conversation_natural_key'],
    'agent_turns':                ['conversation_natural_key', 'turn_id'],
    'agent_errors':               ['conversation_natural_key', 'error_timestamp_utc', 'error_code'],
    'agent_subagents':            ['conversation_natural_key', 'subagent_event_key'],
    'agent_catalogue':            ['canonical_agent_key'],
    'agent_performance':          ['conversation_natural_key'],
    'user_feedback':              ['canonical_environment_key', 'Feedback Event Key'],
    'user_feedback_quarantine':   ['Feedback Event Key'],
}"""
    writes = writes[:merge_start] + merge_keys.rstrip() + "\n\n" + writes[merge_end:]
    env_key_block = """    # Multi-env safety: include the environment in the key for the fact tables so the
    # same conversation id from two environments can never collide (catalogue is a dim).
    if 'source_environment' in sdf.columns and name != 'agent_catalogue' and 'source_environment' not in keys:
        keys.append('source_environment')
"""
    writes = writes.replace(env_key_block, "")
    validation_anchor = "_chunk_rows = int(globals().get('PANDAS_TO_SPARK_CHUNK_ROWS', 20000))\n"
    validation = r'''
def _validate_full_incoming(pdf, name):
    keys = list(MERGE_KEYS.get(name, []))
    missing = [key for key in keys if key not in pdf.columns]
    if missing:
        raise ValueError(f'{name}: merge key column(s) missing: {missing}')
    if not keys or pdf.empty:
        return
    null_or_blank = pd.Series(False, index=pdf.index)
    for key in keys:
        null_or_blank = null_or_blank | pdf[key].isna() | (pdf[key].astype(str).str.strip() == '')
    if null_or_blank.any():
        raise ValueError(f'{name}: merge key contains null/blank values: {keys}')
    if pdf.duplicated(keys, keep=False).any():
        raise ValueError(
            f'{name}: merge key is not unique in the full incoming batch: {keys}')

'''
    if "_validate_full_incoming" not in writes:
        writes = writes.replace(
            validation_anchor, validation + validation_anchor, 1
        )
    validate_call = """for name, pdf in outputs.items():
    pdf = pdf.copy()
"""
    replacement = """for name, pdf in outputs.items():
    pdf = pdf.copy()
    _validate_full_incoming(pdf, name)
"""
    if "pdf = pdf.copy()\n    _validate_full_incoming(pdf, name)" not in writes:
        writes = writes.replace(validate_call, replacement, 1)
    writes = re.sub(
        r"^# --- Carry SourceEnvironment through to the transcript-derived tables ---.*?"
        r"^# --- Unified feedback events:",
        "# --- Unified feedback events:",
        writes,
        count=1,
        flags=re.MULTILINE | re.DOTALL,
    )
    writes = writes.replace(
        "Done. Seven Delta tables written.",
        "Done. Eight Delta tables written.",
    )
    cells[27]["source"] = writes.splitlines(True)

    for index, cell in enumerate(cells):
        if cell.get("cell_type") == "code":
            compile("".join(cell.get("source", [])), f"{path.name}:cell-{index}", "exec")
    path.write_text(
        json.dumps(notebook, ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8",
    )


def patch_credit_notebook(path: Path) -> None:
    notebook = json.loads(path.read_text(encoding="utf-8"))
    cells = notebook["cells"]
    introduction = "".join(cells[1]["source"])
    introduction = introduction.replace(
        "`dbo.credit_consumption_tenant`", "`credit_consumption_tenant`"
    )
    introduction = introduction.replace(
        "`dbo.credit_consumption_agent`", "`credit_consumption_agent`"
    )
    introduction = introduction.replace(
        "`dbo.credit_consumption_user`", "`credit_consumption_user`"
    )
    if "`credit_consumption_quarantine`" not in introduction:
        introduction = introduction.replace(
            "| `EntitlementConsumptionTenantPerUserDetailsReport_MCSMessages` | "
            "`credit_consumption_user` | user × agent × lookback snapshot |",
            "| `EntitlementConsumptionTenantPerUserDetailsReport_MCSMessages` | "
            "`credit_consumption_user` | user × agent × lookback snapshot |\n"
            "| unmapped agent/user rows | `credit_consumption_quarantine` | "
            "identifier-only registry diagnostics |",
        )
    introduction = introduction.replace(
        "Observed credits can be linked to ESS at bare `Agent Id` and, when nonblank, "
        "normalized `User Email`;",
        "Observed credits are scoped through `CreditId` registry aliases and joined "
        "through `canonical_agent_key`; user-report rows never infer an environment "
        "from agent name;",
    )
    cells[1]["source"] = introduction.splitlines(True)
    cells[2]["source"] = [
        "## 1. Configuration\n",
        "\n",
        "Toggle this as the pipeline parameter cell when orchestration overrides "
        "`WRITE_MODE`, `AGENT_SCOPE_MODE`, or `OUTPUT_PREFIX`. Leave "
        "`OUTPUT_PREFIX=''` for a standard Lakehouse; use `dbo` only when schemas "
        "are enabled. The same validated agent registry used by the transcript "
        "parser is required.\n",
    ]
    config = """# === CONFIG ===  (tag this cell as the pipeline `parameters` cell)

SOURCE_DIR = 'Files/credit_consumption'
REPORTS = {
    'credit_consumption_tenant': 'EntitlementConsumptionTenantDetailsReport_MCSMessages*',
    'credit_consumption_agent':  'EntitlementConsumptionTenantPerAgentDetailsReport_MCSMessages*',
    'credit_consumption_user':   'EntitlementConsumptionTenantPerUserDetailsReport_MCSMessages*',
}
AGENT_REGISTRY_FILE = '/lakehouse/default/Files/config/agent-registry.csv'
AGENT_SCOPE_MODE = 'ESS Safe'
OUTPUT_PREFIX = ''
WRITE_MODE = 'overwrite'
ADD_LINEAGE = True
STRICT = True

if AGENT_SCOPE_MODE not in {'ESS Safe', 'Selected Agents', 'All Agents'}:
    raise ValueError(
        'AGENT_SCOPE_MODE must be exactly one of: ESS Safe, Selected Agents, All Agents')
"""
    cells[3]["source"] = config.splitlines(True)
    cells[5]["source"] = CREDIT_HELPERS.splitlines(True)
    cells[7]["source"] = CREDIT_INGEST.splitlines(True)
    verify = "".join(cells[9]["source"])
    verify = verify.replace(
        "for table, files, rows in summary:",
        "for table, files, rows in summary:",
    )
    verify = verify.replace(
        "spark.table('dbo.credit_consumption_agent')",
        "spark.table(_table('credit_consumption_agent'))",
    )
    verify = verify.replace(
        "spark.table('dbo.credit_consumption_user')",
        "spark.table(_table('credit_consumption_user'))",
    )
    verify = verify.replace(
        "spark.table('dbo.agent_sessions')",
        "spark.table(_table('agent_sessions'))",
    )
    cells[9]["source"] = verify.splitlines(True)
    for index, cell in enumerate(cells):
        if cell.get("cell_type") == "code":
            compile("".join(cell.get("source", [])), f"{path.name}:cell-{index}", "exec")
    path.write_text(
        json.dumps(notebook, ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8",
    )


def add_model_columns(
    table: dict, columns: list[tuple[str, str]], namespace: str
) -> None:
    existing = {column["name"] for column in table.get("columns", [])}
    for name, data_type in columns:
        if name in existing:
            continue
        table.setdefault("columns", []).append(
            {
                "name": name,
                "dataType": data_type,
                "sourceColumn": name,
                "lineageTag": str(
                    uuid.uuid5(uuid.NAMESPACE_URL, f"{namespace}/{name}")
                ),
                "summarizeBy": "none",
                "annotations": [
                    {"name": "SummarizationSetBy", "value": "Automatic"}
                ],
            }
        )


def patch_m_ensured(
    expression: str,
    base_variable: str,
    transform_variable: str,
    columns: list[str],
) -> str:
    start = "    // Agent registry canonical columns: begin"
    end = "    // Agent registry canonical columns: end"
    encoded = ", ".join(json.dumps(column) for column in columns)
    block = (
        f"{start}\n"
        f"    RegistryEnsured = List.Accumulate({{{encoded}}}, {base_variable}, "
        "(state, column) => if Table.HasColumns(state, column) then state "
        "else Table.AddColumn(state, column, each null, type text)),\n"
        f"{end}"
    )
    if start in expression:
        block_start = expression.index(start)
        block_end = expression.index(end, block_start) + len(end)
        expression = expression[:block_start] + block + expression[block_end:]
    else:
        anchor = f"    {transform_variable} ="
        if anchor not in expression:
            raise ValueError(f"Power Query transform anchor not found: {anchor}")
        expression = expression.replace(anchor, block + "\n" + anchor, 1)
    patterns = [
        (
            f"{transform_variable} = Table.TransformColumnTypes({base_variable},",
            f"{transform_variable} = Table.TransformColumnTypes(RegistryEnsured,",
        ),
        (
            f"{transform_variable} = Table.TransformColumnTypes(\n        {base_variable},",
            f"{transform_variable} = Table.TransformColumnTypes(\n        RegistryEnsured,",
        ),
    ]
    for old, new in patterns:
        expression = expression.replace(old, new, 1)
    return expression


def catalogue_query(_: str) -> str:
    columns = [
        "canonical_agent_key",
        "canonical_agent_name",
        "canonical_environment_key",
        "agent_schema",
        "agent_display_name",
        "agent_class",
        "raw_agent_id",
        "raw_agent_schema",
        "raw_agent_name",
        "agent_mapping_status",
        "source_environments",
    ]
    encoded = ", ".join(json.dumps(column) for column in columns)
    typed = ",\n        ".join(
        f'{{"{column}", type text}}' for column in columns
    )
    return f'''let
    Columns = {{{encoded}}},
    Source = if Enable_Dataverse = "Include"
        then (try FabricTable("agent_catalogue") otherwise EmptyTable(Columns))
        else EmptyTable(Columns),
    Selected = Table.SelectColumns(Source, Columns, MissingField.UseNull),
    Typed = Table.TransformColumnTypes(Selected, {{
        {typed}
    }}),
    NonBlank = Table.SelectRows(
        Typed,
        each [canonical_agent_key] <> null
            and Text.Trim([canonical_agent_key]) <> ""),
    Conformed = Table.Distinct(NonBlank, {{"canonical_agent_key"}})
in
    Conformed
'''


def credit_query(table_name: str, base_columns: list[tuple[str, str]]):
    canonical = [
        ("canonical_agent_key", "type text"),
        ("canonical_agent_name", "type text"),
        ("canonical_environment_key", "type text"),
        ("agent_mapping_status", "type text"),
        ("raw_agent_id", "type text"),
        ("raw_environment_id", "type text"),
        ("raw_environment_name", "type text"),
    ]
    all_columns = base_columns + canonical
    encoded = ", ".join(json.dumps(name) for name, _ in all_columns)
    typed = ",\n        ".join(
        f'{{"{name}", {m_type}}}' for name, m_type in all_columns
    )

    def transform(_: str) -> str:
        return f'''let
    Columns = {{{encoded}}},
    Source = if Enable_Consumption = "Include"
        then (try FabricTable("{table_name}") otherwise EmptyTable(Columns))
        else EmptyTable(Columns),
    Selected = Table.SelectColumns(Source, Columns, MissingField.UseNull),
    Typed = Table.TransformColumnTypes(Selected, {{
        {typed}
    }}, "en-US")
in
    Typed
'''

    return transform


def patch_feedback_query(expression: str) -> str:
    columns = [
        "canonical_agent_key",
        "canonical_agent_name",
        "canonical_environment_key",
        "agent_mapping_status",
        "raw_agent_id",
        "raw_agent_schema",
        "raw_agent_name",
        "source_environment",
    ]

    def normalize_empty(match: re.Match) -> str:
        present = re.findall(r'"([^"]+)"', match.group(1))
        for column in columns:
            if column not in present:
                present.append(column)
        return "EmptyTable({" + ", ".join(json.dumps(x) for x in present) + "})"

    expression = re.sub(
        r"EmptyTable\(\{([^}]*)\}\)", normalize_empty, expression
    )
    start = "    // Agent registry canonical columns: begin"
    end = "    // Agent registry canonical columns: end"
    encoded = ", ".join(json.dumps(column) for column in columns)
    block = (
        f"{start}\n"
        f"    RegistryEnsured = List.Accumulate({{{encoded}}}, Headers, "
        "(state, column) => if Table.HasColumns(state, column) then state "
        "else Table.AddColumn(state, column, each null, type text)),\n"
        f"{end}"
    )
    if start in expression:
        block_start = expression.index(start)
        block_end = expression.index(end, block_start) + len(end)
        expression = expression[:block_start] + block + expression[block_end:]
    else:
        expression = expression.replace(
            "    Renamed = Table.RenameColumns(Headers,",
            block + "\n    Renamed = Table.RenameColumns(RegistryEnsured,",
            1,
        )
    selected_start = expression.rfind("Selected =")
    selected_end = expression.find("}, MissingField.UseNull)", selected_start)
    if selected_start < 0 or selected_end < 0:
        raise ValueError("ProductFeedback selected-column anchor not found")
    selected = expression[selected_start:selected_end]
    missing = [
        column for column in columns if json.dumps(column) not in selected
    ]
    if missing:
        expression = (
            expression[:selected_end]
            + ", "
            + ", ".join(json.dumps(column) for column in missing)
            + expression[selected_end:]
        )
    return expression


def patch_agent_variables_query(_: str) -> str:
    return '''let
    Columns = {"conversation_id", "conversation_natural_key", "variable_name", "variable_value"},
    Source =
        if Enable_Dataverse = "Include"
        then (try FabricTable("agent_variables") otherwise EmptyTable(Columns))
        else EmptyTable(Columns),
    SessionKeyGroups = Table.Group(
        Table.SelectColumns(
            #"Agent Sessions",
            {"conversation_id", "conversation_natural_key"},
            MissingField.UseNull
        ),
        {"conversation_id"},
        {{"NaturalKeys", each List.Distinct(List.RemoveNulls([conversation_natural_key])), type list}}
    ),
    AmbiguousSessionIds = Table.SelectRows(SessionKeyGroups, each List.Count([NaturalKeys]) > 1),
    NeedsNaturalKeyBackfill = not Table.HasColumns(Source, "conversation_natural_key"),
    AmbiguousJoin =
        if not NeedsNaturalKeyBackfill then
            #table({}, {})
        else
            Table.NestedJoin(
                Source,
                {"conversation_id"},
                AmbiguousSessionIds,
                {"conversation_id"},
                "_ambiguous",
                JoinKind.Inner
            ),
    ValidatedSource =
        if NeedsNaturalKeyBackfill and not Table.IsEmpty(AmbiguousJoin) then
            error "Agent Variables contains conversation IDs that occur in multiple environments. Add conversation_natural_key upstream."
        else Source,
    UnambiguousSessionKeys = Table.RemoveColumns(
        Table.AddColumn(
            Table.SelectRows(SessionKeyGroups, each List.Count([NaturalKeys]) = 1),
            "conversation_natural_key",
            each List.First([NaturalKeys]),
            type nullable text
        ),
        {"NaturalKeys"}
    ),
    WithNaturalKey =
        if not NeedsNaturalKeyBackfill then
            ValidatedSource
        else
            let
                Joined = Table.NestedJoin(
                    ValidatedSource,
                    {"conversation_id"},
                    UnambiguousSessionKeys,
                    {"conversation_id"},
                    "_session",
                    JoinKind.LeftOuter
                )
            in
                Table.ExpandTableColumn(
                    Joined,
                    "_session",
                    {"conversation_natural_key"},
                    {"conversation_natural_key"}
                ),
    Selected = Table.SelectColumns(WithNaturalKey, Columns, MissingField.UseNull),
    Typed = Table.TransformColumnTypes(Selected, {
        {"conversation_id", type text},
        {"conversation_natural_key", type text},
        {"variable_name", type text},
        {"variable_value", type text}
    })
in
    Typed
'''


def patch_knowledge_citations(expression: str) -> str:
    if '"conversation_natural_key"' not in expression:
        expression = expression.replace(
            '"conversation_id", \'Agent Turns\'[conversation_id],',
            '"conversation_id", \'Agent Turns\'[conversation_id],\n'
            '        "conversation_natural_key", \'Agent Turns\'[conversation_natural_key],',
            1,
        )
    return expression


def patch_activity_events(expression: str) -> str:
    if '"conversation_natural_key"' not in expression:
        expression = expression.replace(
            '"conversation_id", \'Agent Performance\'[ConversationTranscriptId],',
            '"conversation_id", \'Agent Performance\'[ConversationTranscriptId],\n'
            '            "conversation_natural_key", \'Agent Performance\'[conversation_natural_key],',
        )
    return expression


def add_calculated_table_column(table: dict, name: str, namespace: str) -> None:
    if any(column["name"] == name for column in table.get("columns", [])):
        return
    table.setdefault("columns", []).append(
        {
            "type": "calculatedTableColumn",
            "name": name,
            "dataType": "string",
            "isNameInferred": False,
            "sourceColumn": f"[{name}]",
            "lineageTag": str(
                uuid.uuid5(uuid.NAMESPACE_URL, f"{namespace}/{name}")
            ),
            "summarizeBy": "none",
            "annotations": [
                {"name": "SummarizationSetBy", "value": "Automatic"}
            ],
        }
    )


def set_partition_expression(table: dict, transform) -> None:
    source = table["partitions"][0]["source"]
    original = source["expression"]
    text = "\n".join(original) if isinstance(original, list) else original
    updated = transform(text)
    source["expression"] = (
        updated.splitlines() if isinstance(original, list) else updated
    )


def upsert_relationship(model: dict, relationship: dict) -> None:
    relationships = model.setdefault("relationships", [])
    name = relationship["name"]
    relationships[:] = [item for item in relationships if item.get("name") != name]
    relationships.append(relationship)


def patch_pbit(source: Path, destination: Path) -> None:
    with zipfile.ZipFile(source, "r") as archive:
        infos = archive.infolist()
        parts = {info.filename: archive.read(info.filename) for info in infos}
    schema = json.loads(parts["DataModelSchema"].decode("utf-16-le"))
    model = schema["model"]
    tables = {table["name"]: table for table in model["tables"]}

    glossary = tables["📖 Metric Glossary"]
    metric_column = next(
        column for column in glossary["columns"] if column["name"] == "Metric"
    )
    metric_column.pop("sortByColumn", None)

    identity_columns = [(name, "string") for name in IDENTITY_COLUMNS]
    facts = {
        "Agent Sessions": ("Ensured", "Typed"),
        "Agent Turns": ("Ensured", "Typed"),
        "Agent Errors": ("Promoted", "Typed"),
        "Agent Sub-Agent Calls": ("Promoted", "Typed"),
        "Agent Performance": ("PromotedHeaders", "ChangedTypes"),
    }
    for table_name, (base, transform_name) in facts.items():
        set_partition_expression(
            tables[table_name],
            lambda expression, base=base, transform_name=transform_name: patch_m_ensured(
                expression, base, transform_name, IDENTITY_COLUMNS
            ),
        )
        add_model_columns(
            tables[table_name],
            identity_columns,
            f"https://github.com/microsoft/ESS/fabric-agent-registry/{table_name}",
        )

    set_partition_expression(tables["Agent Catalogue"], catalogue_query)
    catalogue_columns = [
        ("canonical_agent_key", "string"),
        ("canonical_agent_name", "string"),
        ("canonical_environment_key", "string"),
        ("raw_agent_id", "string"),
        ("raw_agent_schema", "string"),
        ("raw_agent_name", "string"),
        ("agent_mapping_status", "string"),
        ("source_environments", "string"),
    ]
    add_model_columns(
        tables["Agent Catalogue"],
        catalogue_columns,
        "https://github.com/microsoft/ESS/fabric-agent-registry/catalogue",
    )

    set_partition_expression(tables["ProductFeedback"], patch_feedback_query)
    feedback_columns = [
        ("canonical_agent_key", "string"),
        ("canonical_agent_name", "string"),
        ("canonical_environment_key", "string"),
        ("agent_mapping_status", "string"),
        ("raw_agent_id", "string"),
        ("raw_agent_schema", "string"),
        ("raw_agent_name", "string"),
        ("source_environment", "string"),
    ]
    add_model_columns(
        tables["ProductFeedback"],
        feedback_columns,
        "https://github.com/microsoft/ESS/fabric-agent-registry/feedback",
    )

    credit_agent_base = [
        ("Agent_Name", "type text"),
        ("Agent_Id", "type text"),
        ("Product", "type text"),
        ("AI_Feature_Billable_Feature", "type text"),
        ("Billed_credit", "type number"),
        ("Non_billed_credit", "type number"),
        ("Channel", "type text"),
        ("Knowledge_Sources", "type text"),
        ("Tool_Used", "type text"),
        ("LLM_Model", "type text"),
        ("Scenario_Name", "type text"),
        ("Environment_Id", "type text"),
        ("Environment_Name", "type text"),
    ]
    credit_user_base = [
        ("User_Id", "type text"),
        ("User_Email", "type text"),
        ("Agent_Id", "type text"),
        ("Agent_Name", "type text"),
        ("Billable_credit_used", "type number"),
        ("Credits_used", "type number"),
        ("M365_Copilot_Licensed", "type text"),
    ]
    set_partition_expression(
        tables["Credit Consumption (Agent)"],
        credit_query("credit_consumption_agent", credit_agent_base),
    )
    set_partition_expression(
        tables["Credit Consumption (User)"],
        credit_query("credit_consumption_user", credit_user_base),
    )
    credit_model_columns = [
        ("canonical_agent_key", "string"),
        ("canonical_agent_name", "string"),
        ("canonical_environment_key", "string"),
        ("agent_mapping_status", "string"),
        ("raw_agent_id", "string"),
        ("raw_environment_id", "string"),
        ("raw_environment_name", "string"),
    ]
    for table_name in ("Credit Consumption (Agent)", "Credit Consumption (User)"):
        add_model_columns(
            tables[table_name],
            credit_model_columns,
            f"https://github.com/microsoft/ESS/fabric-agent-registry/{table_name}",
        )

    set_partition_expression(
        tables["Agent Variables"], patch_agent_variables_query
    )
    add_model_columns(
        tables["Agent Variables"],
        [("conversation_natural_key", "string")],
        "https://github.com/microsoft/ESS/fabric-agent-registry/Agent Variables",
    )
    set_partition_expression(
        tables["Knowledge Citations"], patch_knowledge_citations
    )
    add_calculated_table_column(
        tables["Knowledge Citations"],
        "conversation_natural_key",
        "https://github.com/microsoft/ESS/fabric-agent-registry/Knowledge Citations",
    )
    set_partition_expression(
        tables["Activity Events"], patch_activity_events
    )
    add_calculated_table_column(
        tables["Activity Events"],
        "conversation_natural_key",
        "https://github.com/microsoft/ESS/fabric-agent-registry/Activity Events",
    )

    relationships = model.setdefault("relationships", [])
    relationships[:] = [
        item
        for item in relationships
        if item.get("name")
        not in {
            "ca04rel-0001-0001-0001-000000000001",
            "cc-agent-id-bridge-0001",
            "cc-user-agentid-bridge-0001",
            "fabric-agent-performance-canonical",
            "fabric-product-feedback-canonical",
            "fabric-credit-agent-canonical",
            "fabric-credit-user-canonical",
        }
    ]
    canonical_relationships = [
        {
            "name": "ca04rel-0001-0001-0001-000000000001",
            "fromTable": "Agent Sessions",
            "fromColumn": "canonical_agent_key",
            "toTable": "Agent Catalogue",
            "toColumn": "canonical_agent_key",
        },
        {
            "name": "fabric-agent-performance-canonical",
            "fromTable": "Agent Performance",
            "fromColumn": "canonical_agent_key",
            "toTable": "Agent Catalogue",
            "toColumn": "canonical_agent_key",
            "isActive": False,
        },
        {
            "name": "fabric-product-feedback-canonical",
            "fromTable": "ProductFeedback",
            "fromColumn": "canonical_agent_key",
            "toTable": "Agent Catalogue",
            "toColumn": "canonical_agent_key",
        },
        {
            "name": "fabric-credit-agent-canonical",
            "fromTable": "Credit Consumption (Agent)",
            "fromColumn": "canonical_agent_key",
            "toTable": "Agent Catalogue",
            "toColumn": "canonical_agent_key",
        },
        {
            "name": "fabric-credit-user-canonical",
            "fromTable": "Credit Consumption (User)",
            "fromColumn": "canonical_agent_key",
            "toTable": "Agent Catalogue",
            "toColumn": "canonical_agent_key",
        },
    ]
    for relationship in canonical_relationships:
        upsert_relationship(model, relationship)

    conversation_relationship_names = {
        "ca01rel-0001-0001-0001-000000000001",
        "ca02rel-0001-0001-0001-000000000001",
        "ca03rel-0001-0001-0001-000000000001",
        "ca07rel-0001-0001-0001-000000000001",
        "ca11rel-0001-0001-0001-000000000001",
        "kc01rel-0001-0001-0001-000000000001",
        "ae01rel-0001-0001-0001-000000000001",
    }
    for relationship in model["relationships"]:
        if relationship.get("name") in conversation_relationship_names:
            relationship["fromColumn"] = "conversation_natural_key"
            relationship["toColumn"] = "conversation_natural_key"

    # Preserve existing dynamic-format fixes.
    for table in model["tables"]:
        for measure in table.get("measures", []):
            if "formatStringDefinition" in measure:
                measure.pop("formatString", None)

    parts["DataModelSchema"] = json.dumps(
        schema, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-16-le")

    raw = parts["UnappliedChanges"].decode("utf-16-le")
    query_transforms = {
        "Agent Sessions": lambda expression: patch_m_ensured(
            expression, "Ensured", "Typed", IDENTITY_COLUMNS
        ),
        "Agent Turns": lambda expression: patch_m_ensured(
            expression, "Ensured", "Typed", IDENTITY_COLUMNS
        ),
        "Agent Errors": lambda expression: patch_m_ensured(
            expression, "Promoted", "Typed", IDENTITY_COLUMNS
        ),
        "Agent Sub-Agent Calls": lambda expression: patch_m_ensured(
            expression, "Promoted", "Typed", IDENTITY_COLUMNS
        ),
        "Agent Performance": lambda expression: patch_m_ensured(
            expression, "PromotedHeaders", "ChangedTypes", IDENTITY_COLUMNS
        ),
        "Agent Catalogue": catalogue_query,
        "ProductFeedback": patch_feedback_query,
        "Credit Consumption (Agent)": credit_query(
            "credit_consumption_agent", credit_agent_base
        ),
        "Credit Consumption (User)": credit_query(
            "credit_consumption_user", credit_user_base
        ),
        "Agent Variables": patch_agent_variables_query,
    }
    for query_name, transform in query_transforms.items():
        raw = replace_query_text_raw(raw, query_name, transform)
    json.loads(raw)
    parts["UnappliedChanges"] = raw.encode("utf-16-le")

    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as archive:
        for info in infos:
            archive.writestr(info, parts[info.filename])


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Apply the Fabric agent-registry contract idempotently."
    )
    parser.add_argument(
        "--repo-root", type=Path, default=Path(__file__).resolve().parents[1]
    )
    args = parser.parse_args()
    repo = args.repo_root.resolve()
    transcript = repo / "Fabric/notebooks/Copilot_Agent_Transcript_Parser.ipynb"
    credit = repo / "Fabric/notebooks/Copilot_Credit_Consumption_Ingester.ipynb"
    pbit = repo / "ESS - Fabric V2.pbit"
    patch_transcript_notebook(transcript)
    patch_credit_notebook(credit)
    patch_pbit(pbit, pbit)
    print(
        json.dumps(
            {
                "transcriptNotebook": str(transcript),
                "creditNotebook": str(credit),
                "fabricPbit": str(pbit),
                "status": "ok",
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
