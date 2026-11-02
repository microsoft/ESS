# Dataverse Direct setup

This is the recommended path for ongoing production reporting from one supported Dataverse environment. Allow about **15-25 minutes** for the first setup.

Dataverse Direct reads the `ConversationTranscript` table through the Dataverse connector. **Do not export a ConversationTranscript CSV for this template.** Transcript CSV exports are supported only by the [CSV Upload path](./SETUP-CSV-Download.md).

## Three customer actions

1. **Prepare access and copy the URL.** Confirm transcript capture and read access, then copy the Dataverse Environment URL.
2. **Choose a setup and validate the report.** URL-only users can download the Service-ready PBIT and skip Python. The existing guided setup remains available for optional enhancements.
3. **Publish the Service-safe report.** Publish the direct PBIT after validation, or use the guided publication helper when optional inputs were embedded.

## Files, portals, and required roles

### Required template input

| Need | Data or input | Portal and retrieval steps | Required role | Included helper | Expected file or output |
|---|---|---|---|---|---|
| Live conversations | Dataverse Environment URL | [Power Apps](https://make.powerapps.com) -> select environment -> **Settings -> Session details -> Instance url** | Bot Transcript Viewer, or custom role with organization-level Read on `conversationtranscript`; Environment Maker alone is insufficient | [Service-ready PBIT or guided setup](#action-2---choose-a-setup-and-validate-the-report) | URL such as `https://org.crm.dynamics.com` |

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

If temporary **System Administrator** access was used for setup, an appropriately authorized Dataverse administrator should remove that role after validation and retain only the approved least-privilege reporting role. Do not renew elevation or grant broader privileges solely to bypass cleanup.

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

## Action 2 - Choose a setup and validate the report

### Option A - URL only, no Python or script

Use this path when Dataverse conversations and the built-in topic taxonomy are sufficient.

1. [Download the Service-ready Dataverse PBIT](./ESS%20Dashboard%20-%20Dynamic%20Topics%20%28Dataverse%29%20V21%20-%20Power%20BI%20Service%20-%20PUBLISH%20THIS.pbit).
2. Open it in Power BI Desktop.
3. Paste the Dataverse Environment URL into **Dataverse Environment URL (required)**.
4. Leave the optional parameters blank, wait until the values stop changing, and select **Load**.

This template already excludes local Organization and Credits sources and is ready for Power BI Service publication after the baseline checks pass. No Python installation or repository script is required.

For optional inputs, Customer Topic Overrides JSON can be pasted directly. Feedback Events JSON is limited to prepared Monitor events whose Conversation ID matches one exact loaded conversation. Use Option B for Microsoft 365 Product Feedback or any input that requires an agent registry.

### Option B - Guided setup with optional enhancements

This option uses the same Service-ready Dataverse PBIT as Option A. The guided Python workflow creates a local **Desktop Validation - DO NOT PUBLISH** report with the selected enhancements and prepares the separate Service publication report; it does not require a second Dataverse source template.

1. [Download the complete ESS ZIP](https://github.com/microsoft/ESS/archive/refs/heads/main.zip).
2. Select **Extract All** and keep the extracted folder structure intact.
3. Install [Power BI Desktop](https://powerbi.microsoft.com/desktop/).
4. Install [Python 3.10 or later](https://www.python.org/downloads/windows/) and make sure the Python launcher is available on `PATH`.
5. Open the extracted `ESS-main` folder and double-click `START-HERE-DATAVERSE.cmd`. This creates the local **Desktop Validation - DO NOT PUBLISH** report and preserves the current guided workflow.
6. Paste the Environment URL and skip optional data for the first run.
7. When the guided checks complete, open the report.

The direct Service-ready PBIT prompts for:

| Parameter | Baseline value |
|---|---|
| **Dataverse Environment URL (required)** | Paste the URL copied in Action 1; it is initially blank |
| **Transcript Lookback Days** | Leave blank for the 90-day default, or enter a smaller retained window |
| **Customer Topic Overrides JSON (optional)** | Blank |
| **Feedback Events JSON (optional)** | Blank |

The guided Desktop-validation report prompts for the same four parameters plus **Org Data File** and **Agent Credits (optional)**. The Environment URL and selected optional inputs are prefilled from the guided setup.

1. Wait until every parameter value is visible and has stopped changing. Power BI fills prefilled guided values asynchronously.
2. Only then select **Load**.
3. When prompted for Dataverse credentials, select **Organizational account**.
4. Select **Sign in**, complete authentication, and select **Connect**.

> [!IMPORTANT]
> If Power BI reports that queries are blocked or that a cyclic reference was encountered, close that report without saving and reopen the report from the guided setup. Do not edit the queries. This message can appear when **Load** is selected before the prefilled values finish initializing.

Power BI may reuse a valid cached credential. To change accounts or environments, use **File -> Options and settings -> Data source settings**.

The lookback parameter limits the server-side query. It does not change retention and cannot restore deleted records.

> [!IMPORTANT]
> The direct Service-ready PBIT from Option A can be published after validation. The report created by `START-HERE-DATAVERSE.cmd` in Option B is for Desktop validation and may contain local Organization and Credits paths, so use its separate publication report from Action 3.

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
3. Download **User-Level Credit Consumption**, the MAC consumption export.
4. Select the file under **Copilot Credits** in guided setup.
5. Review the validation summary and resolve any agent-ID matching warning.

Fabric is not required to use credit data. The guided workflow validates and loads the MAC consumption export locally for Desktop/manual refresh. Fabric is an optional architecture only when the export must be ingested and refreshed automatically in the cloud.

The export has no conversation ID. Total and billable credits are observed; cost per resolved conversation, net value, and ROI are modeled allocations.

### Business Impact financial controls

On the **Business Impact** page, review the **Hourly rate**, **Minutes per ticket**, and **Price per credit** controls before using modeled financial results. These customer-supplied assumptions affect the report's time-savings value, credit cost, net value, and ROI; they do not change observed conversation or credit-consumption totals.

### Product Feedback

1. Add the agent's `M365Title` alias to the registry.
2. Save and review the registry.
3. Export Product Feedback from **Health -> Product feedback** in the Microsoft 365 admin center.
4. Run the guided setup and select the registry under **Agent registry**.
5. Select the raw Product Feedback export. Add a Monitor reaction export too when available.
6. The setup filters, deduplicates, validates, and embeds the matching feedback locally.

Do not load the tenant-wide raw export directly. For Product Feedback, blank or unmatched Agent IDs are excluded and are not inferred to be ESS. Monitor reactions use a registry Bot/Agent ID when present; otherwise they are included only when the report can reconcile the exported Conversation ID to one exact loaded conversation.

### Customer-specific topics

1. Follow [Customer-specific topic tuning](./TOPIC-TUNER.md).
2. Double-click `TUNE-TOPICS.cmd` and select the representative transcript export.
3. Follow the tool's **READY**, **REVIEW REQUIRED**, or **STOP** guidance.
4. Validate the generated **Desktop Validation - Topics - DO NOT PUBLISH** report.

Native Copilot Studio topics remain authoritative. Uncertain rules remain disabled or unassigned.

## Action 3 - Publish the Service report

If you need only Desktop/manual refresh, save the validated report as a PBIX and stop here.

1. Complete the baseline checklist before publishing.
2. Continue with the Service-ready PBIT from Option A. If you used the guided Option B, return to the extracted package and run `BUILD-SERVICE-REFRESH.cmd`. The existing helper supplies the saved URL through the report's Dataverse parameter and embeds approved registry, feedback, and topic selections while excluding local Organization and Credits files. It does not hard-code the URL into the query.
3. Confirm the filename ends with **Power BI Service - PUBLISH THIS.pbit**. Do not publish a **Desktop Validation - DO NOT PUBLISH** report.
4. Open the prepared report, wait until every prefilled value is visible and stable, then select **Load**.
5. Sign in if prompted and select **Home -> Refresh**.
6. Save it as a clearly named PBIX, select **Home -> Publish**, and choose a workspace where you have Contributor, Member, or Admin access. Do not overwrite or publish the Desktop Validation PBIX.
7. In Power BI Service, open the published semantic model and select **Settings -> Data source credentials -> Edit credentials**.
8. Select **OAuth2** as the authentication method and **Organizational** as the privacy level, then sign in with an account that can read `conversationtranscript`.
9. Select **Refresh now** and confirm **Refresh history** shows **Completed**.
10. Only after that successful manual Service refresh, enable **Scheduled refresh**, choose the cadence, and select **Apply**. See [AUTO-REFRESH.md](./AUTO-REFRESH.md) for the complete scheduling guide.

Organization and MAC credit exports remain available through Desktop/manual refresh. Fabric is an optional automation path when those files must be ingested and refreshed in the cloud; it is not required to use either export locally.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Authentication fails | Account lacks transcript-table access or URL is wrong | Confirm Bot Transcript Viewer in the target environment and recopy Instance URL |
| Total Conversations is zero | Unsupported environment, no retained records, or transcript capture disabled | Check environment type, settings, retention, and lookback |
| Refresh is slow | Lookback is wider than needed | Use a smaller retained lookback |
| Agent label is technical | No registry is embedded | Add a reviewed registry and rerun guided setup |
| Organization or credit visuals are blank in Service | These local file sources are intentionally removed | Use Desktop/manual refresh for these files; Fabric is optional for automated cloud enrichment |
| Credit visuals are blank in Desktop | No `Agent Id` matches the selected agent or registry `CreditId` | Check the export and guided validation summary |
| Need to switch environments | The report parameter and credentials point to the previous environment | In the direct Service-ready report, update the Environment URL parameter. For guided enhancements, rerun the guided setup with the new URL. Update Dataverse credentials after publishing. |
| Orange Apply changes banner remains | The report was prepared with an older package | Download the current Service-ready PBIT or repeat the guided setup with the current package |
| Queries are blocked or a cyclic reference appears immediately after Load | Load was selected before the prefilled parameter values finished initializing | Close the report without saving, reopen it from the guided setup, wait for every value to appear and stabilize, then select Load |

## Need help?

- [Return to data-path selection](./README.md#choose-your-data-path)
- [Open a GitHub issue](https://github.com/microsoft/ESS/issues)
- Review the report's **Glossary**, including its load-diagnostics entry
