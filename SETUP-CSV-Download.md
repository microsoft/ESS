# CSV Upload setup

Use this path for evaluation, one-time snapshots, offline copies, or controlled sharing. Allow about **20-30 minutes** for the first setup.

For ongoing production reporting from one environment, use [Dataverse Direct](./SETUP-Dataverse.md). For multiple environments or durable Lakehouse history, use [Fabric](./SETUP-Fabric.md).

## Your first successful report

Complete only the required steps first:

1. Download and extract the complete ESS package.
2. Confirm the supported environment and required transcript settings.
3. Export the untouched `ConversationTranscript` CSV.
4. Create and validate `agent-registry.json`.
5. Open CSV V18 with those two inputs.
6. Confirm Total Conversations is non-zero and the intended agent appears.
7. Add the data needed for other report areas one source at a time.

## Files, portals, and required roles

### Required for the first run

| Need | Data or input | Portal and retrieval steps | Required role | Included helper | Expected file or output |
|---|---|---|---|---|---|
| Transcript capture | Future conversations with node details | [Copilot Studio](https://copilotstudio.microsoft.com) -> open agent -> **Settings -> Advanced -> Conversation transcripts** | Agent owner or coauthor with edit access | None | Both transcript settings on; agent saved and published |
| Conversations | `ConversationTranscript` table | [Power Apps](https://make.powerapps.com) -> select environment -> **Tables -> All -> ConversationTranscript -> Export -> Export data** | Bot Transcript Viewer, or custom role with organization-level Read on `conversationtranscript`; Environment Maker alone is insufficient | None | Untouched `ConversationTranscripts.csv` |
| Safe agent scope | Agent identifiers and friendly name | Use the transcript CSV to identify `BotId`, then follow the [agent registry guide](./AGENT-REGISTRY.md) | Access to the exported transcript CSV; no extra cloud role | [`tools\agent_registry.py`](./tools/agent_registry.py) | `agent-registry.json` |
| Report | CSV V18 | Included in the extracted package | Power BI Desktop user | [`ESS Dashboard - Dynamic Topics (CSV) V18.pbit`](./ESS%20Dashboard%20-%20Dynamic%20Topics%20%28CSV%29%20V18.pbit) | Loaded report |

### Optional data for full report functionality

Load only the data needed for the report areas you intend to use. The transcript-only baseline remains functional without these inputs.

| Need | Data or input | Portal and retrieval steps | Required role | Included helper | Why load it / report area enabled |
|---|---|---|---|---|---|
| Organization | User roster | [Microsoft 365 admin center](https://admin.microsoft.com) -> **Users -> Active users -> Export users**, or an approved HR/Viva Insights/Graph source | Global Reader, User Administrator, or Global Administrator for the Microsoft 365 export | Built into [CSV V18](./ESS%20Dashboard%20-%20Dynamic%20Topics%20%28CSV%29%20V18.pbit) | Adds department, country, job title, and display-name segmentation to **Adoption** and user-level analysis. |
| Copilot Credits | User-Level Credit Consumption | [Power Platform admin center](https://admin.powerplatform.microsoft.com) -> **Licensing -> Copilot Studio -> Summary -> Download report** | Power Platform Administrator recommended; tenant administrator or Dynamics 365 Administrator also works | Built into [CSV V18](./ESS%20Dashboard%20-%20Dynamic%20Topics%20%28CSV%29%20V18.pbit) | Adds observed credit totals and modeled cost/value measures to **Executive Summary** and **Business Impact**. |
| Cross-channel feedback | Product Feedback export | [Microsoft 365 admin center](https://admin.microsoft.com) -> **Health -> Product feedback -> Export to CSV** | Microsoft 365 administrator or reader with Product Feedback access | [`tools\ess_feedback_normalizer.py`](./tools/ess_feedback_normalizer.py) ([guide](./FEEDBACK-INGESTION.md)) | Adds Microsoft 365 Copilot and Monitor reactions to **Agent Feedback**; transcript-native reactions already work without this file. |
| Customer-specific topics | Representative transcript evidence, used only when built-in topics need improvement | [Review when to use or skip it](./TOPIC-TUNER.md) | Transcript read access; no extra cloud role | [`tools\ess_topic_tuner.py`](./tools/ess_topic_tuner.py) ([guide](./TOPIC-TUNER.md)) | Improves classification of recurring customer language in **Conversation Details**, **Improvement Opportunities**, and **Adjust Topic Assumptions**. Skip when native and built-in topics already provide adequate coverage. |

## Prepare the package and tools

1. [Download the complete ESS ZIP](https://github.com/microsoft/ESS/archive/refs/heads/main.zip).
2. Select **Extract All** and keep the extracted folder structure intact.
3. Install [Power BI Desktop](https://powerbi.microsoft.com/desktop/).
4. Install [Python 3.10 or later](https://www.python.org/downloads/windows/) and select **Add Python to PATH**. The included tools use only the standard library.
5. Create a working folder such as `C:\AgentData`.

Do not download individual scripts or templates; the files in the package were tested together.

## Required preflight - confirm transcript capture

Before exporting data:

1. Confirm the agent is in a Production, Sandbox, or Default environment. Microsoft Teams and Microsoft 365 Copilot environments do not persist the required records; Developer environments contain only the maker's conversations.
2. Open the agent in [Copilot Studio](https://copilotstudio.microsoft.com).
3. Select **Settings -> Advanced -> Conversation transcripts**.
4. Turn on **Save conversation transcripts to Dataverse**.
5. Turn on **Include node-level details in transcripts**.
6. Save and publish the agent.
7. Run several new test conversations and allow a few minutes for the records to appear.

The settings affect future conversations only. You need owner or coauthor edit access to change them; ask the agent owner if the controls are unavailable.

## Step 1 — Export your conversation transcripts ✅ Required

1. Sign in to [Power Apps](https://make.powerapps.com).
2. Use the environment selector in the upper-right corner to choose the environment that hosts the ESS agent.
3. In the left navigation, select **Tables**.
4. Select **All**, search for `conversation`, and open **ConversationTranscript**.
5. Select **Export -> Export data**.
6. Wait for the export to finish, then select **Download exported data**.
7. Extract the downloaded ZIP.
8. Move the CSV to your working folder and rename it `ConversationTranscripts.csv`.

> [!CAUTION]
> Do not open or save the transcript CSV in Excel. Excel can alter the JSON in the `Content` column and cause `M Engine error: Token Identifier expected`. Re-export the file if it was saved in Excel.

The export is a snapshot of records that still exist in Dataverse. It is not cumulative history. A later export cannot recover transcripts already deleted by retention.

If **ConversationTranscript** is missing or the export is empty:

- confirm the account has Bot Transcript Viewer in the selected environment;
- confirm the agent is in a Production, Sandbox, or Default environment;
- confirm transcript capture is enabled; and
- allow a few minutes after new test conversations.

## Step 2 - Create the required agent registry

The registry ensures the template reports only approved agents and gives technical IDs a stable display name.

1. Follow [Agent registry and reporting scope](./AGENT-REGISTRY.md).
2. Use the transcript CSV to identify the agent's `BotId`.
3. Copy and edit the included starter registry.
4. Run the included validator to create `agent-registry.json` with `ESS Safe` scope.
5. Do not continue until the validator reports at least one active agent.

The exact command and column definitions are in [Build registry JSON for CSV V18](./AGENT-REGISTRY.md#step-7---build-registry-json-for-csv-v18).

## Step 3 - Open CSV V18

1. Double-click `ESS Dashboard - Dynamic Topics (CSV) V18.pbit`.
2. Complete the parameter prompt:

| Parameter | First-run value |
|---|---|
| **Copilot Studio Transcript** | Full path to the untouched `ConversationTranscripts.csv` |
| **Org Data File** | Leave blank |
| **Agent Credits (optional)** | Leave blank |
| **Agent Scope Mode** | `ESS Safe` |
| **Agent Registry JSON** | Paste the complete contents of `agent-registry.json` |
| **Customer Topic Overrides JSON (optional)** | Leave blank |
| **Feedback Events JSON (optional)** | Leave blank |

3. Select **Load**.
4. If prompted for file privacy, use the same approved privacy level for the local files.

Windows paths use backslashes, for example `C:\AgentData\ConversationTranscripts.csv`. Paste the raw path without quotation marks.

## Step 4 - Confirm the baseline

On the **Adoption** page, whose report title is **Organization Adoption**, confirm:

- [ ] Total Conversations is non-zero and is plausible for the export.
- [ ] Total Users is plausible and is not identical to Total Conversations.
- [ ] The date trend matches the export period.
- [ ] The Agent filter shows the intended friendly name.
- [ ] The **Glossary** page's load-diagnostics entry shows no blocking parser error.

Stop here if the baseline fails. Optional inputs will not repair missing transcript access, unsupported environments, retention gaps, or corrupted transcript JSON.

### Validate with the included synthetic data

Use these files from `SampleData`:

- `ConversationTranscripts.csv`
- `agent-registry.json`

With `ESS Safe`, the baseline should show **168 conversations** and **25 users**. Optional synthetic files can then be added to test the remaining inputs.

## Step 5 - Add data for the report areas you need

Add one enhancement, refresh, and validate it before adding the next.

### Organization data

1. In the [Microsoft 365 admin center](https://admin.microsoft.com), select **Users -> Active users -> Export users**.
2. Confirm the file contains a user identifier such as `User principal name`.
3. Save it as `OrgData.csv`.
4. In Power BI Desktop, select **Transform data -> Edit parameters** and set **Org Data File** to its full path.
5. Refresh and confirm organization labels appear.

The template accepts `UserPrincipalName`, `UPN`, or `PersonId`. Department, Country, JobTitle, DisplayName, and Email are optional; missing attributes remain blank.

### Copilot Credits

1. In the [Power Platform admin center](https://admin.powerplatform.microsoft.com), select **Licensing -> Copilot Studio -> Summary -> Download report**.
2. Set **Usage type** to `Copilot Credits`.
3. Choose a 30-day lookback.
4. Download **User-Level Credit Consumption**.
5. Follow [Find the credit identifier](./AGENT-REGISTRY.md#step-3---find-the-credit-identifier) to add the export's `Agent Id` as a `CreditId` alias.
6. Rebuild `agent-registry.json`; a `TranscriptId` row does not replace the required `CreditId` row even when both values are the same GUID.
7. In **Transform data -> Edit parameters**, replace **Agent Registry JSON**, set **Agent Credits (optional)** to the export path, and refresh.
8. Confirm the credit totals are non-zero and plausible for the selected agent and lookback.

The source has no conversation ID. Total and billable credits are observed; cost per resolved conversation, net value, and ROI are modeled allocations.

### Product Feedback

Do not load the tenant-wide raw export directly.

1. Add the agent's `M365Title` alias to the registry.
2. Rebuild `agent-registry.json` with the included registry validator.
3. Export Product Feedback from **Health -> Product feedback** in the Microsoft 365 admin center.
4. Follow [Cross-channel feedback ingestion](./FEEDBACK-INGESTION.md).
5. Review `feedback-events.audit.json`.
6. Paste the updated registry JSON into **Agent Registry JSON** and the prepared feedback JSON into **Feedback Events JSON (optional)**, then refresh.

### Customer-specific topics

1. Follow [Private adaptive topic tuning](./TOPIC-TUNER.md).
2. Review proposed rules and enable only approved rows.
3. Paste `customer-topic-overrides.json` into the optional parameter.
4. Refresh and review topic diagnostics.

Native Copilot Studio topics remain authoritative. Uncertain rules stay disabled or unassigned.

## Step 6 - Refresh and publish

| Goal | Action |
|---|---|
| Refresh a snapshot | Replace the transcript CSV at the same path, then select **Home -> Refresh** |
| Publish | Select **Home -> Publish** and choose a workspace where you have Contributor or higher |
| Schedule without a gateway | Host supported CSV inputs in SharePoint or OneDrive and follow [AUTO-REFRESH.md](./AUTO-REFRESH.md) |
| Use a local or network path | Configure an on-premises data gateway |

Keep snapshot coverage dates consistent. Do not add overlapping weekly exports together as if they were transactions.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `ConversationTranscript` is missing | Transcript role is missing or wrong environment selected | Ask an admin to grant Bot Transcript Viewer and recheck the environment selector |
| `M Engine error: Token Identifier expected` | CSV was saved by Excel | Re-export and load the untouched file |
| Total Conversations is zero | Unsupported environment, no retained records, or registry excludes the agent | Check environment type, retention, transcript capture, and registry validation |
| Intended agent is missing | Wrong `BotId` or inactive registry row | Rebuild `agent-registry.json` and confirm `ESS Safe` has an active agent |
| Organization charts are blank | Optional file is missing or user identifiers do not match | Confirm UPN values and the Org Data parameter |
| Credit visuals are blank | No matching `Agent Id` in the User-Level export | Check the export window and registry `CreditId` |
| Feedback is missing | Raw export was not normalized or `M365Title` is wrong | Review the normalizer audit and registry alias |

## Need help?

- [Return to data-path selection](./README.md#choose-your-data-path)
- [Open a GitHub issue](https://github.com/microsoft/ESS/issues)
- Review the report's **Glossary**, including its load-diagnostics entry
