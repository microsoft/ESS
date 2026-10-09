# Agent registry and reporting scope

The agent registry is a small customer-controlled CSV that tells ESS Insights which identifiers belong to the same Copilot Studio agent. It prevents feedback or credit usage from another tenant agent from entering ESS totals.

| Source | Alias type | Example |
|---|---|---|
| Conversation transcripts | `TranscriptId` or `TranscriptSchema` | Agent GUID or Copilot Studio schema name |
| Power Platform Copilot Credits | `CreditId` | Agent GUID from the credit export |
| Microsoft 365 Product Feedback | `M365Title` | Title ID beginning with `T_` |

The registry contains identifiers and display labels only. It does not contain prompts, responses, transcripts, user identities, or credentials.

## Choose the reporting scope

| Mode | Use it when | Behavior |
|---|---|---|
| **ESS Safe** | You want only ESS agents | Includes enabled rows where `IsEss=true`; this is the recommended default |
| **Selected Agents** | You want a chosen set of agents | Includes enabled rows where `Selected=true` |
| **All Agents** | You intentionally want every transcript and credit agent | Includes known and unknown transcript/credit agents; Product Feedback still requires a registry match |

Blank, disabled, unrelated, or ambiguous Product Feedback identifiers never enter agent KPIs.

## Before you start

1. [Download the complete ESS package](https://github.com/microsoft/ESS/archive/refs/heads/main.zip) and select **Extract All**.
2. Open the extracted `ESS-main` folder. Keep `tools/agent_registry.py` and `SampleData/agent-registry.csv` in their original locations.
3. Create a customer-controlled folder such as `C:\AgentData`.
4. Copy [`SampleData/agent-registry.csv`](SampleData/agent-registry.csv) into that folder.
5. Rename the copy `agent-registry.csv`.
6. Open the copied file in Excel or a text editor. It is safe to edit this file in Excel; do not open the raw conversation transcript CSV in Excel.

You will replace the fabricated example values with your own agent identifiers.

## Step 1 - Choose the agent name and key

For every row that belongs to the same agent, use the same values:

- `AgentKey`: a short permanent reporting key, such as `employee-self-service`. Use letters, numbers, periods, underscores, colons, or hyphens; do not use spaces.
- `AgentLabel`: the friendly name shown in the report, such as `Employee Self-Service`.
- `IsEss`: `true` for an ESS agent; otherwise `false`.
- `Selected`: `true` when the agent should be included in **Selected Agents** mode.
- `Enabled`: `true` to use the row.

Do not reuse an `AgentKey` for a different agent later.

## Step 2 - Find the transcript identifier

At least one `TranscriptId` or `TranscriptSchema` row is required for **ESS Safe** and **Selected Agents**.

### If you use the CSV template

Use PowerShell so the transcript CSV is not modified:

```powershell
Import-Csv "C:\AgentData\ConversationTranscripts.csv" |
  Select-Object BotName,BotId |
  Sort-Object BotId -Unique |
  Format-Table
```

Find the ESS agent by `BotName` and copy its `BotId`. Add it to the registry as:

```text
AliasType = TranscriptId
AliasValue = the BotId GUID
```

If the command shows more than one agent, create separate registry rows and distinct `AgentKey` values for each agent you intend to report.

### If you use Dataverse Direct or Fabric

1. Open the agent in [Copilot Studio](https://copilotstudio.microsoft.com).
2. Look at the browser address. Copy the identifier after `/bots/` and before the next `/`.
3. If that value is a GUID, add it as `TranscriptId`.
4. If it is a schema-style value, add it as `TranscriptSchema`.

If you can export a small ConversationTranscript CSV, the PowerShell method above is the most reliable confirmation.

## Step 3 - Find the credit identifier

Skip this step if you are not loading Copilot Credits.

1. Download the **Agent-Level Credit Consumption** or **User-Level Credit Consumption** report from the [Power Platform admin center](https://admin.powerplatform.microsoft.com): **Licensing → Copilot Studio → Summary → Download report**.
2. Open that credit CSV.
3. Filter `Agent Name` to the ESS agent.
4. Copy the corresponding `Agent Id`.
5. Add it to the registry as:

```text
AliasType = CreditId
AliasValue = the Agent Id GUID
```

The tool accepts either a bare GUID or a value beginning with `P_`; it normalizes both forms.

## Step 4 - Find the Microsoft 365 feedback identifier

Skip this step if you are not loading Microsoft 365 Product Feedback.

1. Publish the Copilot Studio agent to Microsoft 365 Copilot.
2. Submit one harmless controlled thumbs reaction to that agent.
3. Export **Health → Product feedback** from the Microsoft 365 admin center.
4. Find the controlled row by its unique comment, time, or test prompt.
5. In **Agent ID**, copy only the value beginning with `T_`.
6. Add it to the registry as:

```text
AliasType = M365Title
AliasValue = the T_... title ID
```

See [Microsoft 365 Copilot feedback: export, prepare, and load](FEEDBACK-INGESTION.md) for every click and the privacy rules.

If Agent ID is blank, do not create an alias from the app name, user, timestamp, prompt, or response. That row cannot be safely attributed to ESS.

## Step 5 - Fill the environment fields

For a single-environment CSV or Dataverse report, the environment fields can be blank. For Fabric or a master registry containing several environments, fill them:

- `EnvironmentKey`: a stable customer-chosen key such as `production-us`;
- `EnvironmentName`: a friendly display name; and
- `EnvironmentUrl`: the Dataverse URL, such as `https://orgabc12345.crm.dynamics.com`.

Use the same environment values on every alias row for that agent/environment.

## Step 6 - Review the completed CSV

Use one row per alias and repeat the agent metadata:

```csv
RegistryVersion,AgentKey,AgentLabel,IsEss,Selected,Enabled,EnvironmentKey,EnvironmentName,EnvironmentUrl,AliasType,AliasValue
1,employee-self-service,Employee Self-Service,true,true,true,production,Production,https://orgabc12345.crm.dynamics.com,TranscriptId,00000000-0000-0000-0000-000000000001
1,employee-self-service,Employee Self-Service,true,true,true,production,Production,https://orgabc12345.crm.dynamics.com,CreditId,00000000-0000-0000-0000-000000000001
1,employee-self-service,Employee Self-Service,true,true,true,production,Production,https://orgabc12345.crm.dynamics.com,M365Title,T_example
```

Column rules:

- `RegistryVersion` must be `1`.
- `AliasType` must be `TranscriptId`, `TranscriptSchema`, `CreditId`, or `M365Title`.
- Boolean columns must be `true` or `false`.
- An enabled alias cannot map to more than one agent in the same environment.
- Do not add a blank alias row.

## Step 7 - Build and validate the registry

1. Open the extracted `ESS-main` folder in File Explorer.
2. Click the address bar, type `powershell`, and press **Enter**.
3. Confirm Python:

```powershell
python --version
```

Python 3.10 or later is sufficient and no packages need to be installed. If `python` is not recognized, install Python from [python.org](https://www.python.org/downloads/windows/), select **Add Python to PATH**, reopen PowerShell, and retry.

4. Run:

```powershell
python tools\agent_registry.py `
  --input "C:\AgentData\agent-registry.csv" `
  --output-json "C:\AgentData\agent-registry.json" `
  --scope-mode "ESS Safe"
```

Success prints a short JSON summary containing `registryRows`, `agents`, `activeAgents`, `scopeMode`, and `aliasCounts`. The command also creates `C:\AgentData\agent-registry.json`.

The command stops with a clear error for invalid booleans, unknown alias types, conflicting metadata, ambiguous aliases, or a scope with no active agents. Correct the CSV and run it again.

### Registry with several environments

Fabric can use the full master CSV. CSV V18 and Dataverse V19 report one environment per refresh, so create a filtered JSON file:

```powershell
python tools\agent_registry.py `
  --input "C:\AgentData\agent-registry.csv" `
  --environment-key "production-us" `
  --output-json "C:\AgentData\agent-registry.json" `
  --scope-mode "ESS Safe"
```

Replace `production-us` with the exact `EnvironmentKey` in your CSV.

## Step 8 - Load the registry

### CSV V18 and Dataverse V19

1. Open the report in Power BI Desktop.
2. Select **Home → Transform data → Edit parameters**.
3. Set **Agent Scope Mode** to `ESS Safe`, `Selected Agents`, or `All Agents`.
4. Open `C:\AgentData\agent-registry.json` in Notepad.
5. Select all text, copy it, and paste it into **Agent Registry JSON**.
6. Select **OK**, then refresh.

`ESS Safe` and `Selected Agents` stop with an error when the registry is blank or no transcript agent matches. `All Agents` permits unmapped transcript and credit agents but still excludes unregistered Product Feedback.

### Fabric V2

1. Open the Lakehouse attached to both notebooks.
2. Open **Files** and create the `config` folder if needed.
3. Upload `agent-registry.csv` to:

```text
Files/config/agent-registry.csv
```

4. Set the same `AGENT_SCOPE_MODE` value in both notebook CONFIG cells.
5. Run the transcript parser first, then the credit ingester.

Fabric writes the canonical agent identity to every transcript-derived table. It sends identifier-only details for unmapped external feedback and credits to quarantine tables; it does not infer an environment from an agent name.

## Product Feedback command

After the `M365Title` row is validated, prepare the tenant-wide Product Feedback export:

```powershell
python tools\ess_feedback_normalizer.py `
  --input "C:\AgentData\ProductFeedback.csv" `
  --agent-registry "C:\AgentData\agent-registry.csv" `
  --scope-mode "ESS Safe" `
  --output "C:\AgentData\feedback-events.csv"
```

The normalizer changes the Product Feedback `T_...` ID to the canonical `AgentKey`. The legacy repeatable `--agent-id` option filters rows only and does not unify transcript and credit identities; use the registry for production.

## Attribution boundary

The registry proves which published agent received a reaction. Microsoft 365 Product Feedback does not export the supported conversation identifier needed to join that reaction to one exact transcript turn or child agent. Report agent-level feedback as observed; keep per-conversation and child-agent attribution separate.
