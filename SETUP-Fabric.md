# Step-by-Step Setup Guide — Fabric

> ⚠️ **Read this first.** If you have a single Dataverse environment and just need scheduled refresh, use **[Dataverse Direct](SETUP-Dataverse.md)** + **[AUTO-REFRESH.md](AUTO-REFRESH.md)** instead — it's simpler and requires no Fabric capacity.

This path adds a **Fabric/Lakehouse ingestion layer** in front of the same ESS Insights dashboard, for teams that have outgrown the CSV Upload and Dataverse Direct paths. It is **not** a replacement for either — most customers should keep using whichever of those two they're already on.

---

## Is this path right for you?

Use this path only if at least one of these is true:

- [ ] **Multiple Dataverse environments.** You want conversations from two or more Dataverse environments (e.g. regional or business-unit agents) consolidated into a single dashboard, instead of maintaining one `.pbit` copy per environment.
- [ ] **Refresh performance at scale.** Per-refresh live Dataverse queries against a very large environment (long history, high conversation volume) are slow or timing out with Dataverse Direct.
- [ ] **Credit-consumption analytics.** You want the three current Power Platform admin center Copilot Credits exports ingested alongside conversation data, with the option to automate file landing in your own architecture.

If none of these apply, use **[Dataverse Direct](SETUP-Dataverse.md)** or **[CSV Upload](SETUP-CSV-Download.md)** instead — they get you running faster with no Fabric capacity required.

---

## Benefits of this path

- **Schedulable ingestion and refresh.** Transcript ingestion notebooks can be scheduled. Copilot Credits files must first be landed in the Lakehouse; manual upload is supported now, and automated landing can be added separately.
- **Multiple Dataverse environments, one dashboard.** Conversations from two or more Dataverse environments can be ingested into the same Lakehouse and consolidated into a single dashboard, instead of maintaining a separate `.pbit` copy per environment.
- **Copilot credit-consumption analytics.** `Copilot_Credit_Consumption_Ingester.ipynb` reads the three PPAC Copilot Credits reports after they are landed under `Files/credit_consumption`.
- **Automatic topic identification for every conversation.** `Copilot_Agent_Transcript_Parser.ipynb` includes a two-stage classifier that assigns a topic to every conversation — including ones Copilot Studio itself never assigned a topic to — with zero manual keyword curation required. It runs fully offline: no conversation data leaves the customer's Fabric workspace, and no LLM or external API call is involved. (See Step 3 below for how it works.)

---

## Before you start

✅ A **Fabric workspace** with Fabric capacity assigned (a trial capacity is enough to evaluate)
✅ A **Lakehouse** created in that workspace
✅ Permission to **create and run notebooks** in that workspace
✅ A **Microsoft Entra app registration** added as a Dataverse **Application User** (with read access on Conversation Transcript) in every Dataverse environment you're ingesting from — this typically needs a Dataverse or Entra administrator to set up; it's a different, additional requirement from the CSV/Dataverse-Direct paths' simpler Bot Transcript Viewer role
✅ **Power BI Desktop** installed — [download free](https://powerbi.microsoft.com/desktop/)

---

## Step 1 — Get the template and notebooks

You'll need three files:

| File | What it does |
|---|---|
| `ESS - Fabric V2.pbit` | The dashboard template — imports the Lakehouse SQL analytics endpoint and preserves decimal Copilot Credits |
| `Copilot_Agent_Transcript_Parser.ipynb` | Notebook that parses conversation transcripts into the `agent_sessions` and `agent_catalogue` Delta tables |
| `Copilot_Credit_Consumption_Ingester.ipynb` | Notebook that ingests PPAC reports into `dbo.credit_consumption_tenant`, `dbo.credit_consumption_agent`, and `dbo.credit_consumption_user` |

> Both notebooks are adapted from the community, MIT-licensed **[StudioLens-for-Copilot-Studio](https://github.com/Keithland89/StudioLens-for-Copilot-Studio)** project by **Keithland89** — see [Attribution & license ↓](#attribution--license).

---

## Step 2 — Land the notebooks in your Fabric workspace

1. In your Fabric workspace, import both `Copilot_Agent_Transcript_Parser.ipynb` and `Copilot_Credit_Consumption_Ingester.ipynb` (**New → Import notebook**).
2. Attach each notebook to your **Lakehouse** (**Add lakehouse** in the notebook's Explorer pane).
3. In the transcript parser CONFIG cell, set `DATAVERSE_URL` for one environment or populate `DATAVERSE_URLS` with every environment URL and run the notebook once. A consolidated run prevents the default `overwrite` mode from replacing an earlier environment. If you intentionally orchestrate separate incremental runs, use `WRITE_MODE = 'merge'`.

> 💡 **Fill in the CONFIG cell.** `Copilot_Agent_Transcript_Parser.ipynb`'s CONFIG cell needs `TENANT_ID`, `CLIENT_ID`, and `CLIENT_SECRET` filled in for the app registration from the checklist above. For production, use `notebookutils.credentials.getSecret('<kv-uri>', '<secret-name>')` instead of a literal secret value in the notebook.

### Land the three Copilot Credits exports

1. In **Power Platform admin center**, go to **Licensing → Copilot Studio → Summary → Download report**. Access shown by PPAC is tenant administrator, Power Platform Administrator, or Dynamics 365 Administrator; use **Power Platform Administrator** as least privilege for this workflow.
2. Set **Usage type** to `Copilot Credits`, choose a `30`, `60`, `90`, or `180` day lookback, and download each type: **Environment Consumption Summary**, **Agent-Level Credit Consumption**, and **User-Level Credit Consumption**.
3. In the attached Lakehouse, create/open **Files → `credit_consumption`** and upload all three CSVs. At 30 days their generated names are:
   - `EntitlementConsumptionTenantDetailsReport_MCSMessages_30.csv`
   - `EntitlementConsumptionTenantPerAgentDetailsReport_MCSMessages_30.csv`
   - `EntitlementConsumptionTenantPerUserDetailsReport_MCSMessages_30.csv`

   Keep exactly one current file of each type in this folder. Move or delete older downloads, including `(1)` duplicates, before running the notebook; overlapping lookback snapshots are rejected to prevent double counting.

The notebook reads pre-landed files; it does **not** acquire exports. Manual upload is supported. A scheduled Power Automate flow or other landing pipeline is an architecture option, but this repository does not include a companion flow.

The validated raw contracts are:

- **Environment (daily):** `BillingPlan Id`, `BillingPlan Name`, `Environment Id`, `Environment Name`, `Capacity Type`, `Entitled Quantity`, `Prepaid Consumed Quantity`, `Pay as you go Consumed Quantity`, `Usage Date`
- **Agent (lookback aggregate):** `Agent Name`, `Agent Id`, `Product`, `AI Feature/Billable Feature`, `Billed credit`, `Non-billed credit`, `Channel`, `Knowledge Sources`, `Tool Used`, `LLM Model`, `Scenario Name`, `Environment Id`, `Environment Name`
- **User (lookback aggregate):** `User Id`, `User Email`, `Agent Id`, `Agent Name`, `Billable credit used`, `Credits used`, `M365 Copilot Licensed`

Credit quantities are decimals (for example, `113.89` and `150.94`), and `Agent Id` is a bare GUID—not a `P_`-prefixed value. The environment report has daily `Usage Date` rows; agent and user reports have no activity date and represent the entire selected lookback. `User Email` may be blank and must be retained as unmatched identity. The separate **M365 Copilot Credits report** is limited to metered declarative agents in M365 Copilot Chat and is not the recommended ESS source.

> 💡 **Fabricated validation files:** [`SampleData`](./SampleData/) includes schema-identical Environment, Agent, and User PPAC files that reconcile to **1,651.75 credits**. Upload exactly those three consumption files to `Files/credit_consumption` to validate the credit notebook without customer data.

---

## Step 3 — Run (or schedule) the notebooks

1. **Run all cells** in `Copilot_Agent_Transcript_Parser.ipynb` first — it populates `agent_sessions` and `agent_catalogue`.
2. After landing the three CSVs under `Files/credit_consumption`, **run all cells** in `Copilot_Credit_Consumption_Ingester.ipynb`. It populates `dbo.credit_consumption_tenant`, `dbo.credit_consumption_agent`, and `dbo.credit_consumption_user`.
3. Confirm `agent_sessions`, `agent_catalogue`, and all three `credit_consumption_*` Delta tables appear under your Lakehouse's **Tables** list.
4. *(Recommended for production)* Schedule the notebooks (or wrap them in a Fabric pipeline). If credits must be hands-off, separately implement and schedule the PPAC-export landing step before the credit notebook.

> ⚠️ **Rolling snapshots are not transactions.** The agent and user reports overlap when the same lookback is downloaded repeatedly. Use the default `overwrite` mode for a current snapshot. If you intentionally use `append`, `LoadDate` is snapshot-history metadata; measures must select/deduplicate snapshots and must not sum overlapping windows as transaction history.

> 💡 **Scoped to the ESS agent by default.** `Copilot_Agent_Transcript_Parser.ipynb` already includes a filter cell that scopes ingestion to agents whose schema contains `copilotforemployeeselfservice`. Comment out that one filter cell if you want it to ingest **any** Copilot Studio agent's transcripts instead of just ESS — no other changes needed.

> 💡 **Automatic topic identification.** `Copilot_Agent_Transcript_Parser.ipynb` also classifies every conversation by topic as part of the same run — there's no separate script or extra step. It works in two stages: **Stage 1** matches each conversation's first message against a built-in list of common topics (HR, IT, Facilities, Finance, Travel, and more). **Stage 2** automatically groups anything Stage 1 couldn't match with similar unmatched conversations and labels the group `Auto-Discovered: <terms>`, so it's clearly distinguishable from the built-in topics. Results land in the `primary_topic_derived` field, which already powers the dashboard's topic visuals with no extra configuration. Advanced users can disable Stage 2 via the `ENABLE_SEMANTIC_FALLBACK` toggle inside the notebook. This capability is specific to the Fabric path — the CSV and Dataverse Direct templates still use only the built-in keyword system.

---

## Step 4 — Open the template and connect it to your Lakehouse

1. Double-click `ESS - Fabric V2.pbit` — it opens in Power BI Desktop.
2. When prompted, point the connection at your Lakehouse's **SQL analytics endpoint**. The supplied template uses **Import mode**; it does not provide selectable Direct Lake or DirectQuery behavior.
3. **Home → Refresh** to import the Lakehouse tables and confirm they load without errors.

> 💡 **Optional auxiliary tables:** `copilot_org_data`, `copilot_licensed_users`, and `copilot_interactions_parsed` are not produced by the two included notebooks. Fabric V2 treats them as typed-empty optional sources so refresh still succeeds. Populate them only through a separately implemented and validated Lakehouse ingestion process; this repository doesn't provide a local Org Data file parameter or those ingestion artifacts.

---

## ⚠️ Validation status — read before production use

`ESS - Fabric V2.pbit` has been **structurally validated offline** — package integrity, encoding, and schema all check out. Its refresh behavior against a real, live Fabric workspace and Lakehouse **has not yet been confirmed**. Before relying on it in production:

- [ ] Run the full ingestion → Lakehouse → refresh loop once, end to end, against your real environment(s).
- [ ] Confirm row counts in `agent_sessions`, `agent_catalogue`, `credit_consumption_tenant`, `credit_consumption_agent`, and `credit_consumption_user` look right.
- [ ] Confirm decimal totals remain decimal and reconcile to the source exports; do not round credit quantities to integers.
- [ ] Confirm blank `User Email` rows remain present as unmatched identities.
- [ ] Validate the dashboard the same way described in [Step 6 of the CSV guide](SETUP-CSV-Download.md#step-6--validate-before-sharing) or [Step 7 of the Dataverse guide](SETUP-Dataverse.md#step-7--validate-before-sharing).

### Observed versus modeled attribution

PPAC credits are observed only at environment-day, agent-lookback, and user-agent-lookback grain. They can be linked to ESS by bare `Agent Id` and, for nonblank identities, normalized `User Email`; there is no conversation/session ID. Therefore any credit shown per resolved conversation, topic, or outcome is a **modeled allocation**, not observed billing.

A defensible model keeps each PPAC snapshot as the control total, retains blank-email credits in an unmatched bucket, then allocates a user-agent total only across in-scope resolved conversations using a documented weight (for example equal share, or proportional transcript diagnostic cost). Reconcile allocations back to each PPAC total, expose unmatched/unallocated amounts, and label all downstream conversation/topic/outcome figures as modeled.

---

## Attribution & license

This path adapts the community, MIT-licensed **[StudioLens-for-Copilot-Studio](https://github.com/Keithland89/StudioLens-for-Copilot-Studio)** project by **Keithland89**, which contributes the pattern used here for Fabric/Lakehouse ingestion via notebooks — parsing Copilot Studio transcript and credit-consumption data into Delta tables. The original project's MIT license is preserved and referenced in both notebooks; see the source repository for the full license text.

---

## Need more help?

- 🐛 [Open an issue](https://github.com/microsoft/ESS/issues)
- 📘 Not sure this is the right path? See [Choose your path ↗](README.md#quick-start--choose-your-path)
- 📖 The **Metric Glossary** page (inside the dashboard) has every measure's definition
