import argparse
import json
import uuid
import zipfile
from pathlib import Path

from update_topic_classifier import insert_query_raw, replace_query_text_raw, upsert_expression


SCOPE_PARAMETER = "Agent Scope Mode"
REGISTRY_PARAMETER = "Agent Registry JSON"
REGISTRY_QUERY = "AgentRegistry"
SCOPE_PARAMETER_EXPRESSION = (
    '"ESS Safe" meta [IsParameterQuery=true, Type="Text", IsParameterQueryRequired=true]'
)
REGISTRY_PARAMETER_EXPRESSION = (
    'null meta [IsParameterQuery=true, Type="Text", IsParameterQueryRequired=false]'
)
SCOPE_PARAMETER_LINEAGE = str(
    uuid.uuid5(uuid.NAMESPACE_URL, "https://github.com/microsoft/ESS/parameters/agent-scope-mode")
)
REGISTRY_PARAMETER_LINEAGE = str(
    uuid.uuid5(uuid.NAMESPACE_URL, "https://github.com/microsoft/ESS/parameters/agent-registry-json")
)
REGISTRY_QUERY_LINEAGE = str(
    uuid.uuid5(uuid.NAMESPACE_URL, "https://github.com/microsoft/ESS/queries/agent-registry")
)
CANONICAL_COLUMNS = (("AgentKey", "string"), ("AgentLabel", "string"))
DIRECT_TRANSCRIPT_COLUMNS = (
    ("BotSchemaName", "string"),
    ("AgentKey", "string"),
    ("AgentLabel", "string"),
)
MEASURE_NAMES = {
    ("Agent Performance", "Agent Cost $ (by Agent)"),
    ("Agent Performance", "Agent Match Count"),
    ("AgentCredits", "Total Credits (30 Days)"),
    ("AgentCredits", "Agents with Credits"),
    ("AgentCredits", "Max Credits Agent (30 Days)"),
    ("AgentCredits", "Top Credit Agent"),
    ("AgentCredits", "Credit Utilization Rate"),
    ("AgentCredits", "Credit Share (30 Days)"),
    ("AgentCredits", "Billable Credits"),
    ("AgentCredits", "Credits Without User Email"),
}


def build_agent_registry_query() -> str:
    return r'''let
    Empty = #table(
        type table [
            RegistryVersion = nullable text,
            AgentKey = nullable text,
            AgentLabel = nullable text,
            IsEss = nullable logical,
            Selected = nullable logical,
            Enabled = nullable logical,
            EnvironmentKey = nullable text,
            EnvironmentName = nullable text,
            EnvironmentUrl = nullable text,
            AliasType = nullable text,
            AliasValue = nullable text
        ],
        {}
    ),
    SourceValue = try Text.From(#"Agent Registry JSON") otherwise "",
    SourceText = if SourceValue = null then "" else Text.Trim(SourceValue),
    Parsed =
        if SourceText = "" then {}
        else try Json.Document(Text.ToBinary(SourceText, TextEncoding.Utf8))
             otherwise error "Agent Registry JSON is invalid. Regenerate agent-registry.json with tools/agent_registry.py.",
    Checked =
        if not Value.Is(Parsed, type list) then
            error "Agent Registry JSON must contain a JSON array."
        else Parsed,
    Records = List.Select(Checked, each Value.Is(_, type record)),
    AsTable =
        if List.IsEmpty(Records) then Empty
        else Table.FromRecords(
            Records,
            type table [
                RegistryVersion = nullable text,
                AgentKey = nullable text,
                AgentLabel = nullable text,
                IsEss = nullable logical,
                Selected = nullable logical,
                Enabled = nullable logical,
                EnvironmentKey = nullable text,
                EnvironmentName = nullable text,
                EnvironmentUrl = nullable text,
                AliasType = nullable text,
                AliasValue = nullable text
            ],
            MissingField.UseNull
        ),
    Typed = Table.TransformColumnTypes(AsTable, {
        {"RegistryVersion", type text},
        {"AgentKey", type text},
        {"AgentLabel", type text},
        {"IsEss", type logical},
        {"Selected", type logical},
        {"Enabled", type logical},
        {"EnvironmentKey", type text},
        {"EnvironmentName", type text},
        {"EnvironmentUrl", type text},
        {"AliasType", type text},
        {"AliasValue", type text}
    }),
    Cleaned = Table.TransformColumns(Typed, {
        {"RegistryVersion", each if _ = null then "" else Text.Trim(_), type text},
        {"AgentKey", each if _ = null then "" else Text.Trim(_), type text},
        {"AgentLabel", each if _ = null then "" else Text.Trim(_), type text},
        {"EnvironmentKey", each if _ = null then "" else Text.Trim(_), type text},
        {"EnvironmentName", each if _ = null then "" else Text.Trim(_), type text},
        {"EnvironmentUrl", each if _ = null then "" else Text.Trim(_), type text},
        {"AliasType", each if _ = null then "" else Text.Trim(_), type text},
        {"AliasValue", each if _ = null then "" else Text.Trim(_), type text}
    }),
    NormalizeAlias = (aliasType as nullable text, aliasValue as nullable text) as text =>
        let
            raw = if aliasValue = null then "" else Text.Lower(Text.Trim(aliasValue)),
            unbraced = Text.Trim(raw, {"{", "}"}),
            normalized =
                if aliasType = "CreditId" and Text.StartsWith(unbraced, "p_", Comparer.OrdinalIgnoreCase)
                then Text.Middle(unbraced, 2)
                else unbraced
        in normalized,
    WithNormalizedAlias = Table.AddColumn(
        Cleaned,
        "AliasValueNormalized",
        each NormalizeAlias([AliasType], [AliasValue]),
        type text
    ),
    InvalidRows = Table.SelectRows(WithNormalizedAlias, each
        [RegistryVersion] <> "1"
        or [AgentKey] = ""
        or [AgentLabel] = ""
        or not List.Contains({"TranscriptId", "TranscriptSchema", "CreditId", "M365Title"}, [AliasType])
        or [AliasValueNormalized] = ""
        or [IsEss] = null
        or [Selected] = null
        or [Enabled] = null
    ),
    EnabledRows = Table.SelectRows(WithNormalizedAlias, each [Enabled] = true),
    AliasGroups = Table.Group(
        EnabledRows,
        {"AliasType", "AliasValueNormalized"},
        {{"AgentKeys", each List.Distinct([AgentKey]), type list}}
    ),
    Conflicts = Table.SelectRows(AliasGroups, each List.Count([AgentKeys]) > 1),
    Validated =
        if not Table.IsEmpty(InvalidRows) then
            error "Agent Registry contains invalid rows. Validate it with tools/agent_registry.py."
        else if not Table.IsEmpty(Conflicts) then
            error "Agent Registry contains an alias assigned to multiple AgentKey values."
        else WithNormalizedAlias
in
    Validated
'''


def _replace_marked_block(expression: str, start_marker: str, end_marker: str, block: str) -> str:
    if start_marker not in expression:
        return expression
    start = expression.index(start_marker)
    end = expression.index(end_marker, start) + len(end_marker)
    return expression[:start] + block + expression[end:]


def _transcript_scope_block() -> str:
    return r'''        // Agent registry scope: begin
        AgentRegistryScopeMode = Text.Trim(Text.From(#"Agent Scope Mode")),
        RegistryTranscriptIdAliases = Table.Distinct(Table.SelectColumns(
            Table.SelectRows(AgentRegistry, each [Enabled] = true and [AliasType] = "TranscriptId"),
            {"AliasValueNormalized", "AgentKey", "AgentLabel", "IsEss", "Selected"}
        )),
        RegistryTranscriptSchemaAliases = Table.Distinct(Table.SelectColumns(
            Table.SelectRows(AgentRegistry, each [Enabled] = true and [AliasType] = "TranscriptSchema"),
            {"AliasValueNormalized", "AgentKey", "AgentLabel", "IsEss", "Selected"}
        )),
        WithAgentIdAlias = Table.AddColumn(
            NoGhosts,
            "_AgentIdAliasValue",
            each if [BotId] = null then null else Text.Lower(Text.Trim(Text.Trim(Text.From([BotId]), {"{", "}"}))),
            type nullable text
        ),
        WithAgentSchemaAlias = Table.AddColumn(
            WithAgentIdAlias,
            "_AgentSchemaAliasValue",
            each if [BotSchemaName] = null then null else Text.Lower(Text.Trim(Text.From([BotSchemaName]))),
            type nullable text
        ),
        WithIdRegistry = Table.NestedJoin(
            WithAgentSchemaAlias,
            {"_AgentIdAliasValue"},
            RegistryTranscriptIdAliases,
            {"AliasValueNormalized"},
            "_id_registry",
            JoinKind.LeftOuter
        ),
        ExpandedIdRegistry = Table.ExpandTableColumn(
            WithIdRegistry,
            "_id_registry",
            {"AgentKey", "AgentLabel", "IsEss", "Selected"},
            {"_IdAgentKey", "_IdAgentLabel", "_IdIsEss", "_IdSelected"}
        ),
        WithSchemaRegistry = Table.NestedJoin(
            ExpandedIdRegistry,
            {"_AgentSchemaAliasValue"},
            RegistryTranscriptSchemaAliases,
            {"AliasValueNormalized"},
            "_schema_registry",
            JoinKind.LeftOuter
        ),
        ExpandedSchemaRegistry = Table.ExpandTableColumn(
            WithSchemaRegistry,
            "_schema_registry",
            {"AgentKey", "AgentLabel", "IsEss", "Selected"},
            {"_SchemaAgentKey", "_SchemaAgentLabel", "_SchemaIsEss", "_SchemaSelected"}
        ),
        ConflictingAgentAliases = Table.SelectRows(
            ExpandedSchemaRegistry,
            each [_IdAgentKey] <> null
                and [_SchemaAgentKey] <> null
                and [_IdAgentKey] <> [_SchemaAgentKey]
        ),
        ValidatedAgentAliases =
            if not Table.IsEmpty(ConflictingAgentAliases) then
                error "TranscriptId and TranscriptSchema aliases resolve to different AgentKey values."
            else ExpandedSchemaRegistry,
        WithRegistryAgentKey = Table.AddColumn(
            ValidatedAgentAliases,
            "_RegistryAgentKey",
            each if [_IdAgentKey] <> null then [_IdAgentKey] else [_SchemaAgentKey],
            type nullable text
        ),
        WithRegistryAgentLabel = Table.AddColumn(
            WithRegistryAgentKey,
            "_RegistryAgentLabel",
            each if [_IdAgentLabel] <> null then [_IdAgentLabel] else [_SchemaAgentLabel],
            type nullable text
        ),
        WithRegistryIsEss = Table.AddColumn(
            WithRegistryAgentLabel,
            "_RegistryIsEss",
            each if [_IdAgentKey] <> null then [_IdIsEss] else [_SchemaIsEss],
            type nullable logical
        ),
        WithRegistrySelected = Table.AddColumn(
            WithRegistryIsEss,
            "_RegistrySelected",
            each if [_IdAgentKey] <> null then [_IdSelected] else [_SchemaSelected],
            type nullable logical
        ),
        WithAgentKey = Table.AddColumn(
            WithRegistrySelected,
            "AgentKey",
            each
                if [_RegistryAgentKey] <> null then [_RegistryAgentKey]
                else if AgentRegistryScopeMode = "All Agents" and [_AgentIdAliasValue] <> null
                     then "raw:transcript:" & [_AgentIdAliasValue]
                else if AgentRegistryScopeMode = "All Agents" and [_AgentSchemaAliasValue] <> null
                     then "raw:transcript-schema:" & [_AgentSchemaAliasValue]
                else null,
            type nullable text
        ),
        WithAgentLabel = Table.AddColumn(
            WithAgentKey,
            "AgentLabel",
            each
                if [_RegistryAgentLabel] <> null and Text.Trim([_RegistryAgentLabel]) <> "" then [_RegistryAgentLabel]
                else
                    let
                        friendly = try Text.Trim(Text.From([BotFriendlyName])) otherwise "",
                        botName = try Text.Trim(Text.From([BotName])) otherwise ""
                    in if friendly <> "" then friendly else if botName <> "" then botName else [AgentKey],
            type nullable text
        ),
        ScopedAgentCandidates = Table.SelectRows(
            WithAgentLabel,
            each
                [AgentKey] <> null
                and (
                    AgentRegistryScopeMode = "All Agents"
                    or (AgentRegistryScopeMode = "ESS Safe" and [_RegistryIsEss] = true)
                    or (AgentRegistryScopeMode = "Selected Agents" and [_RegistrySelected] = true)
                )
        ),
        AgentRegistryScopedRows =
            if not List.Contains({"ESS Safe", "Selected Agents", "All Agents"}, AgentRegistryScopeMode) then
                error "Agent Scope Mode must be ESS Safe, Selected Agents, or All Agents."
            else if AgentRegistryScopeMode <> "All Agents"
                    and Table.IsEmpty(RegistryTranscriptIdAliases)
                    and Table.IsEmpty(RegistryTranscriptSchemaAliases) then
                error "Agent Registry JSON must contain enabled TranscriptId or TranscriptSchema aliases for the selected scope."
            else if AgentRegistryScopeMode <> "All Agents"
                    and not Table.IsEmpty(NoGhosts)
                    and Table.IsEmpty(ScopedAgentCandidates) then
                error "No transcript agents matched the selected Agent Registry scope."
            else Table.RemoveColumns(
                ScopedAgentCandidates,
                {
                    "_AgentIdAliasValue", "_AgentSchemaAliasValue",
                    "_IdAgentKey", "_IdAgentLabel", "_IdIsEss", "_IdSelected",
                    "_SchemaAgentKey", "_SchemaAgentLabel", "_SchemaIsEss", "_SchemaSelected",
                    "_RegistryAgentKey", "_RegistryAgentLabel", "_RegistryIsEss", "_RegistrySelected"
                },
                MissingField.Ignore
            ),
        // Agent registry scope: end'''


def patch_agent_performance_query(expression: str) -> str:
    if "BotSchemaName = nullable text" not in expression:
        expression = expression.replace(
            "SchemaVersion = nullable text, BotName = nullable text, BotId = nullable text,",
            "SchemaVersion = nullable text, BotName = nullable text, BotId = nullable text, "
            "BotSchemaName = nullable text,",
            1,
        )
        expression = expression.replace(
            "                    BotId                    = try SafeText(metaRec[BotId]) otherwise null,\n"
            "                    AADTenantId",
            '''                    BotId                    = try SafeText(metaRec[BotId]) otherwise null,
                    BotSchemaName            =
                        let
                            metadataSchema =
                                try SafeText(metaRec[BotSchemaName]) otherwise
                                (try SafeText(metaRec[SchemaName]) otherwise
                                (try SafeText(metaRec[BotSchema]) otherwise null)),
                            traceSchemas = List.RemoveNulls(List.Transform(traceActs, each
                                try SafeText(_[value][parentBotSchemaName]) otherwise
                                (try SafeText(_[value][botSchemaName]) otherwise null)))
                        in
                            if metadataSchema <> null and metadataSchema <> "" then metadataSchema
                            else if List.Count(traceSchemas) > 0 then List.First(traceSchemas)
                            else null,
                    AADTenantId''',
            1,
        )
    block = _transcript_scope_block()
    start_marker = "        // Agent registry scope: begin"
    end_marker = "        // Agent registry scope: end"
    if start_marker in expression:
        expression = _replace_marked_block(expression, start_marker, end_marker, block)
    else:
        anchor = (
            "        NoGhosts = Table.SelectRows(DedupedIds,\n"
            "            each [TotalActivityCount] <> null and [TotalActivityCount] > 0),\n"
        )
        if anchor not in expression:
            raise ValueError("Agent Performance NoGhosts anchor not found")
        expression = expression.replace(anchor, anchor + "\n" + block + "\n", 1)
    expression = expression.replace(
        "FilledStart = Table.TransformColumns(NoGhosts, {",
        "FilledStart = Table.TransformColumns(AgentRegistryScopedRows, {",
        1,
    )
    return expression


def _credit_scope_block() -> str:
    return r'''            // Agent registry scope: begin
            AgentCreditsScopeMode = Text.Trim(Text.From(#"Agent Scope Mode")),
            RegistryCreditAliases = Table.Distinct(Table.SelectColumns(
                Table.SelectRows(AgentRegistry, each [Enabled] = true and [AliasType] = "CreditId"),
                {"AliasValueNormalized", "AgentKey", "AgentLabel", "IsEss", "Selected"}
            )),
            WithCreditAlias = Table.AddColumn(
                AddedAgentGUID,
                "_AgentAliasValue",
                each if [AgentGUID] = null then null else Text.Lower(Text.Trim(Text.Trim(Text.From([AgentGUID]), {"{", "}"}))),
                type nullable text
            ),
            WithCreditRegistry = Table.NestedJoin(
                WithCreditAlias,
                {"_AgentAliasValue"},
                RegistryCreditAliases,
                {"AliasValueNormalized"},
                "_agent_registry",
                JoinKind.LeftOuter
            ),
            ExpandedCreditRegistry = Table.ExpandTableColumn(
                WithCreditRegistry,
                "_agent_registry",
                {"AgentKey", "AgentLabel", "IsEss", "Selected"},
                {"_RegistryAgentKey", "_RegistryAgentLabel", "_RegistryIsEss", "_RegistrySelected"}
            ),
            WithCreditAgentKey = Table.AddColumn(
                ExpandedCreditRegistry,
                "AgentKey",
                each
                    if [_RegistryAgentKey] <> null then [_RegistryAgentKey]
                    else if AgentCreditsScopeMode = "All Agents" and [_AgentAliasValue] <> null
                         then "raw:credit:" & [_AgentAliasValue]
                    else null,
                type nullable text
            ),
            WithCreditAgentLabel = Table.AddColumn(
                WithCreditAgentKey,
                "AgentLabel",
                each
                    if [_RegistryAgentLabel] <> null and Text.Trim([_RegistryAgentLabel]) <> "" then [_RegistryAgentLabel]
                    else if [AgentName] <> null and Text.Trim(Text.From([AgentName])) <> "" then Text.From([AgentName])
                    else [AgentKey],
                type nullable text
            ),
            ScopedCreditCandidates = Table.SelectRows(
                WithCreditAgentLabel,
                each
                    [AgentKey] <> null
                    and (
                        AgentCreditsScopeMode = "All Agents"
                        or (AgentCreditsScopeMode = "ESS Safe" and [_RegistryIsEss] = true)
                        or (AgentCreditsScopeMode = "Selected Agents" and [_RegistrySelected] = true)
                    )
            ),
            AgentRegistryScopedCredits =
                if not List.Contains({"ESS Safe", "Selected Agents", "All Agents"}, AgentCreditsScopeMode) then
                    error "Agent Scope Mode must be ESS Safe, Selected Agents, or All Agents."
                else if AgentCreditsScopeMode <> "All Agents" and Table.IsEmpty(RegistryCreditAliases) then
                    error "Agent Registry JSON must contain enabled CreditId aliases when a credits file is supplied."
                else if AgentCreditsScopeMode <> "All Agents"
                        and not Table.IsEmpty(AddedAgentGUID)
                        and Table.IsEmpty(ScopedCreditCandidates) then
                    error "No credit agents matched the selected Agent Registry scope."
                else Table.RemoveColumns(
                    ScopedCreditCandidates,
                    {"_AgentAliasValue", "_RegistryAgentKey", "_RegistryAgentLabel", "_RegistryIsEss", "_RegistrySelected"},
                    MissingField.Ignore
                )
            // Agent registry scope: end'''


def patch_agent_credits_query(expression: str) -> str:
    empty_schema = expression.split("EmptyTable = #table", 1)[0]
    if "AgentKey = nullable text" not in empty_schema:
        expression = expression.replace(
            "ActivityDate = nullable date, AgentGUID = nullable text",
            "ActivityDate = nullable date, AgentGUID = nullable text,\n"
            "        AgentKey = nullable text, AgentLabel = nullable text",
            1,
        )
    block = _credit_scope_block()
    start_marker = "            // Agent registry scope: begin"
    end_marker = "            // Agent registry scope: end"
    if start_marker in expression:
        expression = _replace_marked_block(expression, start_marker, end_marker, block)
    else:
        anchor = (
            '            AddedAgentGUID = Table.AddColumn(AddedActivityDate, "AgentGUID", each\n'
            "                if [AgentId] = null then null\n"
            "                else\n"
            "                    let _id = Text.Trim(Text.From([AgentId]))\n"
            '                    in if Text.StartsWith(_id, "P_", Comparer.OrdinalIgnoreCase) '
            "then Text.Middle(_id, 2) else _id,\n"
            "                type text)\n"
        )
        if anchor not in expression:
            raise ValueError("AgentCredits AddedAgentGUID anchor not found")
        expression = expression.replace(anchor, anchor[:-1] + ",\n" + block + "\n", 1)
    expression = expression.replace(
        "        in\n            AddedAgentGUID\nin\n    result",
        "        in\n            AgentRegistryScopedCredits\nin\n    result",
        1,
    )
    return expression


def patch_conversation_feedback_query(expression: str) -> str:
    if "// Agent registry feedback resolution" in expression:
        fallback_start = "            fallbackAgentKey ="
        label_marker = "            resolvedAgentLabel ="
        if fallback_start in expression:
            start = expression.index(fallback_start)
            end = expression.index(label_marker, start)
            expression = (
                expression[:start]
                + "            resolvedAgentKey = if matched then [MatchedAgentKey] else registryAgentKey,\n"
                + expression[end:]
            )
        return expression
    expression = expression.replace(
        '    Source = #"Agent Performance",\n',
        '''    Source = #"Agent Performance",
    // Agent registry feedback resolution
    AgentFeedbackScopeMode = Text.Trim(Text.From(#"Agent Scope Mode")),
    NormalizeAgentAlias = (value as nullable text) as text =>
        if value = null then "" else Text.Lower(Text.Trim(Text.Trim(Text.From(value), {"{", "}"}))),
    ResolveExternalAgent = (value as nullable text) as nullable record =>
        let
            normalized = NormalizeAgentAlias(value),
            scopedRegistry = Table.SelectRows(AgentRegistry, each
                [Enabled] = true
                and (
                    AgentFeedbackScopeMode = "All Agents"
                    or (AgentFeedbackScopeMode = "ESS Safe" and [IsEss] = true)
                    or (AgentFeedbackScopeMode = "Selected Agents" and [Selected] = true)
                )
            ),
            byKey = Table.SelectRows(scopedRegistry, each Text.Lower([AgentKey]) = normalized),
            byTitle = Table.SelectRows(scopedRegistry, each
                [AliasType] = "M365Title" and [AliasValueNormalized] = normalized),
            matches = Table.Distinct(Table.Combine({byKey, byTitle}), {"AgentKey"}),
            result =
                if normalized = "" or Table.IsEmpty(matches) then null
                else if Table.RowCount(matches) > 1 then error "Feedback AgentId maps to multiple registry agents."
                else Table.First(matches)
        in
            result,
''',
        1,
    )
    expression = expression.replace(
        '{"ConversationTranscriptId", "BotId", "BotName"}',
        '{"ConversationTranscriptId", "BotId", "BotName", "AgentKey", "AgentLabel"}',
        1,
    )
    expression = expression.replace(
        '        AgentId               = [BotId],\n'
        '        Channel               = "Copilot Studio",',
        '        AgentId               = [BotId],\n'
        '        AgentKey              = [AgentKey],\n'
        '        AgentLabel            = [AgentLabel],\n'
        '        Channel               = "Copilot Studio",',
        1,
    )
    field_list = (
        '"FeedbackEventKey","ConversationId","AgentId","Channel","FeedbackSource",'
        '"FeedbackVerdict","MatchStatus"'
    )
    field_list_with_agent = (
        '"FeedbackEventKey","ConversationId","AgentId","AgentKey","AgentLabel","Channel",'
        '"FeedbackSource","FeedbackVerdict","MatchStatus"'
    )
    expression = expression.replace(field_list, field_list_with_agent, 2)
    expression = expression.replace(
        '        {"BotId", "BotName"},\n'
        '        {"MatchedBotId", "MatchedBotName"}',
        '        {"BotId", "BotName", "AgentKey", "AgentLabel"},\n'
        '        {"MatchedBotId", "MatchedBotName", "MatchedAgentKey", "MatchedAgentLabel"}',
        1,
    )
    expression = expression.replace(
        '            matched = [MatchedBotId] <> null or [MatchedBotName] <> null,\n'
        '            eventId =',
        '''            matched = [MatchedAgentKey] <> null,
            sourceAgentId = if [AgentId] = null then "" else Text.Trim(Text.From([AgentId])),
            registryAgent = if matched then null else ResolveExternalAgent(sourceAgentId),
            registryAgentKey = if registryAgent = null then null else registryAgent[AgentKey],
            registryAgentLabel = if registryAgent = null then null else registryAgent[AgentLabel],
            resolvedAgentKey = if matched then [MatchedAgentKey] else registryAgentKey,
            resolvedAgentLabel = if matched then [MatchedAgentLabel] else registryAgentLabel,
            eventId =''',
        1,
    )
    expression = expression.replace(
        '            AgentName             = if [AgentName] <> null and Text.Trim([AgentName]) <> "" '
        'then [AgentName] else [MatchedBotName],',
        '            AgentName             = if [AgentName] <> null and Text.Trim([AgentName]) <> "" '
        'then [AgentName] else if resolvedAgentLabel <> null then resolvedAgentLabel else [MatchedBotName],',
        1,
    )
    expression = expression.replace(
        '            AgentId               = if [AgentId] <> null and Text.Trim([AgentId]) <> "" '
        'then [AgentId] else [MatchedBotId],\n'
        '            Channel               = [Channel],',
        '            AgentId               = if [AgentId] <> null and Text.Trim([AgentId]) <> "" '
        'then [AgentId] else [MatchedBotId],\n'
        '            AgentKey              = resolvedAgentKey,\n'
        '            AgentLabel            = resolvedAgentLabel,\n'
        '            Channel               = [Channel],',
        1,
    )
    expression = expression.replace(
        '    ExternalDeduplicated = Table.Distinct(Table.Buffer(ExternalEvents), {"FeedbackEventKey"}),',
        '    ExternalScoped = Table.SelectRows(ExternalEvents, each [AgentKey] <> null),\n'
        '    ExternalDeduplicated = Table.Distinct(Table.Buffer(ExternalScoped), {"FeedbackEventKey"}),',
        1,
    )
    expression = expression.replace(
        '        {"IsAgentInteraction", type logical}\n',
        '        {"IsAgentInteraction", type logical},\n'
        '        {"AgentKey", type text},\n'
        '        {"AgentLabel", type text}\n',
        1,
    )
    return expression


def build_agent_bridge_expression() -> str:
    return """VAR _perfPairs =
    DISTINCT(
        SELECTCOLUMNS( 'Agent Performance',
            "PK", 'Agent Performance'[AgentKey],
            "PL", 'Agent Performance'[AgentLabel] )
    )
VAR _credPairs =
    DISTINCT(
        SELECTCOLUMNS( AgentCredits,
            "CK", AgentCredits[AgentKey],
            "CL", AgentCredits[AgentLabel] )
    )
VAR _feedbackPairs =
    DISTINCT(
        SELECTCOLUMNS( ConversationFeedback,
            "FK", ConversationFeedback[AgentKey],
            "FL", ConversationFeedback[AgentLabel] )
    )
VAR _keys =
    FILTER(
        DISTINCT(
            UNION(
                SELECTCOLUMNS( _perfPairs, "AgentKey", [PK] ),
                SELECTCOLUMNS( _credPairs, "AgentKey", [CK] ),
                SELECTCOLUMNS( _feedbackPairs, "AgentKey", [FK] )
            )
        ),
        NOT ISBLANK( [AgentKey] )
    )
RETURN
    ADDCOLUMNS(
        _keys,
        "AgentLabel",
            VAR _k = [AgentKey]
            VAR _perfName = MAXX( FILTER( _perfPairs, [PK] = _k ), [PL] )
            VAR _creditName = MAXX( FILTER( _credPairs, [CK] = _k ), [CL] )
            VAR _feedbackName = MAXX( FILTER( _feedbackPairs, [FK] = _k ), [FL] )
            RETURN COALESCE( _perfName, _creditName, _feedbackName, _k )
    )"""


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
                "isHidden": True,
                "isAvailableInMdx": False,
                "annotations": [{"name": "SummarizationSetBy", "value": "Automatic"}],
            }
        )


def set_partition_expression(table: dict, expression: str) -> None:
    source = table["partitions"][0]["source"]
    original = source["expression"]
    source["expression"] = expression.splitlines() if isinstance(original, list) else expression


def get_partition_expression(table: dict) -> str:
    expression = table["partitions"][0]["source"]["expression"]
    return "\n".join(expression) if isinstance(expression, list) else expression


def patch_credit_measures(model: dict) -> None:
    found = set()
    for table in model["tables"]:
        for measure in table.get("measures", []):
            key = (table["name"], measure["name"])
            if key not in MEASURE_NAMES:
                continue
            expression = measure["expression"]
            as_list = isinstance(expression, list)
            text = "\n".join(expression) if as_list else expression
            text = text.replace(
                "'Agent Performance'[BotId]",
                "'Agent Performance'[AgentKey]",
            ).replace(
                "AgentCredits[AgentGUID]",
                "AgentCredits[AgentKey]",
            )
            measure["expression"] = text.splitlines() if as_list else text
            found.add(key)
    missing = sorted(MEASURE_NAMES - found)
    if missing:
        raise ValueError(f"Agent registry measures not found: {missing}")
    performance = next(
        table for table in model["tables"] if table["name"] == "Agent Performance"
    )
    response_rate = next(
        (
            measure
            for measure in performance.get("measures", [])
            if measure["name"] == "Feedback Response Rate"
        ),
        None,
    )
    if response_rate is None:
        raise ValueError("Agent Performance[Feedback Response Rate] not found")
    response_rate["expression"] = (
        "VAR ConversationMatchedFeedback =\n"
        "    CALCULATE(\n"
        "        DISTINCTCOUNT('ConversationFeedback'[ConversationId]),\n"
        "        KEEPFILTERS(\n"
        "            'ConversationFeedback'[MatchStatus] IN "
        '{"Native transcript", "Exact conversation match"}\n'
        "        )\n"
        "    )\n"
        "RETURN DIVIDE(ConversationMatchedFeedback, [Conversations], 0)"
    )


def patch_relationships(model: dict) -> None:
    relationships = model.setdefault("relationships", [])
    for relationship in relationships:
        endpoints = (relationship.get("fromTable"), relationship.get("toTable"))
        if endpoints == ("Agent Performance", "Agent Bridge"):
            relationship["fromColumn"] = "AgentKey"
        elif endpoints == ("AgentCredits", "Agent Bridge"):
            relationship["fromColumn"] = "AgentKey"
    feedback_name = str(
        uuid.uuid5(
            uuid.NAMESPACE_URL,
            "https://github.com/microsoft/ESS/relationships/conversation-feedback-agent-bridge",
        )
    )
    existing = next(
        (
            item
            for item in relationships
            if item.get("fromTable") == "ConversationFeedback"
            and item.get("toTable") == "Agent Bridge"
        ),
        None,
    )
    relationship = {
        "name": feedback_name,
        "fromTable": "ConversationFeedback",
        "fromColumn": "AgentKey",
        "toTable": "Agent Bridge",
        "toColumn": "AgentKey",
    }
    if existing:
        existing.update(relationship)
    else:
        relationships.append(relationship)


def patch_pbit(source: Path, destination: Path) -> dict:
    with zipfile.ZipFile(source, "r") as archive:
        infos = archive.infolist()
        parts = {info.filename: archive.read(info.filename) for info in infos}
    schema = json.loads(parts["DataModelSchema"].decode("utf-16-le"))
    model = schema["model"]
    tables = {table["name"]: table for table in model["tables"]}

    upsert_expression(
        model,
        {
            "name": SCOPE_PARAMETER,
            "kind": "m",
            "expression": SCOPE_PARAMETER_EXPRESSION,
            "description": (
                "Controls agent scope: ESS Safe, Selected Agents, or All Agents. "
                "ESS Safe is the secure default."
            ),
            "lineageTag": SCOPE_PARAMETER_LINEAGE,
            "annotations": [
                {"name": "PBI_NavigationStepName", "value": "Navigation"},
                {"name": "PBI_ResultType", "value": "Text"},
            ],
        },
        "TopicRules",
    )
    upsert_expression(
        model,
        {
            "name": REGISTRY_PARAMETER,
            "kind": "m",
            "expression": REGISTRY_PARAMETER_EXPRESSION,
            "description": (
                "Paste agent-registry.json generated by tools/agent_registry.py. "
                "Required for ESS Safe and Selected Agents modes."
            ),
            "lineageTag": REGISTRY_PARAMETER_LINEAGE,
            "annotations": [
                {"name": "PBI_NavigationStepName", "value": "Navigation"},
                {"name": "PBI_ResultType", "value": "Text"},
            ],
        },
        "TopicRules",
    )
    registry_query = build_agent_registry_query()
    upsert_expression(
        model,
        {
            "name": REGISTRY_QUERY,
            "kind": "m",
            "expression": registry_query,
            "lineageTag": REGISTRY_QUERY_LINEAGE,
            "annotations": [{"name": "PBI_ResultType", "value": "Table"}],
        },
        "TopicRules",
    )

    transforms = {
        "Agent Performance": patch_agent_performance_query,
        "AgentCredits": patch_agent_credits_query,
        "ConversationFeedback": patch_conversation_feedback_query,
    }
    for table_name, transform in transforms.items():
        table = tables[table_name]
        set_partition_expression(table, transform(get_partition_expression(table)))
        add_model_columns(
            table,
            DIRECT_TRANSCRIPT_COLUMNS
            if table_name == "Agent Performance"
            else CANONICAL_COLUMNS,
            f"https://github.com/microsoft/ESS/agent-registry/{table_name}",
        )

    bridge = tables["Agent Bridge"]
    set_partition_expression(bridge, build_agent_bridge_expression())
    patch_credit_measures(model)
    patch_relationships(model)
    parts["DataModelSchema"] = json.dumps(
        schema, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-16-le")

    raw = parts["UnappliedChanges"].decode("utf-16-le")
    for query in (
        {
            "name": SCOPE_PARAMETER,
            "lineageTag": SCOPE_PARAMETER_LINEAGE,
            "description": "Controls agent scope: ESS Safe, Selected Agents, or All Agents.",
            "navigationStepName": "Navigation",
            "text": [SCOPE_PARAMETER_EXPRESSION],
            "loadAsTableDisabled": True,
            "resultType": "Text",
            "isHidden": False,
        },
        {
            "name": REGISTRY_PARAMETER,
            "lineageTag": REGISTRY_PARAMETER_LINEAGE,
            "description": "Paste agent-registry.json generated by tools/agent_registry.py.",
            "navigationStepName": "Navigation",
            "text": [REGISTRY_PARAMETER_EXPRESSION],
            "loadAsTableDisabled": True,
            "resultType": "Text",
            "isHidden": False,
        },
        {
            "name": REGISTRY_QUERY,
            "lineageTag": REGISTRY_QUERY_LINEAGE,
            "text": registry_query.splitlines(),
            "loadAsTableDisabled": True,
            "resultType": "Table",
            "isHidden": False,
        },
    ):
        raw = insert_query_raw(raw, query)
    raw = replace_query_text_raw(raw, SCOPE_PARAMETER, lambda _: SCOPE_PARAMETER_EXPRESSION)
    raw = replace_query_text_raw(raw, REGISTRY_PARAMETER, lambda _: REGISTRY_PARAMETER_EXPRESSION)
    raw = replace_query_text_raw(raw, REGISTRY_QUERY, lambda _: registry_query)
    for table_name, transform in transforms.items():
        raw = replace_query_text_raw(raw, table_name, transform)
    json.loads(raw)
    parts["UnappliedChanges"] = raw.encode("utf-16-le")

    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as archive:
        for info in infos:
            archive.writestr(info, parts[info.filename])
    with zipfile.ZipFile(destination, "r") as archive:
        json.loads(archive.read("DataModelSchema").decode("utf-16-le"))
        json.loads(archive.read("UnappliedChanges").decode("utf-16-le"))
    return {"source": str(source), "destination": str(destination), "status": "ok"}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv-pbit", type=Path, required=True)
    parser.add_argument("--dataverse-pbit", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    results = [
        patch_pbit(args.csv_pbit, args.output_dir / args.csv_pbit.name),
        patch_pbit(args.dataverse_pbit, args.output_dir / args.dataverse_pbit.name),
    ]
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
