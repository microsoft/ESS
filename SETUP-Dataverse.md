# Step-by-Step Setup Guide — Dataverse Direct

Get the **ESS Insights dashboard** running on your own Copilot Studio agent data, connected directly to Dataverse. Allow about **15–25 minutes** for the first setup.

> **Choose this path for:** ongoing production reporting from one supported Dataverse environment. Use the Desktop-validation build to prove every available source, then publish the separate Service-refresh build. For automated Org Data and Credits enrichment, use Fabric. For a one-time snapshot, use [CSV Upload](SETUP-CSV-Download.md). [Compare all data paths](README.md#choose-your-data-path).

> ⚠️ Extend Dataverse transcript retention to the history period you need; the report lookback parameter cannot restore records that Dataverse has deleted.

---

## Before you start

✅ The [complete ESS package](https://github.com/microsoft/ESS/archive/refs/heads/main.zip) downloaded, extracted, and kept in its original folder structure; do not download the launcher files separately
✅ **Power BI Desktop** installed — [download free](https://powerbi.microsoft.com/desktop/)
✅ **Python 3.10 or later** installed — [download for Windows](https://www.python.org/downloads/windows/); the guided launcher runs it for you, so no coding or package installation is required
✅ Signed in with an account in the **same Microsoft 365 tenant** as the ESS agent
✅ **Bot Transcript Viewer** security role on the Dataverse environment that hosts your ESS agent — an admin must grant this. [Microsoft's how-to](https://learn.microsoft.com/en-us/microsoft-copilot-studio/admin-share-bots#assign-the-bot-transcript-viewer-security-role-during-agent-sharing)
✅ The **Environment URL** of the Dataverse env that hosts your ESS agent (Step 1 below)
✅ A folder for the optional Org Data / Feedback / Credits CSVs (e.g. `Documents/AgentData`)

> ⚠️ **Environment Maker is NOT enough.** Without the Bot Transcript Viewer role, the connector signs in successfully but returns zero `conversationtranscript` rows.

> 📋 See the landing page's single [required and optional data-access table](README.md#get-your-data-and-confirm-access). This guide repeats each role only where you use it.

### Plain-language terms

| Term | What it means |
|---|---|
| **Dataverse** | The Microsoft cloud data store where Copilot Studio keeps conversation transcripts. You do not need to query it manually. |
| **Environment URL** | The web address identifying the Power Platform environment that contains your agent. |
| **Organization data** | An optional CSV that adds Department, Country, Job Title, or display names to transcript users. |
| **Credit consumption** | An optional CSV downloaded from Power Platform admin center showing Copilot credit use by user and agent. |
| **PBIT** | A Power BI template. The setup launcher creates the correct template for your environment. |
| **Desktop-validation template** | The first template to open. It tests live Dataverse plus any optional local files. |
| **Service-refresh template** | The second template. Publish this version because it contains only the cloud Dataverse connection. |

---

## Step 1 — Find your Dataverse Environment URL ✅ Required

**Outcome:** a URL like `https://orgabc12345.crm.dynamics.com` that points at the environment hosting your agent.

1. Sign in to [Copilot Studio](https://copilotstudio.microsoft.com/) with the account that can open the ESS agent.
2. Open the ESS agent and note the selected environment. If the agent is missing, first confirm the account and tenant; do not assume the last-opened environment is correct.
3. Sign in to [Power Apps](https://make.powerapps.com/) with the same account.
4. Use the **environment selector** (top-right) to find the environment from the previous step. Search inside this selector, not the global Power Apps search.
5. Click the **⚙️ gear icon** (top-right) → **Session details**.
6. In the dialog, find **Instance url** (also shown as "Org URL").
7. Copy the value — it looks like:
   - `https://orgabc12345.crm.dynamics.com` (North America)
   - `https://orgabc12345.crm4.dynamics.com` (Europe)
   - `https://orgabc12345.crm6.dynamics.com` (Australia)

> 💡 **Drop the trailing slash.** Use `https://orgabc12345.crm.dynamics.com`, not `…/`. Power BI's Dataverse connector is picky.

> ⚠️ **Multiple environments?** This template targets **one environment** at a time. If your agents live in two or three envs, build a copy of the `.pbit` per environment.

---

## Step 2 — (Desktop/manual refresh only) Export your Org Data

**Outcome:** a CSV that maps each user's UPN to the organization attributes actually available. This optional file works in Desktop-validation mode, but is disabled in the Service-refresh build because local file/web branches make the semantic model dynamic.

| Column | Example | Required? |
|---|---|---|
| `UserPrincipalName` | `jane.doe@contoso.com` | ✅ Yes |
| `Department` | `Finance` | ⭐ Recommended |
| `Country` | `USA` | ⭐ Recommended |
| `JobTitle` | `Senior Analyst` | Optional |
| `DisplayName` | `Jane Doe` | Optional |

**Where to get it** (pick one):

- 🅰️ **From HR, Viva Insights, or Microsoft Graph** — preferred when Department, Country, and JobTitle are required.
- 🅱️ **From the [Microsoft 365 admin center](https://admin.microsoft.com)** — sign in with **Global Reader**, **User Administrator**, or **Global Administrator**, select **Users → Active users → Export users**, then confirm the downloaded header before continuing. The default export can contain only basic identity fields and may omit Department, Country, and JobTitle.
- 🅲 **Skip for now** — the template loads cleanly without it.

`UserPrincipalName`, `UPN`, or `PersonId` is required when the file is supplied. Missing Department, Country, JobTitle, or DisplayName is reported as a warning and renders as blank; it does not invalidate the transcript data.

---

## Step 3 — (Desktop/manual refresh or Fabric only) Download Copilot Credits reports

1. Sign in to the [Power Platform admin center](https://admin.powerplatform.microsoft.com) as a tenant administrator, Power Platform Administrator, or Dynamics 365 Administrator. **Power Platform Administrator** is the recommended least-privilege role.
2. Go to **Licensing → Copilot Studio → Summary → Download report**.
3. Set **Usage type** to `Copilot Credits`; choose a `30`, `60`, `90`, or `180` day lookback.
4. For Dataverse V21 Desktop/manual refresh, download **User-Level Credit Consumption** with a **30-day** lookback. Fabric V2 additionally uses the Environment and Agent reports.

At 30 days the generated names are `EntitlementConsumptionTenantDetailsReport_MCSMessages_30.csv`, `EntitlementConsumptionTenantPerAgentDetailsReport_MCSMessages_30.csv`, and `EntitlementConsumptionTenantPerUserDetailsReport_MCSMessages_30.csv`. The environment export is daily by `Usage Date`; agent and user exports are aggregate snapshots without an activity date. Credit values are decimals, agent IDs are bare GUIDs, and blank `User Email` values are unmatched identities—not rows to discard.

> Dataverse V21 matches credits to ESS by `Agent Id` and joins organization data through `User Email`. The Service-refresh build disables this file source; use Fabric when credits must refresh automatically.

### Optional — Include Microsoft 365 Copilot feedback

Microsoft 365 Copilot Chat reactions are not stored in Dataverse transcripts. To include them:

1. For advanced Microsoft 365 feedback attribution, complete the [agent registry guide](AGENT-REGISTRY.md), including the agent's `M365Title` (`T_...`) alias.
2. In the [Microsoft 365 admin center](https://admin.microsoft.com), select **Health → Product feedback → Export to CSV**. The file is tenant-wide, even if the page is filtered.
3. Follow [Microsoft 365 Copilot feedback: export, prepare, and load](FEEDBACK-INGESTION.md) to filter the export locally and create `feedback-events.json`.
4. Review `feedback-events.audit.json`; do not continue if the expected ESS row is missing.
5. In Step 4 below, answer **Yes** when asked about optional files and select `feedback-events.json` under **Prepared Microsoft 365 feedback**.

Do not load the raw Microsoft 365 export directly or infer ESS from `App = M365 Chat`. Only a registry-matched Agent ID is included.

---

## Step 4 — Create the validated Desktop template

**Run this first.** It creates the Power BI template used to confirm that your Dataverse access works. No command line is required.

1. If needed, [download the complete ESS package](https://github.com/microsoft/ESS/archive/refs/heads/main.zip), select **Extract All**, and open the extracted `ESS-main` folder in File Explorer.
2. Double-click **`START-HERE-DATAVERSE.cmd`**.
3. If Windows displays a protection message, select **More info → Run anyway** only when the file came from the official `microsoft/ESS` download.
4. Paste the Environment URL from Step 1.
5. For the simplest first test, answer **No** when asked about optional files.
6. If you already have optional files, answer **Yes** and use the file-picker windows. You may skip any file you do not have.
7. The launcher checks the URL and every selected file before it creates a template.
8. When it reports success, select **Yes** to open the generated Desktop-validation template.

The result is saved under:

```text
Generated Templates\ESS Dashboard - Dynamic Topics (Dataverse) V21 - Desktop Validation.pbit
```

Warnings are informational. For example, missing Country or Job Title means those report fields will be blank. A credits file with no matching agent is valid, but the selected agent's credit visuals will be blank.

---

## Step 5 — Provide the parameters

| Parameter | Desktop-validation build | Service-refresh build |
|---|---|---|
| **Dataverse Environment URL** | Prefilled and editable | Prefilled for display; connector is fixed to the build-time URL |
| **Transcript Lookback Days** | Optional; blank defaults to 90 | Optional; blank defaults to 90 |
| **Org Data File** | Prefilled when selected in the launcher | Removed |
| **Agent Credits  (optional)** | Prefilled when selected in the launcher | Removed |
| **Customer Topic Overrides JSON (optional)** | Embedded when selected in the launcher | Embedded when supplied |
| **Feedback Events JSON (optional)** | Embedded when selected in the launcher | Embedded when supplied |

Click **Load**.

The launcher validates selected JSON files and embeds their **contents**. `Agent Registry JSON` is intentionally hidden from the normal parameter dialog.

### Minimum successful first run

For the smallest working configuration, run `START-HERE-DATAVERSE.cmd`, paste only the Environment URL, and answer **No** when asked about optional files.

Sign in to Dataverse and confirm **Total Conversations** is non-zero before adding optional sources. This isolates access and retention problems from enrichment problems.

> 💡 **Lookback Days** controls how far back the connector pulls transcripts. The filter runs **server-side** on Dataverse, so a smaller window = faster refresh. Default is 90 days.

> ⚠️ **Lookback is not retention.** Entering `90`, `180`, or `365` does not recover transcripts already removed by the Dataverse retention job. Confirm and extend retention before the required history ages out.

> 💡 **Agent filter.** V21 loads the transcript agents found in the environment. Open **All filters** on any analytical page and choose an Agent; the selection is synchronized across pages. Embed a registry when the technical Bot name must display as a stable friendly label or when feedback/credit aliases must be validated.

---

## Step 6 — Sign in to Dataverse

After Load, Power BI prompts for credentials on the Dataverse data source:

1. Select **Organizational account**
2. Click **Sign in** and complete OAuth (MFA, Conditional Access, etc.)
3. Click **Connect**

> 💡 **One-time per environment.** Power BI caches the credential under *File → Options → Data source settings*. To switch environments, clear the entry there and re-auth.

> 💡 **No sign-in page?** Power BI may already have a valid Organizational account credential cached for this Dataverse environment. Continue if the report loads successfully.

> ⚠️ **"We couldn't authenticate with the credentials provided."** Confirm you signed in with an account that has the **Bot Transcript Viewer** role in this environment. Tenant admin ≠ environment role.

> 💡 **Topic classification.** Native Copilot Studio topics are preserved. Rows without a native topic use the shared customer-neutral English, Spanish, and Chinese taxonomy in `taxonomy/topics-taxonomy.csv`. Complete-word matching, scoring, exclusions, and ambiguity handling prevent partial-word collisions and leave low-signal prompts as **Other / Uncategorized**.

> Need customer-specific topics? Run the [Private adaptive topic tuner](TOPIC-TUNER.md). It learns high-precision rules from the customer's native topic evidence and leaves weak or unlabeled discoveries disabled for local review. Run the guided setup again and select the approved JSON under **Approved topic rules**; no template-code change or second data source is required.

> Microsoft 365 Copilot Chat reactions aren't stored in Dataverse transcripts. Follow [Cross-channel feedback ingestion](FEEDBACK-INGESTION.md) to normalize Product Feedback or Monitor exports, then select the resulting JSON under **Prepared Microsoft 365 feedback** in the guided setup. Embedded JSON avoids Formula Firewall and gateway dependencies.

> Parent/child attribution requires **Include node-level details in transcripts**. When connected-agent traces are present, the Improvement Opportunities Fix-It Queue shows every participating child and its completion state. See [Parent and child agent attribution](CHILD-AGENT-ATTRIBUTION.md).

### Validate optional files with fabricated data

Use `SampleData/OrgData.csv`, `SampleData/agent-registry.json`, and `SampleData/EntitlementConsumptionTenantPerUserDetailsReport_MCSMessages_30_SYNTHETIC.csv` only as a contract test. Their synthetic agent/user IDs do not match a live customer Dataverse environment, so they cannot prove live joins. To validate the entire report without tenant access, use CSV V18 with all matching synthetic files described in the CSV guide.

---

## Step 7 — Validate before sharing

First check the launcher's setup results:

- [ ] Org Data has a recognized UPN column; missing optional attributes are understood
- [ ] Credits uses the supported User-Level schema
- [ ] `matchedRegistryCreditIds` is non-empty before claiming registered-agent credit validation; an empty list means the current export cannot validate that agent
- [ ] Topic overrides and feedback show the expected rule/event counts

Then go to the **Organization Adoption** page and check:

- [ ] **Total Conversations** is non-zero and roughly matches Copilot Studio's own analytics for the same window
- [ ] **Total Users** is plausible — not `1`, not equal to Total Conversations
- [ ] **Conversations & Users by Week** matches your Lookback Days
- [ ] If a registry was embedded: the Agent filter shows the approved friendly label
- [ ] If Org Data includes Department: **Users by Organization** shows real labels
- [ ] Country and Job Title are populated only when those source columns exist
- [ ] If credits matched a registry `CreditId`: observed totals reconcile to the User-Level export; do not interpret them as per-conversation observed cost
- [ ] Native Copilot Studio topics remain unchanged; enabled customer rules apply only to unresolved rows; ambiguous rows remain uncategorized
- [ ] The orange **Apply changes** banner is not present after loading finishes

Then check the **Metric Glossary** page (📖) — it defines the metrics used across the report.

---

## Step 8 — Publish to Power BI Service (only when ready)

### Create the publishable Service template

**Run the second launcher only if you are publishing the report for cloud refresh.** After the Desktop checklist in Step 7 passes:

1. Return to the extracted `ESS-main` folder.
2. Double-click **`BUILD-SERVICE-REFRESH.cmd`**.
3. The launcher reuses the saved Environment URL and approved JSON choices.
4. Select **Yes** to open the generated Service-refresh template.
5. Select **Load**, sign in if prompted, and run **Home → Refresh**.

The result is saved under:

```text
Generated Templates\ESS Dashboard - Dynamic Topics (Dataverse) V21 - Service Refresh.pbit
```

The Service template intentionally excludes local Organization and Credits CSV files. This is what allows Power BI Service to refresh Dataverse without an on-premises gateway.

| Goal | How |
|---|---|
| **Refresh with latest transcripts** | **Home → Refresh** — pulls live from Dataverse |
| **Save the working report** | **File → Save As** and save a `.pbix` copy after the first successful load |
| **Publish to Power BI Service** | Open and validate the **Service Refresh** artifact, save it as PBIX, then **Home → Publish**. Do not publish the Desktop-validation artifact as the scheduled-refresh model. |
| **Schedule refresh** | Service: dataset → **Settings → Scheduled refresh**. Bind Dataverse credentials (OAuth2 / Organizational) first. Step‑by‑step: **[AUTO-REFRESH.md](./AUTO-REFRESH.md)** |
| **Export to PDF** | **File → Export → Export to PDF** |
| **Switch environments** | Run `START-HERE-DATAVERSE.cmd` again, answer **No** when asked to reuse saved choices, and enter the new URL |

> 💡 **No Gateway** is the headline benefit. Cloud Power BI Service talks directly to cloud Dataverse — schedule hourly if you want.

---

## Quick reference card

| Step | What | Where | Time |
|---|---|---|---|
| 1 | Copy Environment URL | Power Apps → ⚙️ → Session details | 1 min |
| 2 | Export HR roster (optional; Desktop/manual refresh only) | M365 Admin Center | 2 min |
| 3 | Download User-Level Credit Consumption CSV (optional; Desktop/manual refresh or Fabric only) | [Power Platform admin center](https://admin.powerplatform.microsoft.com) → Licensing → Copilot Studio → Summary → Download report | 2 min |
| 4 | Export and prepare Microsoft 365 Product Feedback (optional) | Microsoft 365 admin center → Health → Product feedback | 5–10 min |
| 5 | Double-click `START-HERE-DATAVERSE.cmd`, then load and refresh the Desktop template | Guided launcher and Power BI Desktop | 3–10 min |
| 6 | Check source warnings, joins, labels, and topic behavior | Setup results and report pages | 3–5 min |
| 7 | If publishing for cloud refresh, double-click `BUILD-SERVICE-REFRESH.cmd` | Guided launcher | 1–2 min |
| 8 | Refresh, save as PBIX, publish, and schedule | Power BI Desktop and Service | 3–5 min |

---

## Common issues & fixes

| Symptom | Cause | Fix |
|---|---|---|
| `We couldn't authenticate with the credentials provided` | Account lacks Bot Transcript Viewer, or wrong env URL | Confirm role in Power Platform Admin Center → environment → Settings → Users + permissions → Security roles |
| `The remote name could not be resolved` / `Invalid URL` | Trailing slash or typo | Re-copy from Power Apps → ⚙️ → Session details |
| Refresh succeeds but **Total Conversations = 0** | Teams/Developer/M365 Copilot env (transcripts not written), or empty lookback | Move agent to a standard production/sandbox Dataverse env; widen Lookback Days |
| Users or conversations disappear between weekly exports | Older transcripts aged out of Dataverse, or exports used different windows | Confirm the configured retention period and compare the same retained date range; extend retention prospectively |
| Refresh is very slow (5+ min) | Lookback too wide | Lower Lookback Days |
| `Users by Organization` all `(Blank)` | Service-refresh intentionally omits Org Data, the source lacks Department, or UPNs do not match | Check the launcher's setup results and source header; use Desktop validation or Fabric enrichment |
| `Access to the resource is forbidden` | Account lacks Dataverse read access | Grant **Bot Transcript Viewer** in the target environment; Power Platform Administrator or Environment Maker alone is insufficient |
| Observed Credit Leaderboard is blank | Service-refresh omits the file, or the export has no `Agent Id` matching the registry `CreditId` | Check `matchedRegistryCreditIds`; use Desktop validation for the file or Fabric credit ingestion |
| Microsoft 365 feedback is missing | Raw tenant export was not normalized, Agent ID is blank, or the `M365Title` registry alias does not match | Follow the feedback guide, review `feedback-events.audit.json`, then run the first launcher again and select the validated registry and prepared feedback files |
| Total Users too low | Same employee as both UPN and Entra Object ID | Already handled by the model |
| Repeat-usage rate is 0% | Lookback too short | Widen to 60 or 90 days |
| Need to switch environment | The Service-refresh connector is fixed to the setup-time URL | Run `START-HERE-DATAVERSE.cmd` again, enter the new URL, validate Desktop, then rebuild the Service template |
| Orange **Apply changes** banner remains after the initial load | The PBIT was built with an older setup tool that retained stale pending-query metadata | Close without saving, download the latest ESS package, run the guided launchers again, and open the newly generated file; do not repeatedly click the banner |

---

## CSV Upload vs Dataverse Direct — which should I use?

| | CSV Upload | Dataverse Direct *(this guide)* |
|---|---|---|
| Setup time | ~10 min | ~5 min |
| Refresh | Re-export CSV, drop at path, click Refresh | One click — Refresh pulls live |
| Service refresh | No gateway when hosted on SharePoint/OneDrive; local paths need a gateway | **No Gateway** — cloud-to-cloud |
| Tenant access | Anyone who can run the export | Bot Transcript Viewer on the env |
| Lookback control | Whatever the export and retention window still contain | Parameter queries available Dataverse rows; it does not override retention |
| Best for | One-off snapshots, demos, sharing outside tenant | Production dashboards, scheduled refresh |

---

## Need more help?

- 🐛 [Open an issue](https://github.com/microsoft/ESS/issues)
- 🩺 Check the **Load Diagnostics** page for row counts and parser warnings
- 📖 The **Metric Glossary** page has every measure's definition
