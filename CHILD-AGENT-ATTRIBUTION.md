# Parent and child agent attribution

Child-agent reporting isn't limited to the Fabric path. CSV V18, Dataverse V19, and Fabric V2 all read `ConnectedAgentInitializeTraceData` and `ConnectedAgentCompletedTraceData` when those events are present in enhanced Copilot Studio transcripts.

## Required transcript setting

In Copilot Studio, open the agent's **Settings → Advanced → Conversation transcripts** and enable **Include node-level details in transcripts**, then republish the agent. The setting affects future conversations only.

Without connected-agent trace events, the report can't infer which child agent participated.

## CSV V18 and Dataverse V19

Each conversation in `Agent Performance` includes:

- parent agent name and ID;
- child agent friendly names, schema names, and IDs when available;
- invocation and completion states;
- dialog and plan-step identifiers;
- distinct child and invocation counts; and
- a readable detail such as `SAP Agent (Completed); HR Agent (Completed)`.

The **Improvement Opportunities** Fix-It Queue includes a **Child Agent** column. Multiple children remain a semicolon-separated list rather than being forced into one value. Failed child calls are labeled with their completion state, such as `Finance Agent (Failed)`.

## Fabric V2

Fabric keeps the same conversation-level summary in `agent_sessions` and `agent_performance`, and also writes the event-grain `agent_subagents` bridge.

The bridge includes:

- a non-null, deterministic sub-agent event key used for incremental Delta merges;
- conversation ID and invocation timestamp;
- parent and connected-agent schema, ID, and friendly name;
- initialize/completed event type;
- invocation/completion state;
- dialog and plan-step IDs; and
- child error code and message when supplied by the trace.

This event table supports one parent calling one or many children without losing the individual invocations.
When a trace omits schema or plan-step identifiers, the event key falls back through
activity ID, timestamp plus available child identity, and finally event sequence, so the
default incremental merge does not reject valid trace rows.

## Naming behavior

Copilot Studio trace payloads don't always include a friendly child-agent name. The parser uses the friendly name when present, then falls back to the child schema name, then the child ID. A schema fallback is still a reliable technical identifier but might need a customer-maintained display-name mapping for executive reporting.

## Validation scenarios

The release regression covers:

1. one completed child agent;
2. two completed child agents in one conversation; and
3. one failed child-agent call.

The expected details are `SAP Agent (Completed)`, `SAP Agent (Completed); HR Agent (Completed)`, and `Finance Agent (Failed)`.
