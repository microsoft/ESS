# Step-by-Step Setup Guide

Get the **ESS Insights dashboard** running on your own Copilot Studio agent data in about **10 minutes**.

---

## Before you start

✅ **Power BI Desktop** installed — [download free](https://powerbi.microsoft.com/desktop/)
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
  5. Open the downloaded CSV and confirm it includes the columns `User principal name`, `Department`, `Job Title`, `Country or region`, `Display name`, and `Email`. (Column names differ slightly from what the template expects — that's fine, the template normalizes them.)
  6. Move/rename the file to your data folder, e.g. `Documents/AgentData/OrgData.csv`.

  > 💡 The export contains every licensed user in your tenant. If your ESS agent is scoped to a subset (e.g. one country or one business unit), you can leave the file as-is — the template only joins rows whose UPN actually appears in your transcripts.
- 🅲 **Skip for now** — the template still loads. You can add Org Data later via *Transform data → Edit Parameters*.

---

## Step 3 — (Optional) Export Agent Credits

**Outcome:** unlocks the Business Impact page's credit-consumption leaderboard.

1. Sign in to [Copilot Studio](https://copilotstudio.microsoft.com) and open your ESS agent.
2. In the left navigation, select **Analytics** → **Message Consumption**.
3. Apply a date range matching your transcripts export.
4. Click **Export** and save the resulting CSV to your data folder, e.g. `Documents/AgentData/AgentCredits.csv`.

You can skip this step and add Agent Credits later — the template loads cleanly without it.

---

## Step 4 — Download & open the template

1. **Download the .pbit**
   - In this repo, click **[`ESS Dashboard - Dynamic Topics (CSV) V10.pbit`](./ESS%20Dashboard%20-%20Dynamic%20Topics%20(CSV)%20V10.pbit)**
   - Click **Download raw file** (top-right of the file preview)

2. **Open it**
   - Double-click the downloaded `.pbit` — it opens in Power BI Desktop and shows a parameter prompt

---

## Step 5 — Provide the file paths

In the parameter prompt, paste the **full absolute path** to each CSV from Steps 1–3:

| Parameter | Required? | Example value |
|---|---|---|
| **Transcript File** | ✅ Yes | `/Users/<you>/Documents/AgentData/ConversationTranscripts.csv` |
| **Org Data File** | ⭐ Recommended | `/Users/<you>/Documents/AgentData/OrgData.csv` |
| **Agent Credits File** | Optional — leave blank | `…/AgentCredits.csv` |

Click **Load**.

> 💡 **Leaving an optional field blank is fine.** The template loads cleanly and the relevant pages just stay empty until you add the data.

> ⚠️ **Use forward slashes on Mac, backslashes on Windows.** Wrap paths in nothing — just paste the raw path.

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
| 3 | Export Agent Credits / Message Consumption (optional) | Copilot Studio → Analytics | 2 min |
| 4 | Download & open `.pbit` | This repo | 1 min |
| 5 | Paste file paths into parameter prompt | Power BI Desktop | 1 min |
| 6 | Validate Total Users + Total Conversations | Adoption page | 1 min |
| 7 | Publish to workspace or export PDF | Power BI Service | 2 min |

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
| Credit Consumption page is blank | Agent Credits file not loaded | Export from Copilot Studio **Analytics → Message Consumption**, not Dataverse |
| Total Users count seems too low | Same employee shows as both UPN and Entra Object ID in transcripts | Already handled — the model cross-walks both identities automatically |
| Repeat-usage rate is 0% | Period too short — everyone is a first-time user | Widen the date filter or wait for more data |

---

## Need more help?

- 🐛 [Open an issue](https://github.com/microsoft/ESS/issues)
- 🩺 Check the **Load Diagnostics** page (in the page selector) for row counts and parser warnings
- 📖 The **Metric Glossary** page has every measure's definition and source
