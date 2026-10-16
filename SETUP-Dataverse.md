# Dataverse Direct setup

This is the recommended path for ongoing production reporting from one supported Dataverse environment. Allow about **15-25 minutes** for the first setup.

The first launcher creates a Desktop-validation template. After that report works, the second launcher creates a cloud-only Service-refresh template for publication.

## Your first successful report

Complete only the baseline steps first:

1. Confirm the transcript role and copy the Dataverse Environment URL.
2. Download and extract the complete ESS package.
3. Run `START-HERE-DATAVERSE.cmd`.
4. Enter only the Environment URL and skip optional files.
5. Sign in to Dataverse and confirm Total Conversations is non-zero.
6. Add optional inputs one at a time.
7. Run `BUILD-SERVICE-REFRESH.cmd` only after Desktop validation passes.

## Files, portals, and required roles

### Required for the first run

| Need | Data or input | Portal and retrieval steps | Required role | Expected file or output | Included helper |
|---|---|---|---|---|---|
| Transcript capture | Future conversations with node details | [Copilot Studio](https://copilotstudio.microsoft.com) -> open agent -> **Settings -> Advanced -> Conversation transcripts** | Agent owner or coauthor with edit access | Both transcript settings on; agent saved and published | None |
| Live conversations | Dataverse Environment URL | [Power Apps](https://make.powerapps.com) -> select environment -> **Settings -> Session details -> Instance url** | Bot Transcript Viewer, or custom role with organization-level Read on `conversationtranscript`; Environment Maker alone is insufficient | URL such as `https://org.crm.dynamics.com` | [`START-HERE-DATAVERSE.cmd`](./START-HERE-DATAVERSE.cmd) |
| Desktop validation | Environment-specific Desktop template | Run the first launcher from the extracted package | Python 3.10+ locally; no extra cloud role | `Generated Templates\...\Desktop Validation.pbit` | [Dataverse V21](./ESS%20Dashboard%20-%20Dynamic%20Topics%20%28Dataverse%29%20V21.pbit) plus [`START-HERE-DATAVERSE.cmd`](./START-HERE-DATAVERSE.cmd) |
| Service publication | Cloud-only Service template | Run the second launcher after Desktop validation | Same Dataverse transcript role; Power BI workspace Contributor+ to publish | `Generated Templates\...\Service Refresh.pbit` | [`BUILD-SERVICE-REFRESH.cmd`](./BUILD-SERVICE-REFRESH.cmd) |

### Optional after the first successful refresh

| Need | Data or input | Portal and retrieval steps | Required role | Expected file or output | Included helper |
|---|---|---|---|---|---|
| Friendly names or cross-source aliases | Agent registry | Follow the [agent registry guide](./AGENT-REGISTRY.md) | Access to the environment or transcript identifiers | Validated `agent-registry.json` | [`tools\agent_registry.py`](./tools/agent_registry.py) |
| Organization | User roster | [Microsoft 365 admin center](https://admin.microsoft.com) -> **Users -> Active users -> Export users**, or approved HR/Viva Insights/Graph source | Global Reader, User Administrator, or Global Administrator for Microsoft 365 export | `OrgData.csv` | Desktop-validation build only |
| Copilot Credits | User-Level Credit Consumption | [Power Platform admin center](https://admin.powerplatform.microsoft.com) -> **Licensing -> Copilot Studio -> Summary -> Download report** | Power Platform Administrator recommended; tenant administrator or Dynamics 365 Administrator also works | `EntitlementConsumptionTenantPerUserDetailsReport_MCSMessages_30.csv` | Desktop-validation build only |
| Cross-channel feedback | Product Feedback export | [Microsoft 365 admin center](https://admin.microsoft.com) -> **Health -> Product feedback -> Export to CSV** | Microsoft 365 administrator or reader with Product Feedback access | Prepared `feedback-events.json` plus audit file | [`tools\ess_feedback_normalizer.py`](./tools/ess_feedback_normalizer.py) ([guide](./FEEDBACK-INGESTION.md)) |
| Customer topics | Native-topic learning evidence | Run the local tuner after the baseline works | Transcript read access; no extra cloud role | Reviewed `customer-topic-overrides.json` | [`tools\ess_topic_tuner.py`](./tools/ess_topic_tuner.py) ([guide](./TOPIC-TUNER.md)) |

## Step 1 - Confirm access and transcript capture

Ask a Power Platform administrator to grant the report account one of:

- **Bot Transcript Viewer** in the environment that hosts the agent; or
- a customer-approved custom role with organization-level **Read** on `conversationtranscript`.

Tenant administrator, Power Platform Administrator, and Environment Maker do not automatically grant transcript-table access.

Then open the agent in [Copilot Studio](https://copilotstudio.microsoft.com) and confirm:

1. **Settings -> Advanced -> Conversation transcripts -> Save conversation transcripts to Dataverse** is on.
2. **Include node-level details in transcripts** is on.
3. The agent is saved and published.
4. Several new test conversations exist.

Use a Production, Sandbox, or Default environment. Microsoft Teams and Microsoft 365 Copilot environments do not persist the required records; Developer environments contain only the maker's conversations.

## Step 2 - Copy the Environment URL

1. Sign in to [Copilot Studio](https://copilotstudio.microsoft.com) and note the environment that contains the ESS agent.
2. Sign in to [Power Apps](https://make.powerapps.com) with the same account.
3. Use the environment selector in the upper-right corner to select that environment.
4. Select the **Settings** gear -> **Session details**.
5. Copy **Instance url** or **Org URL**.
6. Remove the trailing slash.

Example:

```text
https://orgabc12345.crm.dynamics.com
```

This solution targets one environment per generated Dataverse template. Use Fabric if one report must combine several environments.

## Step 3 - Prepare the package

1. [Download the complete ESS ZIP](https://github.com/microsoft/ESS/archive/refs/heads/main.zip).
2. Select **Extract All** and keep the extracted folder structure intact.
3. Install [Power BI Desktop](https://powerbi.microsoft.com/desktop/).
4. Install [Python 3.10 or later](https://www.python.org/downloads/windows/) and select **Add Python to PATH**.

No Python packages or command-line knowledge are required. The launcher runs the tested local builder for you.

## Step 4 — Create the validated Desktop template

Run this launcher first:

1. Open the extracted `ESS-main` folder in File Explorer.
2. Double-click `START-HERE-DATAVERSE.cmd`.
3. If Windows displays a protection message, select **More info -> Run anyway** only when the file came from the official `microsoft/ESS` download.
4. Paste the Environment URL.
5. For the first test, answer **No** when asked about optional files.
6. Wait for the validation summary.
7. When the launcher reports success, select **Yes** to open the generated template.

The output is:

```text
Generated Templates\ESS Dashboard - Dynamic Topics (Dataverse) V21 - Desktop Validation.pbit
```

Do not open the base `ESS Dashboard - Dynamic Topics (Dataverse) V21.pbit` directly for customer setup. It is the validated launcher input.

## Step 5 - Load and sign in

The Desktop-validation template prompts for:

| Parameter | Baseline value |
|---|---|
| **Dataverse Environment URL** | Prefilled by the launcher |
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
> If Power BI reports that queries are blocked or that a cyclic reference was encountered, close that report without saving and reopen the generated PBIT. Do not edit the queries. This message can appear when **Load** is selected before the prefilled values finish initializing.

Power BI may reuse a valid cached credential. To change accounts or environments, use **File -> Options and settings -> Data source settings**.

The lookback parameter limits the server-side query. It does not change retention and cannot restore deleted records.

## Step 6 - Confirm the baseline

On the **Adoption** page, whose report title is **Organization Adoption**, confirm:

- [ ] Total Conversations is non-zero and is plausible for the lookback.
- [ ] Total Users is plausible and is not identical to Total Conversations.
- [ ] The weekly trend matches the expected date range.
- [ ] The Agent filter contains the expected Dataverse agent.
- [ ] The **Glossary** page's load-diagnostics entry shows no blocking parser error.
- [ ] No orange **Apply changes** banner remains after loading finishes.

Stop here if the baseline fails. Optional files will not repair transcript permissions, unsupported environments, expired records, or the wrong Environment URL.

## Step 7 - Add optional enhancements

Run `START-HERE-DATAVERSE.cmd` again, choose to reuse the saved Environment URL, answer **Yes** to optional files, and select only the enhancement you are ready to validate. The launcher checks each selected file before creating a new Desktop template.

### Agent registry

The registry is optional for the basic Dataverse report. Add it when:

- a technical Dataverse name should display as a stable friendly name;
- Copilot Credits uses a different agent identifier; or
- Product Feedback must map an `M365Title` (`T_...`) identifier.

Follow [Agent registry and reporting scope](./AGENT-REGISTRY.md), then select the validated `agent-registry.json` under **Agent registry**.

### Organization data

1. In the [Microsoft 365 admin center](https://admin.microsoft.com), select **Users -> Active users -> Export users**, or obtain an approved roster from HR, Viva Insights, or Microsoft Graph.
2. Confirm the file contains `UserPrincipalName`, `UPN`, or `PersonId`.
3. Select the file under **Organization data** in the launcher.
4. Refresh and confirm organization labels appear.

Department, Country, JobTitle, and DisplayName are optional; missing fields produce a warning and remain blank.

Organization data is available in the Desktop-validation build only. The Service-refresh build removes local file inputs so the cloud Dataverse model remains gateway-free.

### Copilot Credits

1. In the [Power Platform admin center](https://admin.powerplatform.microsoft.com), select **Licensing -> Copilot Studio -> Summary -> Download report**.
2. Set **Usage type** to `Copilot Credits` and choose a 30-day lookback.
3. Download **User-Level Credit Consumption**.
4. Select the file under **Copilot Credits** in the launcher.
5. Review the launcher's `matchedRegistryCreditIds` result when a registry is present.

Credits are available in the Desktop-validation build only. Use Fabric when credit ingestion must be automated.

The export has no conversation ID. Total and billable credits are observed; cost per resolved conversation, net value, and ROI are modeled allocations.

### Product Feedback

1. Add the agent's `M365Title` alias to the registry.
2. Rebuild `agent-registry.json` with the included registry validator.
3. Export Product Feedback from **Health -> Product feedback** in the Microsoft 365 admin center.
4. Follow [Cross-channel feedback ingestion](./FEEDBACK-INGESTION.md).
5. Review `feedback-events.audit.json`.
6. Rerun the first launcher and select both the updated JSON under **Agent registry** and `feedback-events.json` under **Prepared Microsoft 365 feedback**.

Do not load the tenant-wide raw export directly. Blank or unmatched Agent IDs are not inferred to be ESS.

### Customer-specific topics

1. Follow [Private adaptive topic tuning](./TOPIC-TUNER.md).
2. Review proposed rules and enable only approved rows.
3. Select `customer-topic-overrides.json` under **Approved topic rules**.
4. Refresh and review topic diagnostics.

Native Copilot Studio topics remain authoritative. Uncertain rules remain disabled or unassigned.

## Step 8 - Create and publish the Service-refresh report

Only continue after the Desktop checklist passes.

1. Return to the extracted `ESS-main` folder.
2. Double-click `BUILD-SERVICE-REFRESH.cmd`.
3. The launcher reuses the saved Environment URL and approved embedded JSON choices.
4. Select **Yes** to open the generated Service-refresh template.
5. Wait until every prefilled parameter value is visible and stable, select **Load**, sign in if prompted, and select **Home -> Refresh**.
6. Save the working result as a `.pbix`.
7. Select **Home -> Publish** and choose a workspace where you have Contributor, Member, or Admin access.

The output is:

```text
Generated Templates\ESS Dashboard - Dynamic Topics (Dataverse) V21 - Service Refresh.pbit
```

Publish the Service-refresh result, not the Desktop-validation result. The Service version excludes local Organization and Credits files, which allows gateway-free Dataverse refresh.

Configure OAuth credentials and scheduled refresh by following [AUTO-REFRESH.md](./AUTO-REFRESH.md).

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Authentication fails | Account lacks transcript-table access or URL is wrong | Confirm Bot Transcript Viewer in the target environment and recopy Instance URL |
| Total Conversations is zero | Unsupported environment, no retained records, or transcript capture disabled | Check environment type, settings, retention, and lookback |
| Refresh is slow | Lookback is wider than needed | Use a smaller retained lookback |
| Agent label is technical | No registry is embedded | Add a validated registry and rerun the launcher |
| Organization or credit visuals are blank in Service | These local file sources are intentionally removed | Use Desktop validation for manual files or Fabric for automated enrichment |
| Credit visuals are blank in Desktop | No `Agent Id` matches the selected agent or registry `CreditId` | Check the export and launcher audit |
| Need to switch environments | Saved choices point to the previous URL | Run the first launcher and decline reuse of saved choices |
| Orange Apply changes banner remains | Template was built with an old setup tool | Download the current package and regenerate both templates |
| Queries are blocked or a cyclic reference appears immediately after Load | Load was selected before the prefilled parameter values finished initializing | Close the report without saving, reopen the generated PBIT, wait for every value to appear and stabilize, then select Load |

## Need help?

- [Return to data-path selection](./README.md#choose-your-data-path)
- [Open a GitHub issue](https://github.com/microsoft/ESS/issues)
- Review the report's **Glossary**, including its load-diagnostics entry
