# Step-by-Step Setup Guide — Dataverse Direct

Get the **ESS Insights dashboard** running on your own Copilot Studio agent data, **connected live to Dataverse** — no CSV exports, no file paths, no manual refresh shuffle.

> 💡 **Which version is this?** This is the **Dataverse Direct** template. It pulls `conversationtranscript` rows straight from the Dataverse environment that hosts your agent. If you'd rather work with a one-time CSV export, use the [CSV Upload guide](./SETUP-CSV-Download.md) instead.

---

## Before you start

✅ **Power BI Desktop** installed — [download free](https://powerbi.microsoft.com/desktop/)
✅ **Bot Transcript Viewer** security role on the Dataverse environment that hosts your ESS agent — an admin must grant this. [Microsoft's how-to](https://learn.microsoft.com/en-us/microsoft-copilot-studio/admin-share-bots#assign-the-bot-transcript-viewer-security-role-during-agent-sharing)
✅ The **Environment URL** of the Dataverse env that hosts your ESS agent (Step 1 below)
✅ A folder for the optional Org Data / Feedback / Credits CSVs (e.g. `Documents/AgentData`)

> ⚠️ **Environment Maker is NOT enough.** Without the Bot Transcript Viewer role, the connector signs in successfully but returns zero `conversationtranscript` rows.

---

## Step 1 — Find your Dataverse Environment URL ✅ Required

**Outcome:** a URL like `https://orgabc12345.crm.dynamics.com` that points at the environment hosting your agent.

1. Sign in to [https://make.powerapps.com](https://make.powerapps.com/)
2. Use the **environment selector** (top-right) to switch to the environment that hosts your **ESS agent**
3. Click the **⚙️ gear icon** (top-right) → **Session details**
4. In the dialog, find **Instance url** (also shown as "Org URL")
5. Copy the value — it looks like:
   - `https://orgabc12345.crm.dynamics.com` (North America)
   - `https://orgabc12345.crm4.dynamics.com` (Europe)
   - `https://orgabc12345.crm6.dynamics.com` (Australia)

> 💡 **Drop the trailing slash.** Use `https://orgabc12345.crm.dynamics.com`, not `…/`. Power BI's Dataverse connector is picky.

> ⚠️ **Multiple environments?** This template targets **one environment** at a time. If your agents live in two or three envs, build a copy of the `.pbit` per environment.

---

## Step 2 — (Recommended) Export your Org Data ⭐

**Outcome:** a CSV that maps each user's UPN to Department, Country, and JobTitle. Unlocks "Users by Organization" and "Users by Country" charts.

| Column | Example | Required? |
|---|---|---|
| `UserPrincipalName` | `jane.doe@contoso.com` | ✅ Yes |
| `Department` | `Finance` | ⭐ Recommended |
| `Country` | `USA` | ⭐ Recommended |
| `JobTitle` | `Senior Analyst` | Optional |
| `DisplayName` | `Jane Doe` | Optional |

**Where to get it** (pick one):

- 🅰️ **From HR** — most HR systems can export a roster CSV with the columns above
- 🅱️ **From the Microsoft 365 Admin Center**:
  1. Sign in to the [Microsoft 365 Admin Center](https://admin.microsoft.com) with a Global Reader, User Admin, or Global Admin role.
  2. **Users → Active users → Export users → Confirm**.
  3. Move/rename the downloaded file to `Documents/AgentData/OrgData.csv`. Column-name differences are normalized by the template.
- 🅲 **Skip for now** — the template loads cleanly without it.

---

## Step 3 — (Optional) Export Agent Credits

1. Sign in to [Copilot Studio](https://copilotstudio.microsoft.com) and open your ESS agent.
2. **Analytics → Message Consumption**.
3. Apply a date range matching your transcripts.
4. **Export** → save to `Documents/AgentData/AgentCredits.csv`.

---

## Step 4 — Download & open the template

1. In this repo, click **[`ESS Dashboard - Dynamic Topics (Dataverse) V10.pbit`](./ESS%20Dashboard%20-%20Dynamic%20Topics%20(Dataverse)%20V10.pbit)** → **Download raw file**.
2. Double-click the downloaded `.pbit` — it opens in Power BI Desktop and shows a parameter prompt.

---

## Step 5 — Provide the parameters

| Parameter | Required? | Example value |
|---|---|---|
| **Dataverse Environment URL** | ✅ Yes | `https://orgabc12345.crm.dynamics.com` |
| **Transcript Lookback Days** | Optional — leave blank for 90 | `30`, `60`, `180` |
| **Org Data File** | ⭐ Recommended | `/Users/<you>/Documents/AgentData/OrgData.csv` |
| **Agent Credits File** | Optional | `…/AgentCredits.csv` |

Click **Load**.

> 💡 **Lookback Days** controls how far back the connector pulls transcripts. The filter runs **server-side** on Dataverse, so a smaller window = faster refresh. Default is 90 days.

---

## Step 6 — Sign in to Dataverse

After Load, Power BI prompts for credentials on the Dataverse data source:

1. Select **Organizational account**
2. Click **Sign in** and complete OAuth (MFA, Conditional Access, etc.)
3. Click **Connect**

> 💡 **One-time per environment.** Power BI caches the credential under *File → Options → Data source settings*. To switch environments, clear the entry there and re-auth.

> ⚠️ **"We couldn't authenticate with the credentials provided."** Confirm you signed in with an account that has the **Bot Transcript Viewer** role in this environment. Tenant admin ≠ environment role.

---

## Step 7 — Validate before sharing

Go to the **Organization Adoption** page and sanity-check:

- [ ] **Total Conversations** is non-zero and roughly matches Copilot Studio's own analytics for the same window
- [ ] **Total Users** is plausible — not `1`, not equal to Total Conversations
- [ ] **Conversations & Users by Week** matches your Lookback Days
- [ ] If you loaded Org Data: **Users by Organization** and **Users by Country** show real labels

Then check the **Metric Glossary** page (📖) — it defines the metrics used across the report.

---

## Step 8 — Refresh, publish, share

| Goal | How |
|---|---|
| **Refresh with latest transcripts** | **Home → Refresh** — pulls live from Dataverse |
| **Publish to Power BI Service** | **Home → Publish**. **No Gateway required** — cloud-to-cloud |
| **Schedule refresh** | Service: dataset → **Settings → Scheduled refresh**. Bind Dataverse credentials (OAuth2 / Organizational) first. Step‑by‑step: **[AUTO-REFRESH.md](./AUTO-REFRESH.md)** |
| **Export to PDF** | **File → Export → Export to PDF** |
| **Switch environments** | **Transform data → Edit Parameters → Dataverse Environment URL** → re-auth via Data source settings |

> 💡 **No Gateway** is the headline benefit. Cloud Power BI Service talks directly to cloud Dataverse — schedule hourly if you want.

---

## Quick reference card

| Step | What | Where | Time |
|---|---|---|---|
| 1 | Copy Environment URL | Power Apps → ⚙️ → Session details | 1 min |
| 2 | Export HR roster (optional) | M365 Admin Center | 2 min |
| 3 | Export Agent Credits (optional) | Copilot Studio → Analytics | 2 min |
| 4 | Download & open `.pbit` | This repo | 1 min |
| 5 | Paste env URL + lookback into prompt | Power BI Desktop | 1 min |
| 6 | OAuth into Dataverse | Auth dialog | 1 min |
| 7 | Validate metrics | Adoption page | 1 min |
| 8 | Publish | Power BI Service | 2 min |

---

## Common issues & fixes

| Symptom | Cause | Fix |
|---|---|---|
| `We couldn't authenticate with the credentials provided` | Account lacks Bot Transcript Viewer, or wrong env URL | Confirm role in Power Platform Admin Center → environment → Settings → Users + permissions → Security roles |
| `The remote name could not be resolved` / `Invalid URL` | Trailing slash or typo | Re-copy from Power Apps → ⚙️ → Session details |
| Refresh succeeds but **Total Conversations = 0** | Teams/Developer/M365 Copilot env (transcripts not written), or empty lookback | Move agent to a standard production/sandbox Dataverse env; widen Lookback Days |
| Refresh is very slow (5+ min) | Lookback too wide | Lower Lookback Days |
| `Users by Organization` all `(Blank)` | Org Data UPN doesn't match transcripts | Confirm `UserPrincipalName` column with full UPNs |
| Credit Consumption page blank | Agent Credits file not loaded | Export from Copilot Studio Analytics → Message Consumption |
| Total Users too low | Same employee as both UPN and Entra Object ID | Already handled by the model |
| Repeat-usage rate is 0% | Lookback too short | Widen to 60 or 90 days |
| Need to switch environment | Cached credential points at old env | **File → Options → Data source settings → Clear Permissions** |

---

## CSV Upload vs Dataverse Direct — which should I use?

| | CSV Upload | Dataverse Direct *(this guide)* |
|---|---|---|
| Setup time | ~10 min | ~5 min |
| Refresh | Re-export CSV, drop at path, click Refresh | One click — Refresh pulls live |
| Service refresh | Needs **Gateway** | **No Gateway** — cloud-to-cloud |
| Tenant access | Anyone who can run the export | Bot Transcript Viewer on the env |
| Lookback control | Whatever the export window allows (default 30 days) | Parameter — pull 30 / 90 / 365 at will |
| Best for | One-off snapshots, demos, sharing outside tenant | Production dashboards, scheduled refresh |

---

## Need more help?

- 🐛 [Open an issue](https://github.com/microsoft/ESS/issues)
- 🩺 Check the **Load Diagnostics** page for row counts and parser warnings
- 📖 The **Metric Glossary** page has every measure's definition
