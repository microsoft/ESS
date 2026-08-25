# Step-by-Step Setup Guide — Fabric

> ⚠️ **Read this first.** If you have a single Dataverse environment and just need scheduled refresh, use **[Dataverse Direct](SETUP-Dataverse.md)** + **[AUTO-REFRESH.md](AUTO-REFRESH.md)** instead — it's simpler and requires no Fabric capacity.

This path adds a **Fabric/Lakehouse ingestion layer** in front of the same ESS Insights dashboard, for teams that have outgrown the CSV Upload and Dataverse Direct paths. It is **not** a replacement for either — most customers should keep using whichever of those two they're already on.

---

## Is this path right for you?

Use this path only if at least one of these is true:

- [ ] **Multiple Dataverse environments.** You want conversations from two or more Dataverse environments (e.g. regional or business-unit agents) consolidated into a single dashboard, instead of maintaining one `.pbit` copy per environment.
- [ ] **Refresh performance at scale.** Per-refresh live Dataverse queries against a very large environment (long history, high conversation volume) are slow or timing out with Dataverse Direct.
- [ ] **Built-in credit-consumption analytics.** You want Copilot credit/message-consumption data ingested and available alongside conversation data automatically, without a manual Message Consumption export every refresh cycle.

If none of these apply, use **[Dataverse Direct](SETUP-Dataverse.md)** or **[CSV Upload](SETUP-CSV-Download.md)** instead — they get you running faster with no Fabric capacity required.

---

## Benefits of this path

- **Automatic scheduled refresh.** Once the ingestion notebooks are scheduled (see Step 3), the Lakehouse — and the dashboard connected to it — stays current on its own, with no manual re-export or re-import step to repeat.
- **Multiple Dataverse environments, one dashboard.** Conversations from two or more Dataverse environments can be ingested into the same Lakehouse and consolidated into a single dashboard, instead of maintaining a separate `.pbit` copy per environment.
- **Built-in Copilot credit-consumption analytics.** `Copilot_Credit_Consumption_Ingester.ipynb` ingests Copilot credit and message-consumption data automatically, without a manual Message Consumption export every refresh cycle.
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
| `ESS - Fabric V1.pbit` | The dashboard template — same report, pointed at your Lakehouse instead of a CSV file or a live Dataverse connection |
| `Copilot_Agent_Transcript_Parser.ipynb` | Notebook that parses conversation transcripts into the `agent_sessions` and `agent_catalogue` Delta tables |
| `Copilot_Credit_Consumption_Ingester.ipynb` | Notebook that ingests credit/message-consumption data into the `agent_performance` Delta table |

> Both notebooks are adapted from the community, MIT-licensed **[StudioLens-for-Copilot-Studio](https://github.com/Keithland89/StudioLens-for-Copilot-Studio)** project by **Keithland89** — see [Attribution & license ↓](#attribution--license).

---

## Step 2 — Land the notebooks in your Fabric workspace

1. In your Fabric workspace, import both `Copilot_Agent_Transcript_Parser.ipynb` and `Copilot_Credit_Consumption_Ingester.ipynb` (**New → Import notebook**).
2. Attach each notebook to your **Lakehouse** (**Add lakehouse** in the notebook's Explorer pane).
3. Update the source-connection cells in each notebook to point at your Dataverse environment(s) — repeat the transcript parser once per environment if you're consolidating more than one.

> 💡 **Fill in the CONFIG cell.** `Copilot_Agent_Transcript_Parser.ipynb`'s CONFIG cell needs `TENANT_ID`, `CLIENT_ID`, and `CLIENT_SECRET` filled in for the app registration from the checklist above. For production, use `notebookutils.credentials.getSecret('<kv-uri>', '<secret-name>')` instead of a literal secret value in the notebook.

---

## Step 3 — Run (or schedule) the notebooks

1. **Run all cells** in `Copilot_Agent_Transcript_Parser.ipynb` first — it populates `agent_sessions` and `agent_catalogue`.
2. **Run all cells** in `Copilot_Credit_Consumption_Ingester.ipynb` — it populates `agent_performance`.
3. Confirm all three Delta tables appear under your Lakehouse's **Tables** list with rows in them.
4. *(Recommended for production)* Schedule both notebooks (or wrap them in a Fabric pipeline) to re-run on a cadence, so the Lakehouse stays current without manual runs.

> 💡 **Scoped to the ESS agent by default.** `Copilot_Agent_Transcript_Parser.ipynb` already includes a filter cell that scopes ingestion to agents whose schema contains `copilotforemployeeselfservice`. Comment out that one filter cell if you want it to ingest **any** Copilot Studio agent's transcripts instead of just ESS — no other changes needed.

> 💡 **Automatic topic identification.** `Copilot_Agent_Transcript_Parser.ipynb` also classifies every conversation by topic as part of the same run — there's no separate script or extra step. It works in two stages: **Stage 1** matches each conversation's first message against a built-in list of common topics (HR, IT, Facilities, Finance, Travel, and more). **Stage 2** automatically groups anything Stage 1 couldn't match with similar unmatched conversations and labels the group `Auto-Discovered: <terms>`, so it's clearly distinguishable from the built-in topics. Results land in the `primary_topic_derived` field, which already powers the dashboard's topic visuals with no extra configuration. Advanced users can disable Stage 2 via the `ENABLE_SEMANTIC_FALLBACK` toggle inside the notebook. This capability is specific to the Fabric path — the CSV and Dataverse Direct templates still use only the built-in keyword system.

---

## Step 4 — Open the template and connect it to your Lakehouse

1. Double-click `ESS - Fabric V1.pbit` — it opens in Power BI Desktop.
2. When prompted, point the connection at your Lakehouse — either its **SQL analytics endpoint** (Import or DirectQuery) or **Direct Lake**, depending on which mode you want to run in.
3. **Home → Refresh** (or Direct Lake's automatic sync) to confirm all three tables load without errors.

> 💡 **Org Data works the same as the other paths.** This template's Org Data table uses the same JobTitle/Country/DisplayName auto-detection as the CSV Upload and Dataverse Direct templates, and accepts the same common export column-naming variants. It's still a separate, manual roster file — it isn't produced by either notebook above. See [SETUP-Dataverse.md](SETUP-Dataverse.md) (Step 2) for where to get it.

---

## ⚠️ Validation status — read before production use

`ESS - Fabric V1.pbit` has been **structurally validated offline** — package integrity, encoding, and schema all check out. Its refresh behavior against a real, live Fabric workspace and Lakehouse **has not yet been confirmed**. Before relying on it in production:

- [ ] Run the full ingestion → Lakehouse → refresh loop once, end to end, against your real environment(s).
- [ ] Confirm row counts in `agent_sessions`, `agent_catalogue`, and `agent_performance` look right.
- [ ] Validate the dashboard the same way described in [Step 6 of the CSV guide](SETUP-CSV-Download.md#step-6--validate-before-sharing) or [Step 7 of the Dataverse guide](SETUP-Dataverse.md#step-7--validate-before-sharing).

---

## Attribution & license

This path adapts the community, MIT-licensed **[StudioLens-for-Copilot-Studio](https://github.com/Keithland89/StudioLens-for-Copilot-Studio)** project by **Keithland89**, which contributes the pattern used here for Fabric/Lakehouse ingestion via notebooks — parsing Copilot Studio transcript and credit-consumption data into Delta tables. The original project's MIT license is preserved and referenced in both notebooks; see the source repository for the full license text.

---

## Need more help?

- 🐛 [Open an issue](https://github.com/microsoft/ESS/issues)
- 📘 Not sure this is the right path? See [Choose your path ↗](README.md#quick-start--choose-your-path)
- 📖 The **Metric Glossary** page (inside the dashboard) has every measure's definition
