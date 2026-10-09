import argparse
import json
import uuid
import zipfile
from pathlib import Path

from update_topic_classifier import replace_query_text_raw


DIRECT_CHILD_COLUMNS = (
    ("ParentAgentName", "string"),
    ("ParentAgentId", "string"),
    ("ChildAgentNames", "string"),
    ("ChildAgentSchemaNames", "string"),
    ("ChildAgentIds", "string"),
    ("ChildAgentInvocationStates", "string"),
    ("ChildAgentDialogs", "string"),
    ("ChildAgentPlanSteps", "string"),
    ("ChildAgentInvocationCount", "int64"),
    ("ChildAgentCount", "int64"),
    ("HasChildAgent", "boolean"),
    ("ChildAgentDetail", "string"),
)
FABRIC_SESSION_COLUMNS = (
    ("parent_agent_name", "string"),
    ("parent_agent_id", "string"),
    ("child_agent_names", "string"),
    ("child_agent_schema_names", "string"),
    ("child_agent_ids", "string"),
    ("child_agent_invocation_states", "string"),
    ("child_agent_dialogs", "string"),
    ("child_agent_plan_steps", "string"),
    ("child_agent_invocation_count", "int64"),
    ("child_agent_count", "int64"),
    ("has_child_agent", "boolean"),
    ("child_agent_detail", "string"),
)
FABRIC_SUBAGENT_COLUMNS = (
    ("subagent_event_key", "string"),
    ("parent_agent_id", "string"),
    ("parent_agent_name", "string"),
    ("connected_agent_id", "string"),
    ("connected_agent_name", "string"),
    ("invocation_state", "string"),
    ("completion_state", "string"),
    ("error_code", "string"),
    ("error_message", "string"),
)


def add_model_columns(table: dict, columns: tuple[tuple[str, str], ...], namespace: str) -> None:
    existing = {column["name"] for column in table.get("columns", [])}
    for name, data_type in columns:
        if name in existing:
            continue
        table["columns"].append(
            {
                "name": name,
                "dataType": data_type,
                "sourceColumn": name,
                "lineageTag": str(uuid.uuid5(uuid.NAMESPACE_URL, f"{namespace}/{name}")),
                "summarizeBy": "none",
                "annotations": [{"name": "SummarizationSetBy", "value": "Automatic"}],
            }
        )


def build_direct_child_block() -> str:
    return '''                // Parent/child agent attribution from ConnectedAgent trace events.
                childTraceActs = List.Select(traceActs, each
                    let vt = try SafeText(_[valueType]) otherwise null
                    in List.Contains({"ConnectedAgentInitializeTraceData", "ConnectedAgentCompletedTraceData"}, vt)),
                childRecords = List.Transform(List.Positions(childTraceActs), (childIndex) =>
                    let
                        childAct = childTraceActs{childIndex},
                        childValue = try childAct[value] otherwise [],
                        childType = try SafeText(childAct[valueType]) otherwise null,
                        childSchema = try SafeText(childValue[connectedAgentBotSchemaName]) otherwise
                            (try SafeText(childValue[botSchemaName]) otherwise null),
                        childName = try SafeText(childValue[connectedAgentName]) otherwise
                            (try SafeText(childValue[agentName]) otherwise
                            (try SafeText(childValue[botName]) otherwise null)),
                        childId = try SafeText(childValue[connectedAgentBotId]) otherwise
                            (try SafeText(childValue[connectedAgentId]) otherwise
                            (try SafeText(childValue[botId]) otherwise null)),
                        childDialog = try SafeText(childValue[dialogSchemaName]) otherwise
                            (try SafeText(childValue[dialogName]) otherwise null),
                        childPlanStep = try SafeText(childValue[planStepId]) otherwise null,
                        completedState = try SafeText(childValue[completionState]) otherwise
                            (try SafeText(childValue[status]) otherwise
                            (try SafeText(childValue[outcome]) otherwise null)),
                        childState =
                            if childType = "ConnectedAgentCompletedTraceData" then
                                if completedState <> null and completedState <> "" then completedState else "Completed"
                            else "Initialized",
                        childLabel =
                            if childName <> null and childName <> "" then childName
                            else if childSchema <> null and childSchema <> "" then childSchema
                            else childId,
                        childKey =
                            if childSchema <> null and childSchema <> "" then "schema:" & childSchema
                            else if childId <> null and childId <> "" then "id:" & childId
                            else if childName <> null and childName <> "" then "name:" & childName
                            else childPlanStep,
                        childInvocationKey =
                            if childPlanStep <> null and childPlanStep <> "" then "plan:" & childPlanStep
                            else
                                let
                                    childPrefix = List.FirstN(childTraceActs, childIndex + 1),
                                    childSequence =
                                        if childType = "ConnectedAgentInitializeTraceData" then
                                            List.Count(List.Select(childPrefix, each
                                                try SafeText(_[valueType]) = "ConnectedAgentInitializeTraceData" otherwise false))
                                        else
                                            List.Count(List.Select(childPrefix, each
                                                try SafeText(_[valueType]) = "ConnectedAgentCompletedTraceData" otherwise false))
                                in "sequence:" & Number.ToText(childSequence)
                    in [
                        Key = childKey,
                        InvocationKey = childInvocationKey,
                        Label = childLabel,
                        Name = childName,
                        Schema = childSchema,
                        AgentId = childId,
                        State = childState,
                        Dialog = childDialog,
                        PlanStep = childPlanStep
                    ]),
                childKeys = List.Distinct(List.Select(List.Transform(childRecords, each [Key]), each _ <> null and _ <> "")),
                childNames = List.Distinct(List.Select(List.Transform(childRecords, each [Name]), each _ <> null and _ <> "")),
                childSchemas = List.Distinct(List.Select(List.Transform(childRecords, each [Schema]), each _ <> null and _ <> "")),
                childIds = List.Distinct(List.Select(List.Transform(childRecords, each [AgentId]), each _ <> null and _ <> "")),
                childStates = List.Distinct(List.Select(List.Transform(childRecords, each [State]), each _ <> null and _ <> "")),
                childDialogs = List.Distinct(List.Select(List.Transform(childRecords, each [Dialog]), each _ <> null and _ <> "")),
                childPlanSteps = List.Distinct(List.Select(List.Transform(childRecords, each [PlanStep]), each _ <> null and _ <> "")),
                childInvocationKeys = List.Distinct(List.Select(
                    List.Transform(childRecords, each [InvocationKey]),
                    each _ <> null and _ <> "")),
                childCanonicalKeys = List.Distinct(List.Transform(childInvocationKeys, (invocationKey) =>
                    let
                        related = List.Select(childRecords, each [InvocationKey] = invocationKey),
                        schemas = List.Select(List.Transform(related, each [Schema]), each _ <> null and _ <> ""),
                        ids = List.Select(List.Transform(related, each [AgentId]), each _ <> null and _ <> ""),
                        names = List.Select(List.Transform(related, each [Name]), each _ <> null and _ <> "")
                    in
                        if List.Count(schemas) > 0 then "schema:" & List.Last(schemas)
                        else if List.Count(ids) > 0 then "id:" & List.Last(ids)
                        else if List.Count(names) > 0 then "name:" & List.Last(names)
                        else invocationKey)),
                childDetails = List.Transform(childInvocationKeys, (invocationKey) =>
                    let
                        related = List.Select(childRecords, each [InvocationKey] = invocationKey),
                        finalEvents = List.Select(related, each [State] <> "Initialized"),
                        chosen = if List.Count(finalEvents) > 0 then List.Last(finalEvents) else List.Last(related),
                        friendlyNames = List.Select(List.Transform(related, each [Name]), each _ <> null and _ <> ""),
                        label =
                            if List.Count(friendlyNames) > 0 then List.Last(friendlyNames)
                            else if chosen[Label] <> null and chosen[Label] <> "" then chosen[Label]
                            else invocationKey
                    in label & " (" & chosen[State] & ")"),
'''


def patch_direct_agent_query(expression: str) -> str:
    if "ChildAgentDetail" in expression:
        start_marker = "                // Parent/child agent attribution from ConnectedAgent trace events."
        end_marker = "                // ── SessionInfo"
        start = expression.find(start_marker)
        end = expression.find(end_marker, start)
        if start < 0 or end < 0:
            raise ValueError("Existing direct child-agent block not found")
        expression = expression[:start] + build_direct_child_block() + "\n" + expression[end:]
        expression = expression.replace(
            "ChildAgentCount          = List.Count(childLabels)",
            "ChildAgentCount          = List.Count(childCanonicalKeys)",
        ).replace(
            "HasChildAgent            = List.Count(childLabels) > 0",
            "HasChildAgent            = List.Count(childCanonicalKeys) > 0",
        ).replace(
            "ChildAgentCount          = List.Count(childKeys)",
            "ChildAgentCount          = List.Count(childCanonicalKeys)",
        ).replace(
            "HasChildAgent            = List.Count(childKeys) > 0",
            "HasChildAgent            = List.Count(childCanonicalKeys) > 0",
        )
        return expression
    schema_marker = (
        "        ThumbsUpCount = nullable number, ThumbsDownCount = nullable number\n"
        "    ],"
    )
    schema_replacement = '''        ThumbsUpCount = nullable number, ThumbsDownCount = nullable number,
        ParentAgentName = nullable text, ParentAgentId = nullable text,
        ChildAgentNames = nullable text, ChildAgentSchemaNames = nullable text,
        ChildAgentIds = nullable text, ChildAgentInvocationStates = nullable text,
        ChildAgentDialogs = nullable text, ChildAgentPlanSteps = nullable text,
        ChildAgentInvocationCount = nullable number, ChildAgentCount = nullable number,
        HasChildAgent = nullable logical, ChildAgentDetail = nullable text
    ],'''
    if schema_marker not in expression:
        raise ValueError("Agent Performance empty schema marker not found")
    expression = expression.replace(schema_marker, schema_replacement, 1)

    trace_marker = (
        '                pvaActs    = List.Select(eventActs, each try _[name] = "pvaSetContext" otherwise false),\n\n'
    )
    if trace_marker not in expression:
        raise ValueError("Agent Performance trace marker not found")
    expression = expression.replace(
        trace_marker,
        trace_marker + build_direct_child_block() + "\n",
        1,
    )

    output_marker = '''                    FeedbackComment          = feedbackComment,
                    ThumbsUpCount            = feedbackUps,
                    ThumbsDownCount          = feedbackDowns
'''
    output_replacement = '''                    FeedbackComment          = feedbackComment,
                    ThumbsUpCount            = feedbackUps,
                    ThumbsDownCount          = feedbackDowns,
                    ParentAgentName          = try SafeText(metaRec[BotName]) otherwise null,
                    ParentAgentId            = try SafeText(metaRec[BotId]) otherwise null,
                    ChildAgentNames          = if List.Count(childNames) > 0 then Text.Combine(childNames, " | ") else null,
                    ChildAgentSchemaNames    = if List.Count(childSchemas) > 0 then Text.Combine(childSchemas, " | ") else null,
                    ChildAgentIds            = if List.Count(childIds) > 0 then Text.Combine(childIds, " | ") else null,
                    ChildAgentInvocationStates = if List.Count(childStates) > 0 then Text.Combine(childStates, " | ") else null,
                    ChildAgentDialogs        = if List.Count(childDialogs) > 0 then Text.Combine(childDialogs, " | ") else null,
                    ChildAgentPlanSteps      = if List.Count(childPlanSteps) > 0 then Text.Combine(childPlanSteps, " | ") else null,
                    ChildAgentInvocationCount = List.Count(childInvocationKeys),
                    ChildAgentCount          = List.Count(childCanonicalKeys),
                    HasChildAgent            = List.Count(childCanonicalKeys) > 0,
                    ChildAgentDetail         = if List.Count(childDetails) > 0 then Text.Combine(childDetails, "; ") else null
'''
    if output_marker not in expression:
        raise ValueError("Agent Performance output marker not found")
    return expression.replace(output_marker, output_replacement, 1)


def patch_fix_it_visual(raw: bytes) -> bytes:
    visual = json.loads(raw.decode("utf-8"))
    projections = visual["visual"]["query"]["queryState"]["Values"]["projections"]
    if any(item.get("queryRef") == "Agent Performance.ChildAgentDetail" for item in projections):
        return raw
    child_projection = {
        "field": {
            "Column": {
                "Expression": {"SourceRef": {"Entity": "Agent Performance"}},
                "Property": "ChildAgentDetail",
            }
        },
        "queryRef": "Agent Performance.ChildAgentDetail",
        "nativeQueryRef": "Child Agent",
        "displayName": "Child Agent",
    }
    insert_at = next(
        (index for index, item in enumerate(projections) if item.get("queryRef") == "Agent Performance.Recommended Action"),
        len(projections),
    )
    projections.insert(insert_at, child_projection)
    objects = visual["visual"].setdefault("objects", {})
    objects.setdefault("columnWidth", []).append(
        {
            "properties": {"value": {"expr": {"Literal": {"Value": "220D"}}}},
            "selector": {"metadata": "Agent Performance.ChildAgentDetail"},
        }
    )
    return (json.dumps(visual, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")


def patch_direct_pbit(source: Path, destination: Path) -> None:
    with zipfile.ZipFile(source, "r") as archive:
        infos = archive.infolist()
        parts = {info.filename: archive.read(info.filename) for info in infos}
    schema = json.loads(parts["DataModelSchema"].decode("utf-16-le"))
    model = schema["model"]
    table = next(table for table in model["tables"] if table["name"] == "Agent Performance")
    source_obj = table["partitions"][0]["source"]
    original = source_obj["expression"]
    expression = "\n".join(original) if isinstance(original, list) else original
    expression = patch_direct_agent_query(expression)
    source_obj["expression"] = expression.splitlines() if isinstance(original, list) else expression
    add_model_columns(table, DIRECT_CHILD_COLUMNS, "https://github.com/microsoft/ESS/child-agent")
    parts["DataModelSchema"] = json.dumps(schema, ensure_ascii=False, separators=(",", ":")).encode("utf-16-le")
    raw = parts["UnappliedChanges"].decode("utf-16-le")
    raw = replace_query_text_raw(raw, "Agent Performance", patch_direct_agent_query)
    json.loads(raw)
    parts["UnappliedChanges"] = raw.encode("utf-16-le")

    visual_path = (
        "Report/definition/pages/improveopp001aabbcc07/visuals/"
        "improve_table_backlog_001/visual.json"
    )
    parts[visual_path] = patch_fix_it_visual(parts[visual_path])
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as archive:
        for info in infos:
            archive.writestr(info, parts[info.filename])


def build_fabric_subagent_function() -> str:
    return '''def build_subagents(parsed):
    rows = []
    for _, r in parsed.iterrows():
        child_event_sequence = 0
        for a in get_activities(r['content_json']):
            if not isinstance(a, dict):
                continue
            vt = a.get('valueType')
            if vt not in ('ConnectedAgentInitializeTraceData', 'ConnectedAgentCompletedTraceData'):
                continue
            child_event_sequence += 1
            v = a.get('value') or {}
            event_type = 'initialize' if vt.endswith('InitializeTraceData') else 'completed'
            connected_schema = v.get('connectedAgentBotSchemaName') or v.get('botSchemaName')
            connected_id = v.get('connectedAgentBotId') or v.get('connectedAgentId') or v.get('botId')
            connected_name = v.get('connectedAgentName') or v.get('agentName') or v.get('botName')
            plan_step_id = v.get('planStepId')
            activity_id = a.get('id') or a.get('activityId')
            timestamp_raw = a.get('timestampMs') or a.get('timestamp')
            agent_identity = connected_schema or connected_id or connected_name or 'unknown'
            subagent_event_key = (
                f'activity:{activity_id}' if activity_id
                else f'sequence:{child_event_sequence}|{event_type}|'
                     f'{timestamp_raw or plan_step_id or agent_identity}')
            completion_state = (
                v.get('completionState') or v.get('status') or v.get('outcome')
                or ('Initialized' if event_type == 'initialize' else 'Completed'))
            rows.append({
                'conversation_id': r.get('conversationtranscriptid', ''),
                'subagent_event_key': subagent_event_key,
                'invocation_timestamp_utc': _iso(a.get('timestampMs') or a.get('timestamp')),
                'event_type': event_type,
                'parent_agent_schema': v.get('parentBotSchemaName'),
                'parent_agent_id': v.get('parentBotId') or v.get('parentAgentId'),
                'parent_agent_name': v.get('parentAgentName') or v.get('parentBotName'),
                'connected_agent_schema': connected_schema,
                'connected_agent_id': connected_id,
                'connected_agent_name': connected_name,
                'dialog_schema': v.get('dialogSchemaName') or v.get('dialogName'),
                'user_id_hash': hash_id(v.get('userId')),
                'plan_step_id': plan_step_id,
                'invocation_state': completion_state,
                'completion_state': completion_state if event_type == 'completed' else None,
                'error_code': v.get('errorCode'),
                'error_message': (v.get('errorMessage') or '')[:TEXT_TRUNCATE],
            })
    return pd.DataFrame(rows, columns=[
        'conversation_id', 'subagent_event_key', 'invocation_timestamp_utc', 'event_type',
        'parent_agent_schema', 'parent_agent_id', 'parent_agent_name',
        'connected_agent_schema', 'connected_agent_id', 'connected_agent_name',
        'dialog_schema', 'user_id_hash', 'plan_step_id', 'invocation_state',
        'completion_state', 'error_code', 'error_message'])

def summarize_subagents(subagent_frame):
    columns = [
        'conversation_id', 'parent_agent_name', 'parent_agent_id',
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
    for conversation_id, group in subagent_frame.groupby('conversation_id', dropna=False):
        group = group.copy()
        _initialize_sequence = 0
        _completed_sequence = 0
        _fallback_keys = []
        for _event_type in group['event_type'].tolist():
            if _event_type == 'initialize':
                _initialize_sequence += 1
                _fallback_keys.append(f'sequence:{_initialize_sequence}')
            else:
                _completed_sequence += 1
                _fallback_keys.append(f'sequence:{_completed_sequence}')
        group['_fallback_invocation_key'] = _fallback_keys
        identities = []
        details = []
        def _identity(row):
            return _first_present(
                row.get('connected_agent_schema'),
                row.get('connected_agent_id'),
                row.get('connected_agent_name'))

        def _invocation_key(row):
            plan_step = _first_present(row.get('plan_step_id'))
            if plan_step:
                return f'plan:{plan_step}'
            return row.get('_fallback_invocation_key')

        invocation_keys = list(dict.fromkeys(
            key for key in group.apply(_invocation_key, axis=1).tolist() if key))
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
            friendly_names = [
                value for value in matching['connected_agent_name'].tolist()
                if _present(value)]
            label = (friendly_names[-1] if friendly_names
                     else _first_present(
                         chosen.get('connected_agent_schema'),
                         chosen.get('connected_agent_id'),
                         identity))
            details.append(f'{label} ({chosen.get("invocation_state") or chosen.get("event_type")})')
        first = group.iloc[0]
        summaries.append({
            'conversation_id': conversation_id,
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


def patch_fabric_notebook(path: Path) -> None:
    notebook = json.loads(path.read_text(encoding="utf-8"))
    cell = "".join(notebook["cells"][16]["source"])
    start = cell.index("def build_subagents(parsed):")
    end = cell.index("errors = build_errors(parsed)", start)
    cell = cell[:start] + build_fabric_subagent_function() + "\n" + cell[end:]
    old_tail = '''errors = build_errors(parsed)
subagents = build_subagents(parsed)
print(f'errors: {len(errors):,}  |  sub-agent events: {len(subagents):,}')'''
    new_tail = '''errors = build_errors(parsed)
subagents = build_subagents(parsed)
child_summary = summarize_subagents(subagents)
_session_child_columns = {
    'parent_agent_name': None,
    'parent_agent_id': None,
    'child_agent_names': None,
    'child_agent_schema_names': None,
    'child_agent_ids': None,
    'child_agent_invocation_states': None,
    'child_agent_dialogs': None,
    'child_agent_plan_steps': None,
    'child_agent_invocation_count': 0,
    'child_agent_count': 0,
    'has_child_agent': False,
    'child_agent_detail': None,
}
if not child_summary.empty:
    sessions = sessions.merge(child_summary, on='conversation_id', how='left')
for _column, _default in _session_child_columns.items():
    if _column not in sessions.columns:
        sessions[_column] = _default
    else:
        sessions[_column] = sessions[_column].where(pd.notna(sessions[_column]), _default)
print(f'errors: {len(errors):,}  |  sub-agent events: {len(subagents):,}')
'''
    if old_tail in cell:
        cell = cell.replace(old_tail, new_tail, 1)
    elif "child_summary = summarize_subagents(subagents)" not in cell:
        raise ValueError("Fabric child-agent tail marker not found")
    notebook["cells"][16]["source"] = cell.splitlines(True)

    writes = "".join(notebook["cells"][27]["source"])
    writes = writes.replace(
        "'agent_subagents':    ['conversation_id', 'invocation_timestamp_utc', 'connected_agent_schema', 'plan_step_id'],",
        "'agent_subagents':    ['conversation_id', 'subagent_event_key'],",
    )
    if "'agent_subagents':    ['conversation_id', 'subagent_event_key']," not in writes:
        raise ValueError("Fabric Agent Sub-Agent Calls merge key marker not found")
    notebook["cells"][27]["source"] = writes.splitlines(True)

    performance = "".join(notebook["cells"][25]["source"])
    marker = "agent_performance = build_agent_performance(parsed)\n"
    enrichment = marker + '''if not child_summary.empty:
    _performance_child = child_summary.rename(columns={
        'conversation_id': 'ConversationTranscriptId',
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
        _performance_child, on='ConversationTranscriptId', how='left')
_performance_child_defaults = {
    'ParentAgentName': None,
    'ParentAgentId': None,
    'ChildAgentNames': None,
    'ChildAgentSchemaNames': None,
    'ChildAgentIds': None,
    'ChildAgentInvocationStates': None,
    'ChildAgentDialogs': None,
    'ChildAgentPlanSteps': None,
    'ChildAgentInvocationCount': 0,
    'ChildAgentCount': 0,
    'HasChildAgent': False,
    'ChildAgentDetail': None,
}
for _column, _default in _performance_child_defaults.items():
    if _column not in agent_performance.columns:
        agent_performance[_column] = _default
    else:
        agent_performance[_column] = agent_performance[_column].where(
            pd.notna(agent_performance[_column]), _default)
'''
    if marker not in performance:
        raise ValueError("Fabric Agent Performance marker not found")
    start = performance.index(marker)
    end_marker = "print(f'agent performance rows:"
    end = performance.index(end_marker, start)
    performance = performance[:start] + enrichment + performance[end:]
    notebook["cells"][25]["source"] = performance.splitlines(True)
    compile(cell, "fabric_subagents", "exec")
    compile(performance, "fabric_agent_performance", "exec")
    compile(writes, "fabric_writes", "exec")
    path.write_text(json.dumps(notebook, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def add_ensured_columns(expression: str, ensured_columns: list[str], typed_columns: list[tuple[str, str]]) -> str:
    if ensured_columns[0] not in expression:
        marker = "    Typed = Table.TransformColumnTypes("
        if marker not in expression:
            raise ValueError("Fabric query Typed marker not found")
        quoted = ", ".join(json.dumps(column) for column in ensured_columns)
        block = (
            "    EnsuredChildAgents = List.Accumulate(\n"
            f"        {{{quoted}}},\n"
            "        Promoted,\n"
            "        (st, c) => if List.Contains(Table.ColumnNames(st), c) then st else Table.AddColumn(st, c, each null, type text)),\n"
        )
        expression = expression.replace(marker, block + marker.replace("Promoted", "EnsuredChildAgents"), 1)
    type_marker = "    })\nin\n"
    if typed_columns[0][0] not in expression:
        if type_marker not in expression:
            raise ValueError("Fabric query type-list marker not found")
        additions = ",\n" + ",\n".join(
            f'        {{{json.dumps(name)}, {m_type}}}' for name, m_type in typed_columns
        )
        expression = expression.replace(type_marker, additions + "\n    })\nin\n", 1)
    return expression


def patch_fabric_sessions_query(expression: str) -> str:
    ensured_marker = '"agent_name", "agent_id"}'
    replacement = (
        '"agent_name", "agent_id", "parent_agent_name", "parent_agent_id", '
        '"child_agent_names", "child_agent_schema_names", "child_agent_ids", '
        '"child_agent_invocation_states", "child_agent_dialogs", "child_agent_plan_steps", '
        '"child_agent_invocation_count", "child_agent_count", "has_child_agent", "child_agent_detail"}'
    )
    if replacement not in expression:
        if ensured_marker not in expression:
            raise ValueError("Fabric Agent Sessions Ensured marker not found")
        expression = expression.replace(ensured_marker, replacement, 1)
    if '{"parent_agent_name", type text},' not in expression:
        marker = '        {"agent_id", type text}'
        block = '''        {"agent_id", type text},
        {"parent_agent_name", type text},
        {"parent_agent_id", type text},
        {"child_agent_names", type text},
        {"child_agent_schema_names", type text},
        {"child_agent_ids", type text},
        {"child_agent_invocation_states", type text},
        {"child_agent_dialogs", type text},
        {"child_agent_plan_steps", type text},
        {"child_agent_invocation_count", Int64.Type},
        {"child_agent_count", Int64.Type},
        {"has_child_agent", type logical},
        {"child_agent_detail", type text}'''
        expression = expression.replace(marker, block, 1)
    return expression


def patch_fabric_subagents_query(expression: str) -> str:
    return '''let
    Promoted = if Enable_Dataverse = "Include" then
        (try FabricTable("agent_subagents") otherwise EmptyTable({
            "conversation_id", "invocation_timestamp_utc", "event_type",
            "parent_agent_schema", "connected_agent_schema", "dialog_schema",
            "user_id_hash", "plan_step_id", "subagent_event_key",
            "parent_agent_id", "parent_agent_name", "connected_agent_id",
            "connected_agent_name", "invocation_state", "completion_state",
            "error_code", "error_message"
        }))
    else EmptyTable({
        "conversation_id", "invocation_timestamp_utc", "event_type",
        "parent_agent_schema", "connected_agent_schema", "dialog_schema",
        "user_id_hash", "plan_step_id", "subagent_event_key",
        "parent_agent_id", "parent_agent_name", "connected_agent_id",
        "connected_agent_name", "invocation_state", "completion_state",
        "error_code", "error_message"
    }),
    Typed = Table.TransformColumnTypes(Promoted, {
        {"conversation_id", type text},
        {"invocation_timestamp_utc", type datetime},
        {"event_type", type text},
        {"parent_agent_schema", type text},
        {"connected_agent_schema", type text},
        {"dialog_schema", type text},
        {"user_id_hash", type text},
        {"plan_step_id", type text},
        {"subagent_event_key", type text},
        {"parent_agent_id", type text},
        {"parent_agent_name", type text},
        {"connected_agent_id", type text},
        {"connected_agent_name", type text},
        {"invocation_state", type text},
        {"completion_state", type text},
        {"error_code", type text},
        {"error_message", type text}
    })
in
    Typed
'''


def patch_fabric_performance_query(expression: str) -> str:
    old_columns = '"StatusCode", "StateCode"}'
    new_columns = (
        '"StatusCode", "StateCode", "ParentAgentName", "ParentAgentId", "ChildAgentNames", '
        '"ChildAgentSchemaNames", "ChildAgentIds", "ChildAgentInvocationStates", '
        '"ChildAgentDialogs", "ChildAgentPlanSteps", "ChildAgentInvocationCount", '
        '"ChildAgentCount", "HasChildAgent", "ChildAgentDetail"}'
    )
    expression = expression.replace(old_columns, new_columns)
    if '{"ChildAgentInvocationCount",' not in expression:
        marker = '            {"StateCode", Int64.Type}'
        block = '''            {"StateCode", Int64.Type},
            {"ChildAgentInvocationCount", Int64.Type},
            {"ChildAgentCount", Int64.Type},
            {"HasChildAgent", type logical}'''
        expression = expression.replace(marker, block, 1)
    return expression


def patch_fabric_interactions_query(expression: str) -> str:
    marker = '    __link = Table.AddColumn(__xN, "Agent_LinkID", each'
    replacement = (
        '    __linkBase = Table.RemoveColumns(__xN, {"Agent_LinkID"}, MissingField.Ignore),\n'
        '    __link = Table.AddColumn(__linkBase, "Agent_LinkID", each'
    )
    return expression.replace(marker, replacement, 1)


def patch_fabric_pbit(source: Path, destination: Path) -> None:
    with zipfile.ZipFile(source, "r") as archive:
        infos = archive.infolist()
        parts = {info.filename: archive.read(info.filename) for info in infos}
    schema = json.loads(parts["DataModelSchema"].decode("utf-16-le"))
    model = schema["model"]
    transforms = {
        "Chat + Agent Interactions (Audit Logs)": patch_fabric_interactions_query,
        "Agent Sessions": patch_fabric_sessions_query,
        "Agent Sub-Agent Calls": patch_fabric_subagents_query,
        "Agent Performance": patch_fabric_performance_query,
    }
    columns = {
        "Chat + Agent Interactions (Audit Logs)": (),
        "Agent Sessions": FABRIC_SESSION_COLUMNS,
        "Agent Sub-Agent Calls": FABRIC_SUBAGENT_COLUMNS,
        "Agent Performance": DIRECT_CHILD_COLUMNS,
    }
    for table_name, transform in transforms.items():
        table = next(table for table in model["tables"] if table["name"] == table_name)
        source_obj = table["partitions"][0]["source"]
        original = source_obj["expression"]
        expression = "\n".join(original) if isinstance(original, list) else original
        expression = transform(expression)
        source_obj["expression"] = expression.splitlines() if isinstance(original, list) else expression
        add_model_columns(
            table,
            columns[table_name],
            f"https://github.com/microsoft/ESS/fabric-child-agent/{table_name}",
        )
    parts["DataModelSchema"] = json.dumps(schema, ensure_ascii=False, separators=(",", ":")).encode("utf-16-le")
    raw = parts["UnappliedChanges"].decode("utf-16-le")
    for table_name, transform in transforms.items():
        raw = replace_query_text_raw(raw, table_name, transform)
    json.loads(raw)
    parts["UnappliedChanges"] = raw.encode("utf-16-le")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as archive:
        for info in infos:
            archive.writestr(info, parts[info.filename])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv-pbit", type=Path, required=True)
    parser.add_argument("--dataverse-pbit", type=Path, required=True)
    parser.add_argument("--fabric-pbit", type=Path, required=True)
    parser.add_argument("--fabric-notebook", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    patch_direct_pbit(args.csv_pbit, args.output_dir / args.csv_pbit.name)
    patch_direct_pbit(args.dataverse_pbit, args.output_dir / args.dataverse_pbit.name)
    patch_fabric_notebook(args.fabric_notebook)
    patch_fabric_pbit(args.fabric_pbit, args.output_dir / args.fabric_pbit.name)
    print(json.dumps({"outputDir": str(args.output_dir), "status": "ok"}, indent=2))


if __name__ == "__main__":
    main()
