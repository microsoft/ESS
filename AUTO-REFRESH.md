# Set up automatic (scheduled) refresh

Keep your ESS Insights dashboard current **without re‑opening Power BI Desktop** by letting the **Power BI / Microsoft Fabric service** refresh the data on a schedule.

This guide covers the three supported hosting paths and the exact steps for each:

| Your data lives… | Gateway needed? | Cloud scheduled refresh? | Jump to |
|---|---|---|---|
| **Dataverse** (Dataverse Direct template) | ❌ No | ✅ Yes — cloud‑to‑cloud | [Path A ↓](#path-a--dataverse-direct-recommended) |
| **SharePoint / OneDrive‑hosted CSV** (CSV Upload template) | ❌ No | ✅ Yes — cloud‑to‑cloud | [Path B ↓](#path-b--csv-hosted-on-sharepoint--onedrive) |
| **Local / network‑drive CSV** (CSV Upload template) | ✅ Yes | ⚠️ Only via an on‑prem data gateway | [Path C ↓](#path-c--csv-on-a-local-or-network-path) |

> ✅ **Start here:** For hands‑off, production dashboards, **Dataverse Direct (Path A)** is the simplest — no file hosting, no gateway. If you must stay on CSV, **host it on SharePoint/OneDrive (Path B)** so the cloud can refresh it without a gateway.

> **Why this matters for refresh:** Dataverse V22 passes the validated customer URL directly to the Dataverse connector through a Power Query parameter, which Power BI Service supports for refresh. The customer-neutral Service PBIT removes all Organization and Credits connectors. When organization data is selected in the guided builder, it validates the SharePoint Online or OneDrive for Business CSV path and emits a customer-specific static SharePoint source.

> 🆕 **Already need more than this?** Path A and Path B above already give you gateway‑free, cloud‑to‑cloud scheduled refresh — most customers don't need anything else. If you're consolidating multiple Dataverse environments into one dashboard, hitting refresh limits at very large scale, or want [Power Platform admin center](https://admin.powerplatform.microsoft.com) credit-consumption analytics alongside conversation data (with a separate file-landing step), see **[SETUP-Fabric.md ↗](SETUP-Fabric.md)**.

---

## Before you begin (all paths)

- [ ] For Dataverse, you published either the directly downloaded or guided **Power BI Service - PUBLISH THIS** report, not a **Desktop Validation - DO NOT PUBLISH** report.
- [ ] You have **published** the report from Power BI Desktop to a **workspace** in the Power BI service (**Home → Publish**).
- [ ] You have permission to manage that workspace's datasets (**Member/Admin/Contributor**).
- [ ] The dataset **refreshes successfully in Desktop first** — fix any load errors locally before scheduling in the cloud.

> A cloud schedule can only ever be as healthy as a manual Desktop refresh. Always get a clean **Home → Refresh** in Desktop before publishing.

---

## Path A — Dataverse Direct (recommended)

The report prepared by the Dataverse publication step connects the service directly to the Dataverse environment selected in its parameter - no transcript export and no gateway.

1. Complete [Action 3 in the Dataverse guide](SETUP-Dataverse.md#action-3---publish-the-service-report). URL-only users can publish the Service-ready PBIT without Python. Guided users run the existing publication helper to reuse the validated Environment URL and approved registry, feedback, and topic data.

   Local Organization and Credits files are not included in the publishable Dataverse report. Organization data requires the guided builder's validated static SharePoint source; use Fabric when the source must be Entra/Graph, credits must be automated, or several environments must be combined.

2. Confirm the prepared filename ends with **Power BI Service - PUBLISH THIS.pbit**. Paste the required Environment URL and leave optional parameters blank for the transcript-only baseline. If organization data is required, run `BUILD-SERVICE-REFRESH.cmd` first and supply the direct SharePoint/OneDrive CSV path so the helper can generate the static source. Wait until every value is visible and stable, then select **Load**, refresh successfully in Desktop, save as PBIX, and **Publish** it to your workspace. Neither publishable PBIT exposes local Organization or Credits file parameters.
3. In the service, open the **semantic model → Settings**.
4. Expand **Gateway and cloud connections**:
   - Turn off **Use an On-premises or VNet data gateway**; Dataverse does not require one.
   - Map the Dataverse source to **Personal Cloud Connection** and select **Apply**.
   - If no suitable connection exists, select **Create a connection**, choose `OAuth2`, set privacy to `Organizational`, and sign in with an account that holds the **Bot Transcript Viewer** role (or equivalent read access to `conversationtranscript`).
   - If organization data is configured, map the SharePoint source to a cloud connection using an account that can read the hosted CSV.
   - In tenants that still show the legacy pane, use **Data source credentials → Edit credentials** with the same OAuth2 and privacy settings.
5. Expand **Parameters** to confirm **Dataverse Environment URL** matches the intended environment. The transcript-only template has four parameters and no organization URL parameter. If you change the Dataverse URL, apply the change and update the cloud connection before refreshing.
6. From the semantic model menu, select **Refresh now**.
7. Open **Refresh history** and confirm the refresh status is **Completed**. Do not enable a schedule until this manual Service refresh succeeds.
8. Expand **Scheduled refresh** → toggle **On** → set your cadence (up to **8×/day** on Pro; more on Premium/Fabric capacity) and time zone → **Apply**.

✅ **Done.** The service now pulls fresh transcripts on your schedule with **no gateway**.

> 💡 Because the lookback filter runs on Dataverse, you can safely schedule frequent refreshes even on large environments — keep the window as narrow as your reporting needs allow.

> ⚠️ **Scheduled refresh is not historical storage.** It re-queries Dataverse and therefore reflects only records still retained there. Extend Dataverse transcript retention for the reporting period you need; records deleted before a refresh cannot be restored by Power BI.

> ⚠️ **Local Organization and Credits files are excluded from the publishable Dataverse report.** The customer-neutral template contains no organization connector. A guided organization build uses a static native SharePoint query so the Service model never carries a dynamic or local-file branch.

---

## Path B — CSV hosted on SharePoint / OneDrive

You can get **gateway‑free cloud refresh** with the CSV Upload template *if the CSV lives on SharePoint or OneDrive for Business* (both are cloud sources the service can reach directly).

### B1. Host the file

1. Upload your exported `conversationtranscript` CSV to a **SharePoint document library** or **OneDrive for Business** folder.
2. Get its **direct file path URL** (not a sharing/`?web=1` link):
   - In SharePoint/OneDrive, open the **… menu → Details → Path**, or use **Copy link → More settings → “Copy direct link”**.
   - It should look like:
     `https://contoso.sharepoint.com/sites/HR/Shared Documents/ess/conversationtranscript.csv`
   - ⚠️ Avoid links containing `:x:/` , `?d=`, `&web=1`, or `guestaccess.aspx` — those are viewer links, not file paths, and will not refresh.

### B2. Point the template at it

3. Open `ESS Dashboard - Dynamic Topics (CSV) V18` in Desktop. Paste the **direct SharePoint URL** into **Copilot Studio Transcript**. Optional Org Data and the 30-day Power Platform admin center User-Level Credit Consumption CSV can be hosted the same way.
4. **Home → Refresh** to confirm it loads locally, then **Publish** to your workspace.

### B3. Bind credentials & schedule

5. In the service, open the **dataset → Settings → Data source credentials → Edit credentials** on the **Web** source:
   - **Authentication method:** `OAuth2` (Organizational account)
   - **Privacy level:** `Organizational`
   - Sign in with an account that can read that SharePoint library.
6. Expand **Scheduled refresh** → **On** → set cadence → **Apply**.

✅ **Done.** Whenever a **new export overwrites the file at the same URL**, the scheduled refresh picks it up — no gateway required.

> 🔁 **Keep the URL stable.** Refresh follows the *path*, not the file. Overwrite the existing file (same name, same folder) rather than uploading a date‑stamped copy, or the schedule will keep reading the old file.

> ⚠️ **Source-file automation isn't included.** This repository doesn't include or validate a Power Automate package or scheduled Dataverse CSV export. For supported hands-off transcript refresh, use **Dataverse V22**. If you build a custom file-landing process, validate its permissions, schema preservation, overwrite behavior, and failure monitoring before production use.

---

## Path C — CSV on a local or network path

If the parameter points at a **local file** (`C:\Data\…`) or a **network share** (`\\server\share\…`), the cloud service cannot reach it directly. You have two options:

- **Preferred:** move the file to SharePoint/OneDrive and follow **[Path B](#path-b--csv-hosted-on-sharepoint--onedrive)** — no gateway.
- **Or install an [on‑premises data gateway](https://learn.microsoft.com/power-bi/connect-data/service-gateway-onprem)** (personal or standard) on a machine that can see the file:
  1. Install and sign in to the gateway.
  2. In **dataset → Settings → Gateway connection**, map the file data source to your gateway.
  3. Enable **Scheduled refresh** as above.

> The gateway machine must be **on and online** at each scheduled refresh time.

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| **“You can't schedule refresh for this dataset because … the data sources are dynamic.”** | The report was prepared with an older package, its Dataverse query was modified, or it still contains a local-file branch. | Download the current Service-ready PBIT or repeat the guided [Action 3](SETUP-Dataverse.md#action-3---publish-the-service-report), refresh it in Desktop, and publish that result. |
| Organization filters are blank | The customer-neutral PBIT was used, the guided URL was invalid, the file moved, or the SharePoint cloud connection is not mapped | Rebuild with a validated direct CSV path, map the SharePoint cloud connection, and run **Refresh now** |
| **“We couldn't authenticate with the credentials provided.”** | A cloud connection is not mapped, or the account lacks access. | **Semantic model → Settings → Gateway and cloud connections**; map or create the OAuth2 connection using an account with Bot Transcript Viewer (Dataverse) or library read (SharePoint). |
| **Scheduled refresh option is greyed out.** | Credentials for one or more sources not yet set. | Edit credentials on **every** listed source first, then the schedule unlocks. |
| **Refresh succeeds but data is stale.** | New export saved under a new name/path. | Overwrite the file at the **same URL/path** the parameter points to. |
| **Refresh very slow / times out (Dataverse).** | Lookback window too wide. | Lower **Transcript Lookback Days**. |
| **“The remote name could not be resolved” / “Invalid URL.”** | The Environment URL used during publication preparation was wrong. | Re-copy the Instance URL and repeat the Dataverse publication step. |
| **Queries are blocked / “A cyclic reference was encountered” immediately after Load.** | Load was selected before the prefilled parameter values finished initializing. | Close the report without saving, reopen the prepared report, wait for every value to appear and stabilize, then select **Load**. |

---

## Which cadence should I pick?

| Use case | Suggested schedule |
|---|---|
| Executive monthly recap | Daily (overnight) is plenty |
| Ongoing program monitoring | 2–4× per day |
| Active launch / triage window | Hourly (Dataverse Direct, or Premium/Fabric capacity) |

> Refresh only needs to run as often as your **source data actually changes**. Copilot Studio writes transcripts continuously, but most stakeholders read the dashboard daily at most — a nightly refresh keeps costs and load low while staying current.

---

*Related: [CSV Upload setup ↗](SETUP-CSV-Download.md) · [Dataverse Direct setup ↗](SETUP-Dataverse.md) · [Back to README ↗](README.md)*
