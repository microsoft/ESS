# Fabric setup

Use this advanced path when you need multiple Dataverse environments in one report, independently governed Lakehouse history, large-scale ingestion, or Lakehouse-based credit analytics.

If you have one environment and need scheduled refresh, use [Dataverse Direct](./SETUP-Dataverse.md). For a snapshot or proof of concept, use [CSV Upload](./SETUP-CSV-Download.md).

> [!IMPORTANT]
> The PBIT does not archive Dataverse records. Schedule the transcript notebook before records reach the Dataverse retention boundary. Merge mode preserves only records that were successfully ingested.

## Your first successful report

Build the transcript-only baseline first:

1. Download the package and create the Fabric workspace and Lakehouse.
2. Confirm each source agent's supported environment and required transcript settings.
3. Have an administrator create the Entra app registration and Dataverse Application User.
4. Import and configure the transcript-parser notebook.
5. Upload and validate `agent-registry.csv`.
6. Run the notebook and confirm all eight transcript tables exist.
7. Connect Fabric V2 and confirm Total Conversations is non-zero.
8. Add the data needed for other report areas one source at a time.

## Files, portals, and required roles

### Required for the first run

| Need | Data or input | Portal and retrieval steps | Required role | Included helper | Expected file or output |
|---|---|---|---|---|---|
| Transcript capture | Future conversations with node details | [Copilot Studio](https://copilotstudio.microsoft.com) -> open each source agent -> **Settings -> Advanced -> Conversation transcripts** | Agent owner or coauthor with edit access | None | Both transcript settings on; each agent saved and published |
| Fabric destination | Workspace and Lakehouse | [Microsoft Fabric](https://app.fabric.microsoft.com) -> create or select workspace -> **New -> Lakehouse** | Workspace Contributor, Member, or Admin; capacity assigned | None | Attached Lakehouse |
| Dataverse authentication | Entra app registration | [Entra admin center](https://entra.microsoft.com) -> **Identity -> Applications -> App registrations -> New registration** | Account permitted to register applications; Application Developer or Entra administrator help may be required by tenant policy | None | Tenant ID, client ID, secret or approved credential |
| Transcript authorization | Dataverse Application User in each source environment | [Power Platform admin center](https://admin.powerplatform.microsoft.com) -> **Environments -> Settings -> Users + permissions -> Application users** | Power Platform or Dataverse administrator | Bot Transcript Viewer or approved custom role | Application User with organization-level transcript Read |
| Agent scope | Cross-source registry | Follow the [agent registry guide](./AGENT-REGISTRY.md) and upload to `Files/config/agent-registry.csv` | Access to approved agent identifiers | [Transcript notebook](./Fabric/notebooks/Copilot_Agent_Transcript_Parser.ipynb) validation | Reviewed CSV in Lakehouse |
| Transcript ingestion | Dataverse records | Configure and run the required notebook | Fabric notebook execution permission plus application credential | [`Copilot_Agent_Transcript_Parser.ipynb`](./Fabric/notebooks/Copilot_Agent_Transcript_Parser.ipynb) | Eight transcript-derived Delta tables |
| Report | Lakehouse SQL analytics endpoint | Open Lakehouse -> SQL analytics endpoint -> copy connection string and database name | Lakehouse read access and Power BI Desktop | [`ESS - Fabric V2.pbit`](./ESS%20-%20Fabric%20V2.pbit) | Loaded report |

### Optional data for full report functionality

Load only the data needed for the report areas you intend to use. The transcript-only baseline remains functional without these inputs.

| Need | Data or input | Portal and retrieval steps | Required role | Included helper | Why load it / report area enabled |
|---|---|---|---|---|---|
| Copilot Credits | Environment, Agent-Level, and User-Level exports | [Power Platform admin center](https://admin.powerplatform.microsoft.com) -> **Licensing -> Copilot Studio -> Summary -> Download report** | Power Platform Administrator recommended; tenant administrator or Dynamics 365 Administrator also works | [`Copilot_Credit_Consumption_Ingester.ipynb`](./Fabric/notebooks/Copilot_Credit_Consumption_Ingester.ipynb) | Enables the Fabric credit-consumption and value views with tenant, agent, and user totals. |
| Cross-channel feedback | Product Feedback export | [Microsoft 365 admin center](https://admin.microsoft.com) -> **Health -> Product feedback -> Export to CSV** | Microsoft 365 administrator or reader with Product Feedback access | [`tools\ess_feedback_normalizer.py`](./tools/ess_feedback_normalizer.py) ([guide](./FEEDBACK-INGESTION.md)) | Adds Microsoft 365 Copilot and Monitor reactions to the Fabric feedback views; transcript-native reactions already work without this file. |
| Customer-specific topics | Representative transcript evidence, used only when built-in topics need improvement | [Review when to use or skip it](./TOPIC-TUNER.md) | Transcript read access; no extra cloud role | [`tools\ess_topic_tuner.py`](./tools/ess_topic_tuner.py) ([guide](./TOPIC-TUNER.md)) | Improves topic exploration and improvement views for recurring customer language. Skip when native and built-in topics already provide adequate coverage. |
| Organization | Approved HR, Viva Insights, Graph, or Microsoft 365 user export | Source-specific retrieval | Global Reader, User Administrator, or Global Administrator for Microsoft 365 export | No organization-ingestion notebook is included | Use only when organization segmentation is required and a customer-managed Lakehouse ingestion has been implemented; it is not part of the baseline Fabric package. |

## Step 1 - Download the package and create Fabric resources

1. [Download the complete ESS ZIP](https://github.com/microsoft/ESS/archive/refs/heads/main.zip) and extract it.
2. Keep the package folder structure intact.
3. In [Microsoft Fabric](https://app.fabric.microsoft.com), create or select a capacity-backed workspace.
4. Create a Lakehouse.
5. Install [Power BI Desktop](https://powerbi.microsoft.com/desktop/).
6. Install [Python 3.10 or later](https://www.python.org/downloads/windows/) only when you are ready to use the optional local feedback or topic-preparation tools.

The baseline uses:

| Package file | Purpose |
|---|---|
| [`ESS - Fabric V2.pbit`](./ESS%20-%20Fabric%20V2.pbit) | Imports the Lakehouse SQL analytics endpoint |
| [`Fabric\notebooks\Copilot_Agent_Transcript_Parser.ipynb`](./Fabric/notebooks/Copilot_Agent_Transcript_Parser.ipynb) | Required transcript ingestion and parsing |
| [`SampleData\agent-registry.csv`](./SampleData/agent-registry.csv) | Fabricated starter registry to copy and replace |

The credit notebook is optional and should not be run until the transcript-only report works.

## Required preflight - confirm transcript capture

Complete this for every source agent before configuring ingestion:

1. Confirm the agent is in a Production, Sandbox, or Default environment. Microsoft Teams and Microsoft 365 Copilot environments do not persist the required records; Developer environments contain only the maker's conversations.
2. Open the agent in [Copilot Studio](https://copilotstudio.microsoft.com).
3. Select **Settings -> Advanced -> Conversation transcripts**.
4. Turn on **Save conversation transcripts to Dataverse**.
5. Turn on **Include node-level details in transcripts**.
6. Save and publish the agent.
7. Run several new test conversations and allow a few minutes for the records to appear.

The settings affect future conversations only. You need owner or coauthor edit access to change them; ask the agent owner if the controls are unavailable.

## Step 2 - Create the Entra application

Ask an Entra administrator or an application owner permitted by tenant policy to:

1. Sign in to the [Microsoft Entra admin center](https://entra.microsoft.com).
2. Select **Identity -> Applications -> App registrations -> New registration**.
3. Enter a customer-approved name such as `ESS Fabric Transcript Reader`.
4. Keep **Accounts in this organizational directory only** selected and leave Redirect URI blank.
5. Select **Register**.
6. Copy the **Application (client) ID** and **Directory (tenant) ID**.
7. Select **Certificates & secrets -> Client secrets -> New client secret**.
8. Use the shortest approved expiration and copy the secret **Value**, not the Secret ID.

For production, store the credential in an approved secret store and retrieve it with `notebookutils.credentials.getSecret(...)`. Do not commit secrets to the repository or leave a literal secret in a shared notebook.

## Step 3 - Add the Dataverse Application User

A Power Platform or Dataverse administrator must repeat these steps in every source environment:

1. Sign in to the [Power Platform admin center](https://admin.powerplatform.microsoft.com).
2. Select **Environments**, then the environment that hosts the agent.
3. Select **Settings -> Users + permissions -> Application users**.
4. Select **New app user -> Add an app**.
5. Select the app registration, then select **Add**.
6. Choose the business unit.
7. Assign **Bot Transcript Viewer** or a customer-approved custom role with organization-level **Read** on `conversationtranscript`.
8. Select **Create**.

Application permissions can take several minutes to become active. Power Platform Administrator or Environment Maker alone does not grant the application transcript access.

## Step 4 - Build and upload the agent registry

1. Follow [Agent registry and reporting scope](./AGENT-REGISTRY.md).
2. Replace the synthetic rows in `SampleData\agent-registry.csv` with approved customer identifiers.
3. Mark the intended agents enabled and in scope.
4. Review the registry column rules and identifiers.
5. In the Lakehouse, create `Files/config`.
6. Upload the reviewed file as:

```text
Files/config/agent-registry.csv
```

The Fabric notebook reads and validates the CSV directly. It does not use the JSON version or require the local registry validator.

## Step 5 - Import and configure the transcript notebook

1. In the Fabric workspace, select **New -> Import notebook**.
2. Import `Fabric\notebooks\Copilot_Agent_Transcript_Parser.ipynb`.
3. Open the notebook and select **Add lakehouse** to attach the target Lakehouse.
4. Find the **CONFIG** cell.
5. For one environment, set `DATAVERSE_URL` and leave `DATAVERSE_URLS = []`.
6. For several environments, populate `DATAVERSE_URLS` and leave the single URL unused.
7. Set `TENANT_ID`, `CLIENT_ID`, and the approved credential retrieval.
8. Keep `LOOKBACK_DAYS = 7` and `WRITE_MODE = 'merge'` for scheduled incremental ingestion.
9. Set the same approved `AGENT_SCOPE_MODE` used by the registry:
   - `ESS Safe` for enabled rows marked `IsEss=true`;
   - `Selected Agents` for enabled rows marked `Selected=true`; or
   - `All Agents` only as an explicit broad-scope choice.

Use the environment **Instance URL** from Power Apps **Settings -> Session details**, without a trailing slash.

Use `LOOKBACK_DAYS = 0` with `WRITE_MODE = 'overwrite'` only for an intentional full replacement. The notebook rejects overwrite with a bounded lookback because that combination would discard older Lakehouse history.

## Step 6 - Run and validate transcript ingestion

1. Select **Run all** in `Copilot_Agent_Transcript_Parser.ipynb`.
2. Confirm the run ends without a red error cell.
3. Review the printed source and row-count summary.
4. Refresh the Lakehouse Explorer.
5. Confirm these eight tables exist:
   - `agent_sessions`
   - `agent_turns`
   - `agent_errors`
   - `agent_subagents`
   - `agent_catalogue`
   - `agent_performance`
   - `user_feedback`
   - `user_feedback_quarantine`
6. Confirm `agent_sessions` contains non-zero rows and only the intended agent scope.

Stop here if ingestion fails. Optional sources will not repair application credentials, Dataverse permissions, registry errors, or unsupported environments.

## Step 7 - Connect Fabric V2

1. Open the Lakehouse.
2. Open its **SQL analytics endpoint**.
3. Copy the **SQL connection string** and note the Lakehouse/database name.
4. Double-click `ESS - Fabric V2.pbit`.
5. Complete the parameter prompt:

| Template parameter | Baseline value |
|---|---|
| **Fabric SQL Endpoint** | SQL connection string |
| **Lakehouse Name** | Lakehouse/database name |
| **Enable_Dataverse** | `Include` |
| **Enable_ProductFeedback** | `Include` so native transcript reactions are visible |
| **Enable_Agent365** | `Exclude` |
| **Enable_Consumption** | `Exclude` |
| **Enable_CostConsumption** | `Exclude` |

6. When prompted, select **Organizational account**, sign in, and select **Connect**.
7. Select **Home -> Refresh**.

The supplied template uses Import mode.

## Step 8 - Confirm the baseline

Confirm:

- [ ] Total Conversations is non-zero.
- [ ] `agent_catalogue` and `agent_sessions` contain only the agents enabled by the selected registry scope.
- [ ] The report date range matches the ingested records.
- [ ] Lakehouse `agent_sessions` and Power BI totals are plausible for the same scope.
- [ ] The transcript notebook completed without errors and the Lakehouse row counts are plausible.

Schedule the transcript notebook only after a manual end-to-end run succeeds. A daily run with a seven-day merge overlap is recommended; monitor failures so the gap never reaches the Dataverse retention boundary.

## Step 9 - Add data for the report areas you need

### Copilot Credits

1. Import and attach `Fabric\notebooks\Copilot_Credit_Consumption_Ingester.ipynb`.
2. Add a `CreditId` alias for each intended agent to `agent-registry.csv`, then replace `Files/config/agent-registry.csv` with the updated file.
3. Set the credit notebook's `AGENT_SCOPE_MODE` to the same value used by the transcript notebook.
4. In the [Power Platform admin center](https://admin.powerplatform.microsoft.com), select **Licensing -> Copilot Studio -> Summary -> Download report**.
5. Set **Usage type** to `Copilot Credits` and choose one lookback.
6. Download all three types:
   - **Environment Consumption Summary**
   - **Agent-Level Credit Consumption**
   - **User-Level Credit Consumption**
7. Upload exactly one current copy of each file to `Files/credit_consumption`.
8. Remove older copies and `(1)` duplicates.
9. Run the credit notebook and confirm:
   - `credit_consumption_tenant`
   - `credit_consumption_agent`
   - `credit_consumption_user`
10. Set **Enable_Consumption** to `Include` and refresh Power BI.

The notebook reads pre-landed files; it does not acquire the exports. Manual upload is supported. Automated landing requires a separately approved pipeline or flow.

Credit values are decimals. Agent and user exports are overlapping lookback snapshots, not transactions. Retain blank `User Email` rows as unmatched identities.

### Product Feedback

1. Add the agent's `M365Title` alias to `agent-registry.csv`.
2. Replace `Files/config/agent-registry.csv` with the updated registry.
3. Export Product Feedback from **Health -> Product feedback** in the Microsoft 365 admin center.
4. Follow [Cross-channel feedback ingestion](./FEEDBACK-INGESTION.md).
5. Review `feedback-events.audit.json`.
6. Upload the prepared file to `Files/feedback/feedback-events.csv`.
7. Run the transcript notebook.
8. Confirm mapped rows appear in `user_feedback` and review `user_feedback_quarantine`.
9. Keep **Enable_ProductFeedback** set to `Include` and refresh Power BI.

Do not upload the tenant-wide raw export directly.

### Customer-specific topics

1. Follow [Customer-specific topic tuning](./TOPIC-TUNER.md).
2. Review proposed rules and enable only approved rows.
3. Upload the result to:

```text
Files/config/customer-topic-overrides.csv
```

4. Run the transcript notebook and review classification diagnostics.

Native Copilot Studio topics remain authoritative. The built-in taxonomy continues to work when the override file is absent.

### Users and organization data

Fabric V2 treats `copilot_org_data`, `copilot_licensed_users`, and `copilot_interactions_parsed` as optional typed-empty sources so the baseline refresh succeeds without them.

This repository does not include an organization-ingestion notebook. Populate those tables only through a separately designed, governed, and validated Lakehouse process. If Microsoft 365 **Active users** is the approved source, the exporting account needs Global Reader, User Administrator, or Global Administrator.

## Step 10 - Publish and operate

1. Save the validated report as a `.pbix`.
2. Select **Home -> Publish** and choose a workspace where you have Contributor, Member, or Admin access.
3. In Power BI Service, bind the semantic model to an explicit OAuth cloud connection for the Lakehouse SQL analytics endpoint.
4. Configure scheduled refresh.
5. Schedule the transcript notebook or a Fabric pipeline.
6. Monitor ingestion before the Dataverse retention boundary.

See [AUTO-REFRESH.md](./AUTO-REFRESH.md) for publication details.

Before production use, reconcile:

- `agent_sessions` and `agent_catalogue` row counts;
- each credit snapshot to its source total without rounding;
- unmatched blank-email credits;
- `feedback-events.audit.json` to mapped and quarantined feedback; and
- Power BI totals to the same registry scope and date range.

Observed Power Platform exports have no conversation/session ID. Any credit attributed to a conversation, topic, or outcome is a modeled allocation and must reconcile to the exported control total.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `invalid_client` | Wrong secret value, expired credential, or incorrect tenant/client ID | Use the secret **Value**, verify expiration, and recopy IDs |
| Dataverse request is forbidden | Application User or transcript role is missing in that environment | Add the app to every source environment and assign organization-level transcript Read |
| Registry validation fails | Duplicate, ambiguous, or inactive aliases | Correct `agent-registry.csv` and validate again |
| Older history disappears | Notebook used unsafe overwrite or never ingested records before retention | Restore the approved merge configuration; expired source records cannot be recovered |
| Credit notebook rejects files | Duplicate or overlapping exports are present | Keep exactly one current file of each type |
| Power BI baseline is empty | Required tables are empty, wrong endpoint/database, or agent scope excludes rows | Validate notebook counts, connection parameters, and registry scope |
| Organization visuals are blank | Optional customer-managed tables are not populated | Implement and validate a governed organization-ingestion process |

## Attribution and help

The Fabric notebooks adapt the MIT-licensed [StudioLens-for-Copilot-Studio](https://github.com/Keithland89/StudioLens-for-Copilot-Studio) project by Keithland89. The original license references are retained in both notebooks.

- [Return to data-path selection](./README.md#choose-your-data-path)
- [Open a GitHub issue](https://github.com/microsoft/ESS/issues)
- Review **Appendix: Glossary** and the notebook's validation output
