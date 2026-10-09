# Step-by-Step Setup Guide

Get the **ESS Insights dashboard** running on your own Copilot Studio agent data. Allow about **20–30 minutes** for the first setup; later transcript refreshes are much faster.

---

## Before you start

✅ **Power BI Desktop** installed — [download free](https://powerbi.microsoft.com/desktop/)
✅ **Python 3.10 or later** installed — used by the local registry tool and optional feedback/topic tools; no packages are required
✅ **Bot Transcript Viewer** security role on the Dataverse environment that hosts your ESS agent — an admin must grant this. [Microsoft's how-to](https://learn.microsoft.com/en-us/microsoft-copilot-studio/admin-share-bots#assign-the-bot-transcript-viewer-security-role-during-agent-sharing)
✅ A folder you'll use to store the CSVs (e.g. `Documents/AgentData`)

> ⚠️ **Environment Maker is NOT enough.** Without the Bot Transcript Viewer role, you won't see the ConversationTranscript table in Step 1.

---

## Step 1 — Export your conversation transcripts ✅ Required

**Outcome:** a CSV file containing the last 30 days of agent conversations.

1. **Sign in to Power Apps**
   - Go to [https://make.powerapps.com](https://make.powerapps.com/)
   - Use the environment selector (top-right) to switch to the environment that hosts your **ESS agent**

2. **Open the ConversationTranscript table**
   - In the left sidebar, select **Tables**
   - Click **All** at the top of the table list
   - In the search box, type `conversation`
   - Click the **ConversationTranscript** table to open it

3. **Export the data**
   - In the top menu bar, select **Export** → **Export data**
   - Wait a few minutes for the export to compile (status banner at the top)

4. **Download the file**
   - When the status shows ready, click **Download exported data**
   - A `.zip` archive downloads to your browser's default downloads folder

5. **Unzip and rename**
   - Unzip the archive — inside you'll find a CSV with an auto-generated name like `ConversationTranscript_2026-06-11.csv`
   - Move it to your data folder and rename it to something simple:
     - **Windows:** `C:\Users\<you>\Documents\AgentData\ConversationTranscripts.csv`
     - **Mac:** `/Users/<you>/Documents/AgentData/ConversationTranscripts.csv`

> ⚠️ **Do NOT open this CSV in Excel.** Excel will silently corrupt the JSON in the `Content` column and you'll get an `M Engine error: Token Identifier expected` on load. If you accidentally opened and saved it, re-download from Dataverse — don't try to repair it.

> 💡 **Default window is last 30 days.** Want more? Your admin can change the retention period in the environment settings before you export.

❌ **Transcripts aren't written for these environments:** Dataverse for Teams, Dataverse developer environments, or Microsoft 365 Copilot agents. Confirm your ESS agent runs in a standard Dataverse production/sandbox environment, otherwise the export will be empty.

---

## Step 2 — (Recommended) Export your Org Data ⭐

**Outcome:** a CSV that maps each user's UPN to their Department, Country, and JobTitle. Unlocks "Users by Organization" and "Users by Country" charts on every page.

**Required column** (only one):

| Column | Example | Required? |
|---|---|---|
| `UserPrincipalName` | `jane.doe@contoso.com` | ✅ Yes — must match your agent's UPNs |
| `Department` | `Finance` | ⭐ Recommended — becomes "Organization" |
| `Country` | `USA` | ⭐ Recommended — unlocks Country chart |
| `JobTitle` | `Senior Analyst` | Optional |
| `DisplayName` | `Jane Doe` | Optional |
| `Email` | `jane.doe@contoso.com` | Optional |

**Where to get it** (pick one):

- 🅰️ **From HR** — most HR systems can export a roster CSV with the columns above
- 🅱️ **From the Microsoft 365 Admin Center** — point-and-click, no scripting needed:
  1. Sign in to the [Microsoft 365 Admin Center](https://admin.microsoft.com) with a Global Reader, User Admin, or Global Admin role.
  2. In the left navigation, select **Users → Active users**.
  3. On the **Active users** page, click **Export users** in the top command bar.
  4. In the confirmation dialog, click **Confirm**. A CSV file downloads to your browser's default downloads folder (it may take a minute for large tenants).
  5. Open the downloaded CSV and confirm it includes the columns `User principal name`, `Department`, `Title`, `CountryOrRegion`, `Display name`, and `Email`. (Column names differ slightly from what the template expects — that's fine, the template normalizes them.)
  6. Move/rename the file to your data folder, e.g. `Documents/AgentData/OrgData.csv`.

  > 💡 The export contains every licensed user in your tenant. If your ESS agent is scoped to a subset (e.g. one country or one business unit), you can leave the file as-is — the template only joins rows whose UPN actually appears in your transcripts.
- 🅲 **Skip for now** — the template still loads. You can add Org Data later via *Transform data → Edit Parameters*.

---

## Step 3 — (Optional) Download Copilot Credits reports

**Outcome:** obtains observed Copilot Studio credits for the Business Impact page.

1. Sign in to the [Power Platform admin center](https://admin.powerplatform.microsoft.com) as a tenant administrator, Power Platform Administrator, or Dynamics 365 Administrator. **Power Platform Administrator** is the recommended least-privilege role.
2. Go to **Licensing → Copilot Studio → Summary → Download report**.
3. Set **Usage type** to `Copilot Credits`; choose a `30`, `60`, `90`, or `180` day lookback.
4. For CSV V18, download **User-Level Credit Consumption** with a **30-day** lookback. Fabric V2 additionally uses the Environment and Agent reports.

For a 30-day lookback the generated names are `EntitlementConsumptionTenantDetailsReport_MCSMessages_30.csv`, `EntitlementConsumptionTenantPerAgentDetailsReport_MCSMessages_30.csv`, and `EntitlementConsumptionTenantPerUserDetailsReport_MCSMessages_30.csv`. The environment file has daily `Usage Date` rows; agent and user files are lookback aggregates with no activity date. Credits are decimals, agent IDs are bare GUIDs, and blank `User Email` values must remain visible as unmatched identities.

> CSV V18 matches credits to ESS by `Agent Id` and joins organization data through `User Email`. The Power Platform admin center export has no conversation ID, so cost per resolved conversation, net value, and ROI are labeled modeled allocations.

### Optional — Include Microsoft 365 Copilot feedback

Use this when employees access the Copilot Studio agent from Microsoft 365 Copilot and you want those thumbs-up/down reactions in the report.

1. Complete the [agent registry guide](AGENT-REGISTRY.md), including the agent's `M365Title` (`T_...`) alias.
2. In the [Microsoft 365 admin center](https://admin.microsoft.com), select **Health → Product feedback → Export to CSV**. The download is tenant-wide, even if the page is filtered.
3. Run the local preparation command in [Microsoft 365 Copilot feedback: export, prepare, and load](FEEDBACK-INGESTION.md). It filters the tenant export to approved registry agents and creates `feedback-events.json`.
4. Review `feedback-events.audit.json`; do not continue if the expected ESS row is missing.
5. In Step 5 below, paste the complete contents of `feedback-events.json` into **Feedback Events JSON (optional)**.

Do not load the raw Microsoft 365 export directly. Rows with blank Agent ID cannot be safely attributed to ESS and are excluded.

---

## Step 4 — Download & open the template

1. **Build the required agent registry**
   - Follow [Agent registry and reporting scope](AGENT-REGISTRY.md).
   - Use the transcript file from Step 1 to find the agent's `BotId`.
   - Generate `agent-registry.json`.

2. **Download the .pbit**
   - In this repo, click **[`ESS Dashboard - Dynamic Topics (CSV) V18.pbit`](./ESS%20Dashboard%20-%20Dynamic%20Topics%20%28CSV%29%20V18.pbit)**
   - Click **Download raw file** (top-right of the file preview)

3. **Open it**
   - Double-click the downloaded `.pbit` — it opens in Power BI Desktop and shows a parameter prompt

---

## Step 5 — Provide the file paths

In the parameter prompt, paste the **full absolute path** to each CSV from Steps 1–3:

| Parameter | Required? | Example value |
|---|---|---|
| **Copilot Studio Transcript** | ✅ Yes | `C:\Users\<you>\Documents\AgentData\ConversationTranscripts.csv` |
| **Org Data File** | ⭐ Recommended | `/Users/<you>/Documents/AgentData/OrgData.csv` |
| **Agent Credits  (optional)** | Optional | `C:\Users\<you>\Documents\AgentData\EntitlementConsumptionTenantPerUserDetailsReport_MCSMessages_30.csv` |
| **Agent Scope Mode** | ✅ Yes | `ESS Safe` (default), `Selected Agents`, or `All Agents` |
| **Agent Registry JSON** | Required for ESS Safe / Selected Agents | Paste the full contents of `agent-registry.json` |
| **Customer Topic Overrides JSON (optional)** | Optional | Paste the full contents of `customer-topic-overrides.json` |
| **Feedback Events JSON (optional)** | Optional | Paste the full contents of `feedback-events.json` from `ess_feedback_normalizer.py` |

Click **Load**.

### Minimum successful first run

For the smallest working configuration, provide:

1. **Copilot Studio Transcript** — the untouched CSV from Step 1.
2. **Agent Scope Mode** — `ESS Safe`.
3. **Agent Registry JSON** — the complete contents of the JSON generated in Step 4.

Leave Org Data, credits, topic overrides, and feedback blank for the first load. After the report opens and **Total Conversations** is non-zero, add optional inputs one at a time and refresh after each addition. This makes any input error easy to identify.

> 💡 **Leaving an optional field blank is fine.** The template loads cleanly and the relevant pages just stay empty until you add the data.

> ⚠️ **Use forward slashes on Mac, backslashes on Windows.** Wrap paths in nothing — just paste the raw path.

> 💡 **Agent scope.** `ESS Safe` includes only enabled registry agents marked as ESS. `Selected Agents` uses the registry's `Selected` flag. `All Agents` is explicit opt-in and preserves unmapped transcript/credit agents with diagnostic keys; Product Feedback still requires a registry match. See [Agent registry and reporting scope](AGENT-REGISTRY.md).

> 💡 **Topic classification.** Native Copilot Studio topics are preserved. Rows without a native topic use the shared customer-neutral English, Spanish, and Chinese taxonomy in `taxonomy/topics-taxonomy.csv`. Complete-word matching, scoring, exclusions, and ambiguity handling prevent partial-word collisions and leave low-signal prompts as **Other / Uncategorized**.

> Need customer-specific topics? Run the [Private topic tuner](TOPIC-TUNER.md), review the generated candidates, then paste its approved JSON into the optional parameter. No new template release is required.

> Microsoft 365 Copilot Chat reactions aren't stored in Dataverse transcripts. Follow [Cross-channel feedback ingestion](FEEDBACK-INGESTION.md) to normalize Product Feedback or Monitor exports, then paste the resulting JSON here. This avoids cross-source privacy conflicts.

> Parent/child attribution requires **Include node-level details in transcripts**. When connected-agent traces are present, the Improvement Opportunities Fix-It Queue shows every participating child and its completion state. See [Parent and child agent attribution](CHILD-AGENT-ATTRIBUTION.md).

### Validate with fabricated sample data

The repository's [`SampleData`](./SampleData/) folder contains a matching, fully synthetic set. For CSV V18 use:

- `SampleData/ConversationTranscripts.csv`
- `SampleData/OrgData.csv`
- `SampleData/EntitlementConsumptionTenantPerUserDetailsReport_MCSMessages_30_SYNTHETIC.csv`
- `SampleData/agent-registry.json`
- `SampleData/feedback-events.csv`
- `SampleData/feedback-events.json`

Use `ESS Safe` and paste `agent-registry.json`. The expected validation totals are **168 conversations**, **25 users**, **109 resolved conversations**, **1,651.75 observed credits**, and **516.89 observed billable credits**. With the contents of `feedback-events.json` pasted into the parameter, the unified table has **56 feedback events**: **41 thumbs up** and **15 thumbs down** after one exact duplicate is removed.

---

## Step 6 — Validate before sharing

When the model finishes loading, go to the **Organization Adoption** page and sanity-check:

- [ ] **Total Conversations** is non-zero and roughly matches the row count of your transcripts CSV
- [ ] **Total Users** is plausible — not `1`, not equal to Total Conversations (somewhere in between)
- [ ] **Conversations & Users by Week** line chart shows a sensible date range matching your export window
- [ ] If you loaded Org Data: **Users by Organization** and **Users by Country** show real labels, not just `(Blank)`

Then check the **Metric Glossary** page (📖) — it defines the metrics used across the report. Use it to answer "where does this number come from?" before stakeholders ask.

---

## Step 7 — Refresh, publish, share

| Goal | How |
|---|---|
| **Refresh after new export** | Drop the fresh CSV at the same path → **Home → Refresh** |
| **Publish to Power BI Service** | **Home → Publish** → pick workspace. For **gateway‑free scheduled refresh**, host the CSV on **SharePoint/OneDrive** — see **[AUTO-REFRESH.md](./AUTO-REFRESH.md)**. A local/network CSV needs an on‑prem data gateway. |
| **Export to PDF for monthly recap** | **File → Export → Export to PDF** |
| **Re-brand for a different agent** | Edit the "ESS Agent" title text on each page header → save as new `.pbit` |

---

## Quick reference card

Save this as a sticky note:

| Step | What | Where | Time |
|---|---|---|---|
| 1 | Export `ConversationTranscript` table | Power Apps → Tables | 5 min |
| 2 | Export HR roster (optional) | HR system or Entra/Graph | 2 min |
| 3 | Download 30-day User-Level Credit Consumption CSV (optional) | [Power Platform admin center](https://admin.powerplatform.microsoft.com) → Licensing → Copilot Studio → Summary → Download report | 2 min |
| 4 | Export and prepare Microsoft 365 Product Feedback (optional) | Microsoft 365 admin center → Health → Product feedback | 5–10 min |
| 5 | Download & open `.pbit` | This repo | 1 min |
| 6 | Paste file paths and optional JSON into the parameter prompt | Power BI Desktop | 1 min |
| 7 | Validate conversations, users, and optional feedback | Report pages | 2 min |
| 8 | Publish to workspace or export PDF | Power BI Service | 2 min |

---

## Common issues & fixes

| Symptom | Cause | Fix |
|---|---|---|
| `M Engine error: Token Identifier expected` on open | CSV opened in Excel before loading; Excel corrupted the JSON | Re-export from Dataverse, do **not** open in Excel |
| Can't find `ConversationTranscript` table in Power Apps | Missing **Bot Transcript Viewer** security role | Ask your admin to grant it — Environment Maker isn't enough |
| Empty CSV after export | Agent runs in Teams/Developer/M365 Copilot env (transcripts aren't written) | Move agent to standard Dataverse production/sandbox env |
| Power BI hangs or runs out of memory on load | Very large transcript file (>500 MB) | Apply a date filter at the Dataverse export step to narrow the window |
| `Users by Organization` shows everyone as `(Blank)` | Org Data UPN column doesn't match transcripts | Confirm column is named `UserPrincipalName` and values are full UPNs (`user@contoso.com`) |
| `Users by Country` chart shows "Something's wrong with one or more fields" | Org Data CSV missing the `Country` column | Add a `Country` column (can be empty), or download the latest `.pbit` from this repo |
| Observed Credit Leaderboard is blank | User-Level Credit Consumption file is missing or no `Agent Id` matches the transcripts | Use the 30-day Power Platform admin center User-Level export and verify it covers the same ESS agent |
| Microsoft 365 feedback is missing | Raw tenant export was not normalized, Agent ID is blank, or the `M365Title` registry alias does not match | Follow the feedback guide, review `feedback-events.audit.json`, and paste the newly generated JSON parameter |
| Total Users count seems too low | Same employee shows as both UPN and Entra Object ID in transcripts | Already handled — the model cross-walks both identities automatically |
| Repeat-usage rate is 0% | Period too short — everyone is a first-time user | Widen the date filter or wait for more data |

---

## Need more help?

- 🐛 [Open an issue](https://github.com/microsoft/ESS/issues)
- 🩺 Check the **Load Diagnostics** page (in the page selector) for row counts and parser warnings
- 📖 The **Metric Glossary** page has every measure's definition and source
