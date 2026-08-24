# Set up automatic (scheduled) refresh

Keep your ESS Insights dashboard current **without re‑opening Power BI Desktop** by letting the **Power BI / Microsoft Fabric service** refresh the data on a schedule.

This guide covers the three supported hosting paths and the exact steps for each:

| Your data lives… | Gateway needed? | Cloud scheduled refresh? | Jump to |
|---|---|---|---|
| **Dataverse** (Dataverse Direct template) | ❌ No | ✅ Yes — cloud‑to‑cloud | [Path A ↓](#path-a--dataverse-direct-recommended) |
| **SharePoint / OneDrive‑hosted CSV** (CSV Upload template) | ❌ No | ✅ Yes — cloud‑to‑cloud | [Path B ↓](#path-b--csv-hosted-on-sharepoint--onedrive) |
| **Local / network‑drive CSV** (CSV Upload template) | ✅ Yes | ⚠️ Only via an on‑prem data gateway | [Path C ↓](#path-c--csv-on-a-local-or-network-path) |

> ✅ **Start here:** For hands‑off, production dashboards, **Dataverse Direct (Path A)** is the simplest — no file hosting, no gateway. If you must stay on CSV, **host it on SharePoint/OneDrive (Path B)** so the cloud can refresh it without a gateway.

> 🆕 **Why this matters for refresh:** Some older template versions could trip a **"dynamic data source"** error in the service that blocked *all* scheduled refresh. The current **V10** templates structure every data source (Dataverse and web/SharePoint) so the service can identify and authenticate it statically — the prerequisite for scheduled refresh. **Use the V10 templates** for anything you intend to auto‑refresh.

> 🆕 **Already need more than this?** Path A and Path B above already give you gateway‑free, cloud‑to‑cloud scheduled refresh — most customers don't need anything else. If you're consolidating multiple Dataverse environments into one dashboard, hitting refresh limits at very large scale, or want built‑in Copilot credit‑consumption analytics alongside conversation data, see **[SETUP-Fabric.md ↗](SETUP-Fabric.md)**.

---

## Before you begin (all paths)

- [ ] You have **published** the report from Power BI Desktop to a **workspace** in the Power BI service (**Home → Publish**).
- [ ] You have permission to manage that workspace's datasets (**Member/Admin/Contributor**).
- [ ] The dataset **refreshes successfully in Desktop first** — fix any load errors locally before scheduling in the cloud.

> A cloud schedule can only ever be as healthy as a manual Desktop refresh. Always get a clean **Home → Refresh** in Desktop before publishing.

---

## Path A — Dataverse Direct (recommended)

The Dataverse Direct template connects the service **directly to your Dataverse environment** — no exported files, no gateway.

1. **Publish** the `ESS Dashboard - Dynamic Topics (Dataverse) V10` report to your workspace.
2. In the service, open the **dataset → Settings** (or **… → Settings** next to the dataset).
3. Expand **Data source credentials** and click **Edit credentials** on the Dataverse source:
   - **Authentication method:** `OAuth2`
   - **Privacy level:** `Organizational`
   - Sign in with an account that holds the **Bot Transcript Viewer** role (or equivalent read access to the `conversationtranscript` table) on that environment.
4. *(Optional)* Expand **Parameters** to confirm **Dataverse Environment URL** and **Transcript Lookback Days**. A smaller lookback = faster refresh (the filter runs server‑side on Dataverse).
5. Expand **Scheduled refresh** → toggle **On** → set your cadence (up to **8×/day** on Pro; more on Premium/Fabric capacity) and time zone → **Apply**.

✅ **Done.** The service now pulls fresh transcripts on your schedule with **no gateway**.

> 💡 Because the lookback filter runs on Dataverse, you can safely schedule frequent refreshes even on large environments — keep the window as narrow as your reporting needs allow.

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

3. Open `ESS Dashboard - Dynamic Topics (CSV) V10` in Desktop. When prompted (or via **Transform data → Edit Parameters**), paste the **direct SharePoint URL** into **Copilot Studio Transcript**. (Optional Org Data / Agent Credits files can be hosted the same way.)
4. **Home → Refresh** to confirm it loads locally, then **Publish** to your workspace.

### B3. Bind credentials & schedule

5. In the service, open the **dataset → Settings → Data source credentials → Edit credentials** on the **Web** source:
   - **Authentication method:** `OAuth2` (Organizational account)
   - **Privacy level:** `Organizational`
   - Sign in with an account that can read that SharePoint library.
6. Expand **Scheduled refresh** → **On** → set cadence → **Apply**.

✅ **Done.** Whenever a **new export overwrites the file at the same URL**, the scheduled refresh picks it up — no gateway required.

> 🔁 **Keep the URL stable.** Refresh follows the *path*, not the file. Overwrite the existing file (same name, same folder) rather than uploading a date‑stamped copy, or the schedule will keep reading the old file.

> 🤖 **Automate the export drop (optional):** Use a **Power Automate** flow or a scheduled Dataverse export to write the latest `conversationtranscript` CSV to that same SharePoint path on a cadence. Combined with scheduled refresh, this makes the CSV path effectively hands‑off.

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
| **“You can't schedule refresh for this dataset because … the data sources are dynamic.”** | Data source URL/connection can't be resolved statically (older template, or a viewer‑style SharePoint link). | Use the **V10** template, and for CSV use a **direct file path URL** (Path B), not a `?web=1`/sharing link. |
| **“We couldn't authenticate with the credentials provided.”** | Credentials not bound, or account lacks access. | **dataset → Settings → Data source credentials → Edit credentials**; sign in with an account that has Bot Transcript Viewer (Dataverse) or library read (SharePoint). |
| **Scheduled refresh option is greyed out.** | Credentials for one or more sources not yet set. | Edit credentials on **every** listed source first, then the schedule unlocks. |
| **Refresh succeeds but data is stale.** | New export saved under a new name/path. | Overwrite the file at the **same URL/path** the parameter points to. |
| **Refresh very slow / times out (Dataverse).** | Lookback window too wide. | Lower **Transcript Lookback Days**. |
| **“The remote name could not be resolved” / “Invalid URL.”** | Trailing slash or typo in a parameter. | Re‑copy the environment URL / file URL and re‑enter via **Edit Parameters**. |

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
