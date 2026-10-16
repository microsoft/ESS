# Dataverse Direct setup

This is the recommended path for ongoing production reporting from one supported Dataverse environment. Allow about **15-25 minutes** for the first setup.

Dataverse Direct reads the `ConversationTranscript` table through the Dataverse connector. **Do not export a ConversationTranscript CSV for this template.** Transcript CSV exports are supported only by the [CSV Upload path](./SETUP-CSV-Download.md).

## Three customer actions

1. **Prepare access and copy the URL.** Confirm transcript capture and read access, then copy the Dataverse Environment URL.
2. **Run the guided setup and validate the report.** Start with the URL only to isolate access errors, then add the data needed for your report areas one source at a time.
3. **Publish only if needed.** Keep the validated PBIX for Desktop use, or follow the collapsed publication section for Power BI Service.

## Files, portals, and required roles

### Required template input

| Need | Data or input | Portal and retrieval steps | Required role | Included helper | Expected file or output |
|---|---|---|---|---|---|
| Live conversations | Dataverse Environment URL | [Power Apps](https://make.powerapps.com) -> select environment -> **Settings -> Session details -> Instance url** | Bot Transcript Viewer, or custom role with organization-level Read on `conversationtranscript`; Environment Maker alone is insufficient | [Guided Dataverse setup](#action-2---run-the-guided-setup-and-validate-the-report) | URL such as `https://org.crm.dynamics.com` |

### Optional data for full report functionality

Load only the data needed for the report areas you intend to use. The transcript-only baseline remains functional without these inputs.

| Need | Data or input | Portal and retrieval steps | Required role | Included helper | Why load it / report area enabled |
|---|---|---|---|---|---|
| Friendly names or cross-source aliases | Agent registry | Follow the [agent registry guide](./AGENT-REGISTRY.md) | Access to approved agent identifiers | [Agent registry guide](./AGENT-REGISTRY.md) | Use for stable Agent filter labels and to reconcile credits or Microsoft 365 feedback to the correct agent across report pages. Required when loading external Product Feedback. |
| Organization | User roster | [Microsoft 365 admin center](https://admin.microsoft.com) -> **Users -> Active users -> Export users**, or approved HR/Viva Insights/Graph source | Global Reader, User Administrator, or Global Administrator for Microsoft 365 export | Included guided setup | Adds department, country, job title, and display-name segmentation to **Adoption** and user-level analysis. |
| Copilot Credits | User-Level Credit Consumption | [Power Platform admin center](https://admin.powerplatform.microsoft.com) -> **Licensing -> Copilot Studio -> Summary -> Download report** | Power Platform Administrator recommended; tenant administrator or Dynamics 365 Administrator also works | Included guided setup | Adds observed credit totals and modeled cost/value measures to **Executive Summary** and **Business Impact**. |
| Cross-channel feedback | Raw Product Feedback or Monitor export plus agent registry | [Microsoft 365 admin center](https://admin.microsoft.com) -> **Health -> Product feedback -> Export to CSV** | Microsoft 365 administrator or reader with Product Feedback access | Included guided setup ([feedback guide](./FEEDBACK-INGESTION.md)) | Adds Microsoft 365 Copilot and Monitor reactions to **Agent Feedback**; transcript-native reactions already work without this file. |
| Customer-specific topics | Representative transcript evidence, used only when built-in topics need improvement | [Review when to use or skip it](./TOPIC-TUNER.md) | Transcript read access; no extra cloud role | [Optional topic tuner](./TOPIC-TUNER.md) | Improves classification of recurring customer language in **Conversation Details**, **Improvement Opportunities**, and **Adjust Topic Assumptions**. Skip when native and built-in topics already provide adequate coverage. |

## Action 1 - Prepare access and copy the URL

Ask a Power Platform administrator to grant the report account one of:

- **Bot Transcript Viewer** in the environment that hosts the agent; or
- a customer-approved custom role with organization-level **Read** on `conversationtranscript`.

Tenant administrator, Power Platform Administrator, and Environment Maker do not automatically grant transcript-table access.

Transcript capture is a **preflight setting**, not a file or template input. Open the agent in [Copilot Studio](https://copilotstudio.microsoft.com) and confirm:

1. **Settings -> Advanced -> Conversation transcripts -> Save conversation transcripts to Dataverse** is on.
2. **Include node-level details in transcripts** is on.
3. The agent is saved and published.
4. Several new test conversations exist.

Use a Production, Sandbox, or Default environment. Microsoft Teams and Microsoft 365 Copilot environments do not persist the required records; Developer environments contain only the maker's conversations.

Then copy the only required template input:

1. Sign in to [Power Apps](https://make.powerapps.com) with the same account.
2. Use the environment selector in the upper-right corner to select the environment that contains the agent.
3. Select the **Settings** gear -> **Session details**.
4. Copy **Instance url** or **Org URL**.
5. Remove the trailing slash.

Example:

```text
https://orgabc12345.crm.dynamics.com
```

This solution targets one environment per report. Use Fabric if one report must combine several environments.

## Action 2 - Run the guided setup and validate the report

1. [Download the complete ESS ZIP](https://github.com/microsoft/ESS/archive/refs/heads/main.zip).
2. Select **Extract All** and keep the extracted folder structure intact.
3. Install [Power BI Desktop](https://powerbi.microsoft.com/desktop/).
4. Open the extracted `ESS-main` folder and double-click `START-HERE-DATAVERSE.cmd`.
5. Paste the Environment URL and skip optional data for the first run.
6. When the guided checks complete, open the report.

The report prompts for:

| Parameter | Baseline value |
|---|---|
| **Dataverse Environment URL** | Prefilled by guided setup |
| **Transcript Lookback Days** | Leave blank for the 90-day default, or enter a smaller retained window |
| **Org Data File** | Blank |
| **Agent Credits (optional)** | Blank |
| **Customer Topic Overrides JSON (optional)** | Blank |
| **Feedback Events JSON (optional)** | Blank |

1. Wait until every prefilled parameter value is visible and has stopped changing. Power BI fills these values asynchronously.
2. Only then select **Load**.
3. When prompted for Dataverse credentials, select **Organizational account**.
4. Select **Sign in**, complete authentication, and select **Connect**.

> [!IMPORTANT]
> If Power BI reports that queries are blocked or that a cyclic reference was encountered, close that report without saving and reopen the report from the guided setup. Do not edit the queries. This message can appear when **Load** is selected before the prefilled values finish initializing.

Power BI may reuse a valid cached credential. To change accounts or environments, use **File -> Options and settings -> Data source settings**.

The lookback parameter limits the server-side query. It does not change retention and cannot restore deleted records.

### Confirm the baseline

On the **Adoption** page, whose report title is **Organization Adoption**, confirm:

- [ ] Total Conversations is non-zero and is plausible for the lookback.
- [ ] Total Users is plausible and is not identical to Total Conversations.
- [ ] The weekly trend matches the expected date range.
- [ ] The Agent filter contains the expected Dataverse agent.
- [ ] The **Glossary** page's load-diagnostics entry shows no blocking parser error.
- [ ] No orange **Apply changes** banner remains after loading finishes.

Stop here if the baseline fails. Optional files will not repair transcript permissions, unsupported environments, expired records, or the wrong Environment URL.

### Add data for the report areas you need

Run the guided setup again, reuse the saved Environment URL, and select only the enhancement you are ready to validate. The setup checks each selected file before opening a new report.

### Agent registry

The registry is optional for the basic Dataverse report. Add it when:

- a technical Dataverse name should display as a stable friendly name;
- Copilot Credits uses a different agent identifier; or
- Product Feedback must map an `M365Title` (`T_...`) identifier.

Follow [Agent registry and reporting scope](./AGENT-REGISTRY.md), then select the reviewed registry CSV or JSON under **Agent registry**.

### Organization data

1. In the [Microsoft 365 admin center](https://admin.microsoft.com), select **Users -> Active users -> Export users**, or obtain an approved roster from HR, Viva Insights, or Microsoft Graph.
2. Confirm the file contains `UserPrincipalName`, `UPN`, or `PersonId`.
3. Select the file under **Organization data** in guided setup.
4. Refresh and confirm organization labels appear.

Department, Country, JobTitle, and DisplayName are optional; missing fields produce a warning and remain blank.

Organization data is available for Desktop/manual refresh. It is excluded from the gateway-free cloud refresh option.

### Copilot Credits

1. In the [Power Platform admin center](https://admin.powerplatform.microsoft.com), select **Licensing -> Copilot Studio -> Summary -> Download report**.
2. Set **Usage type** to `Copilot Credits` and choose a 30-day lookback.
3. Download **User-Level Credit Consumption**.
4. Select the file under **Copilot Credits** in guided setup.
5. Review the validation summary and resolve any agent-ID matching warning.

Credits are available for Desktop/manual refresh. Use Fabric when credit ingestion must be automated.

The export has no conversation ID. Total and billable credits are observed; cost per resolved conversation, net value, and ROI are modeled allocations.

### Product Feedback

1. Add the agent's `M365Title` alias to the registry.
2. Save and review the registry.
3. Export Product Feedback from **Health -> Product feedback** in the Microsoft 365 admin center.
4. Run the guided setup and select the registry under **Agent registry**.
5. Select the raw Product Feedback export. Add a Monitor reaction export too when available.
6. The setup filters, deduplicates, validates, and embeds the matching feedback locally.

Do not load the tenant-wide raw export directly. For Product Feedback, blank or unmatched Agent IDs are excluded and are not inferred to be ESS. Monitor reactions use a registry Bot/Agent ID when present; otherwise they are included only when the report can reconcile the exported Conversation ID to one exact loaded conversation.

### Customer-specific topics

1. Follow [Private adaptive topic tuning](./TOPIC-TUNER.md).
2. Review proposed rules and enable only approved rows.
3. Select `customer-topic-overrides.json` under **Approved topic rules**.
4. Refresh and review topic diagnostics.

Native Copilot Studio topics remain authoritative. Uncertain rules remain disabled or unassigned.

## Action 3 - Publish only if needed

If you need only Desktop/manual refresh, save the validated report as a PBIX and stop here.

<details>
<summary><strong>Publish and schedule gateway-free Dataverse refresh</strong></summary>

1. Complete the baseline checklist before publishing.
2. Return to the extracted package and run `BUILD-SERVICE-REFRESH.cmd`. This publication helper reuses the saved URL and approved registry, feedback, and topic selections while excluding local Organization and Credits files.
3. Open the prepared report, wait until every prefilled value is visible and stable, then select **Load**.
4. Sign in if prompted and select **Home -> Refresh**.
5. Save as PBIX, select **Home -> Publish**, and choose a workspace where you have Contributor, Member, or Admin access.
6. Configure OAuth credentials and the schedule by following [AUTO-REFRESH.md](./AUTO-REFRESH.md).

Use Fabric instead when organization or credit files must refresh automatically.

</details>

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Authentication fails | Account lacks transcript-table access or URL is wrong | Confirm Bot Transcript Viewer in the target environment and recopy Instance URL |
| Total Conversations is zero | Unsupported environment, no retained records, or transcript capture disabled | Check environment type, settings, retention, and lookback |
| Refresh is slow | Lookback is wider than needed | Use a smaller retained lookback |
| Agent label is technical | No registry is embedded | Add a reviewed registry and rerun guided setup |
| Organization or credit visuals are blank in Service | These local file sources are intentionally removed | Use Desktop/manual refresh for these files or Fabric for automated enrichment |
| Credit visuals are blank in Desktop | No `Agent Id` matches the selected agent or registry `CreditId` | Check the export and guided validation summary |
| Need to switch environments | Saved choices point to the previous URL | Run the guided setup and decline reuse of saved choices |
| Orange Apply changes banner remains | The report was prepared with an older package | Download the current package and repeat the guided setup |
| Queries are blocked or a cyclic reference appears immediately after Load | Load was selected before the prefilled parameter values finished initializing | Close the report without saving, reopen it from the guided setup, wait for every value to appear and stabilize, then select Load |

## Need help?

- [Return to data-path selection](./README.md#choose-your-data-path)
- [Open a GitHub issue](https://github.com/microsoft/ESS/issues)
- Review the report's **Glossary**, including its load-diagnostics entry
