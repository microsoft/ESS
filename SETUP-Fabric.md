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
- **Copilot credit-consumption analytics.** `Copilot_Credit_Consumption_Ingester.ipynb` reads the three Power Platform admin center Copilot Credits reports after they are landed under `Files/credit_consumption`.
- **Automatic multilingual topic identification for conversations without a native topic.** `Copilot_Agent_Transcript_Parser.ipynb` preserves Copilot Studio topics, then applies a shared English, Spanish, and Chinese taxonomy and a local discovery fallback. No conversation data leaves the customer's Fabric workspace, and no LLM or external API call is involved. (See Step 3 below for how it works.)

---

## Before you start

✅ A **Fabric workspace** with Fabric capacity assigned (a trial capacity is enough to evaluate)
✅ A **Lakehouse** created in that workspace
✅ Permission to **create and run notebooks** in that workspace
✅ A **Microsoft Entra app registration** added as a Dataverse **Application User** (with read access on Conversation Transcript) in every Dataverse environment you're ingesting from — this typically needs a Dataverse or Entra administrator to set up; it's a different, additional requirement from the CSV/Dataverse-Direct paths' simpler Bot Transcript Viewer role
✅ **Power BI Desktop** installed — [download free](https://powerbi.microsoft.com/desktop/)
✅ **Python 3.10 or later** installed locally — used to validate the agent registry and optionally prepare feedback/topic files; no packages are required

---

## One-time administrator setup — create the Dataverse application user

Ask an Entra and Power Platform administrator to complete these steps. Reuse one app registration across the Dataverse environments, but add it as an application user in every environment.

### Create the Microsoft Entra app registration

1. Sign in to the [Microsoft Entra admin center](https://entra.microsoft.com).
2. Select **Identity → Applications → App registrations → New registration**.
3. Enter a customer-approved name such as `ESS Fabric Transcript Reader`.
4. Keep **Accounts in this organizational directory only** selected and leave Redirect URI blank.
5. Select **Register**.
6. On **Overview**, copy:
   - **Application (client) ID** — this becomes `CLIENT_ID`;
   - **Directory (tenant) ID** — this becomes `TENANT_ID`.
7. Select **Certificates & secrets → Client secrets → New client secret**.
8. Enter a description and the shortest approved expiration, then select **Add**.
9. Immediately copy the secret **Value** — not the Secret ID. It is displayed only once.

> Store the secret in an approved secret store. Do not commit it to this repository, leave it in a shared notebook, paste it into screenshots, or send it by email or chat. For production, use Azure Key Vault and `notebookutils.credentials.getSecret(...)`.

### Add the app to each Dataverse environment

1. Sign in to the [Power Platform admin center](https://admin.powerplatform.microsoft.com).
2. Select **Environments**, then select the environment that hosts the agent.
3. Select **Settings → Users + permissions → Application users**.
4. Select **New app user → Add an app**.
5. Select the app registration created above, then select **Add**.
6. Choose the environment's business unit.
7. Under **Security roles**, select **Bot Transcript Viewer** or a customer-approved custom role with organization-level **Read** access to the `conversationtranscript` table.
8. Select **Create**.
9. Repeat these steps for every environment listed in `DATAVERSE_URLS`.

Application permissions can take a few minutes to become active.

---

## Step 1 — Get the template and notebooks

You'll need three files:

| File | What it does |
|---|---|
| `ESS - Fabric V2.pbit` | The dashboard template — imports the Lakehouse SQL analytics endpoint and preserves decimal Copilot Credits |
| `Copilot_Agent_Transcript_Parser.ipynb` | Notebook that parses conversation transcripts into the `agent_sessions` and `agent_catalogue` Delta tables |
| `Copilot_Credit_Consumption_Ingester.ipynb` | Optional notebook that ingests Power Platform admin center reports into `credit_consumption_tenant`, `credit_consumption_agent`, and `credit_consumption_user` |

> Both notebooks are adapted from the community, MIT-licensed **[StudioLens-for-Copilot-Studio](https://github.com/Keithland89/StudioLens-for-Copilot-Studio)** project by **Keithland89** — see [Attribution & license ↓](#attribution--license).

---

## Step 2 — Land the notebooks in your Fabric workspace

1. In your Fabric workspace, import both `Copilot_Agent_Transcript_Parser.ipynb` and `Copilot_Credit_Consumption_Ingester.ipynb` (**New → Import notebook**).
2. Attach each notebook to your **Lakehouse** (**Add lakehouse** in the notebook's Explorer pane).
3. Open `Copilot_Agent_Transcript_Parser.ipynb` and find the **CONFIG** cell near the top.
4. For one environment, set `DATAVERSE_URL` and leave `DATAVERSE_URLS = []`. For several environments, populate `DATAVERSE_URLS` and leave the single URL unused. Use each environment's **Instance URL** from Power Apps **Settings → Session details**, without a trailing slash.
5. Set `TENANT_ID`, `CLIENT_ID`, and `CLIENT_SECRET` from the administrator setup above. For production, replace the literal secret with `notebookutils.credentials.getSecret(...)`.
6. Leave `LOOKBACK_DAYS = 7` and `WRITE_MODE = 'merge'` for safe incremental refresh. Use `LOOKBACK_DAYS = 0` with `WRITE_MODE = 'overwrite'` only for an intentional full replacement.

Create and validate the [agent registry](AGENT-REGISTRY.md), then upload `agent-registry.csv` to `Files/config/agent-registry.csv`. Set the same `AGENT_SCOPE_MODE` in both notebooks:

- `ESS Safe` — enabled registry agents marked `IsEss=true` (default);
- `Selected Agents` — enabled registry agents marked `Selected=true`;
- `All Agents` — all transcript/credit agents, while Product Feedback still requires a registry match.

To add customer-specific topics without editing the notebook, run the [Private topic tuner](TOPIC-TUNER.md), review and enable the approved rules, then upload `customer-topic-overrides.csv` to `Files/config/customer-topic-overrides.csv`. The notebook uses only enabled rows and continues with the built-in taxonomy when the file is absent.

To include Microsoft 365 Copilot Chat or exported Monitor reactions, follow [Cross-channel feedback ingestion](FEEDBACK-INGESTION.md), then upload `feedback-events.csv` to `Files/feedback/feedback-events.csv`. The transcript parser writes mapped events to `user_feedback` and identifier-only unmapped rows to `user_feedback_quarantine`.

Parent/child attribution is built into the same transcript parser. With node-level transcript details enabled, conversation summaries land in `agent_sessions` and `agent_performance`, and every initialize/completed event lands in `agent_subagents`. See [Parent and child agent attribution](CHILD-AGENT-ATTRIBUTION.md).

> If the token check returns `invalid_client`, confirm that `CLIENT_SECRET` contains the secret **Value**, not the Secret ID, and that it has not expired.

### Land the three Copilot Credits exports

1. In the [Power Platform admin center](https://admin.powerplatform.microsoft.com), go to **Licensing → Copilot Studio → Summary → Download report**. This page allows a tenant administrator, Power Platform Administrator, or Dynamics 365 Administrator; use **Power Platform Administrator** as least privilege for this workflow.
2. Set **Usage type** to `Copilot Credits`, choose a `30`, `60`, `90`, or `180` day lookback, and download each type: **Environment Consumption Summary**, **Agent-Level Credit Consumption**, and **User-Level Credit Consumption**.
3. In the attached Lakehouse, create/open **Files → `credit_consumption`** and upload all three CSVs. At 30 days their generated names are:
   - `EntitlementConsumptionTenantDetailsReport_MCSMessages_30.csv`
   - `EntitlementConsumptionTenantPerAgentDetailsReport_MCSMessages_30.csv`
   - `EntitlementConsumptionTenantPerUserDetailsReport_MCSMessages_30.csv`

   Keep exactly one current file of each type in this folder. Move or delete older downloads, including `(1)` duplicates, before running the notebook; overlapping lookback snapshots are rejected to prevent double counting.

The notebook reads pre-landed files; it does **not** acquire exports. Manual upload is supported. A scheduled Power Automate flow or other landing pipeline is an architecture option, but this repository does not include a companion flow.

### Land Microsoft 365 Copilot feedback

1. Add the agent's `M365Title` (`T_...`) alias to `agent-registry.csv` by following the [agent registry guide](AGENT-REGISTRY.md).
2. In the [Microsoft 365 admin center](https://admin.microsoft.com), select **Health → Product feedback → Export to CSV**.
3. Follow [Microsoft 365 Copilot feedback: export, prepare, and load](FEEDBACK-INGESTION.md) to run the local normalizer with the registry.
4. Review `feedback-events.audit.json` and confirm the expected ESS rows were included. The export is tenant-wide; do not upload it directly to Fabric.
5. In the attached Lakehouse, create/open **Files → `feedback`** and upload the prepared `feedback-events.csv`.
6. Run `Copilot_Agent_Transcript_Parser.ipynb`. Confirm mapped rows appear in `user_feedback` and review identifier-only rows in `user_feedback_quarantine`.

The export is a snapshot rather than a live connection. Repeat the export, preparation, upload, and notebook run for each refresh, or implement an approved export-landing process separately.

The validated raw contracts are:

- **Environment (daily):** `BillingPlan Id`, `BillingPlan Name`, `Environment Id`, `Environment Name`, `Capacity Type`, `Entitled Quantity`, `Prepaid Consumed Quantity`, `Pay as you go Consumed Quantity`, `Usage Date`
- **Agent (lookback aggregate):** `Agent Name`, `Agent Id`, `Product`, `AI Feature/Billable Feature`, `Billed credit`, `Non-billed credit`, `Channel`, `Knowledge Sources`, `Tool Used`, `LLM Model`, `Scenario Name`, `Environment Id`, `Environment Name`
- **User (lookback aggregate):** `User Id`, `User Email`, `Agent Id`, `Agent Name`, `Billable credit used`, `Credits used`, `M365 Copilot Licensed`

Credit quantities are decimals (for example, `113.89` and `150.94`), and `Agent Id` is a bare GUID—not a `P_`-prefixed value. The environment report has daily `Usage Date` rows; agent and user reports have no activity date and represent the entire selected lookback. `User Email` may be blank and must be retained as unmatched identity. The separate **M365 Copilot Credits report** is limited to metered declarative agents in M365 Copilot Chat and is not the recommended ESS source.

> 💡 **Fabricated validation files:** [`SampleData`](./SampleData/) includes schema-identical Environment, Agent, and User Power Platform admin center files that reconcile to **1,651.75 credits**. Upload exactly those three consumption files to `Files/credit_consumption` to validate the credit notebook without customer data.

---

## Step 3 — Run (or schedule) the notebooks

1. **Run all cells** in `Copilot_Agent_Transcript_Parser.ipynb` first — it populates `agent_sessions` and `agent_catalogue`.
2. A successful run ends without a red error cell and prints row counts for each output. Refresh the Lakehouse Explorer and confirm these required tables exist: `agent_sessions`, `agent_turns`, `agent_errors`, `agent_subagents`, `agent_catalogue`, `agent_performance`, `user_feedback`, and `user_feedback_quarantine`.
3. After landing the three CSVs under `Files/credit_consumption`, **run all cells** in `Copilot_Credit_Consumption_Ingester.ipynb`. It populates `credit_consumption_tenant`, `credit_consumption_agent`, and `credit_consumption_user`.
4. Confirm `agent_sessions`, `agent_catalogue`, `user_feedback`, and all three `credit_consumption_*` Delta tables appear under your Lakehouse's **Tables** list.
5. *(Recommended for production)* Schedule the notebooks (or wrap them in a Fabric pipeline). If credits must be hands-off, separately implement and schedule the Power Platform admin center export-landing step before the credit notebook.

> ⚠️ **Rolling snapshots are not transactions.** The agent and user reports overlap when the same lookback is downloaded repeatedly. Use the default `overwrite` mode for a current snapshot. If you intentionally use `append`, `LoadDate` is snapshot-history metadata; measures must select/deduplicate snapshots and must not sum overlapping windows as transaction history.

> 💡 **Transcript history is protected by default.** The transcript parser uses `WRITE_MODE = 'merge'` for its bounded seven-day Dataverse pull. It rejects `overwrite` with a nonzero lookback because that combination would discard older Delta history. For an intentional full replacement, set both `LOOKBACK_DAYS = 0` and `WRITE_MODE = 'overwrite'`.

> 💡 **Native analytics signals are preserved.** `messageReaction.value.reaction` supplies transcript thumbs, and `SessionInfo.outcome`/`outcomeReason` remain authoritative. Conversations without `SessionInfo` are labeled `Engaged-Unclassified` rather than assumed resolved.

> 💡 **Safe and flexible agent scope.** Do not comment out notebook cells. Change `AGENT_SCOPE_MODE` and registry flags instead. The registry maps transcript, credit, and Microsoft 365 title IDs to one canonical agent identity and prevents unrelated tenant feedback from entering agent metrics.

> 💡 **Automatic topic identification.** `Copilot_Agent_Transcript_Parser.ipynb` classifies conversations as part of the same run. A native Copilot Studio topic remains authoritative. For rows without one, **Stage 1** uses the shared customer-neutral English, Spanish, and Chinese taxonomy with complete-word or phrase matching, scoring, exclusions, and ambiguity handling. **Stage 2** groups a sufficiently large set of remaining uncategorized prompts with multilingual character n-grams and labels each group `Auto-Discovered: <terms>`. Results land in `primary_topic_derived`; audit fields record the source, matched terms, score, confidence, ambiguity, language, and classifier version. Advanced users can disable Stage 2 via `ENABLE_SEMANTIC_FALLBACK`. Auto-discovered labels are candidate themes and should be reviewed before business use.

---

## Step 4 — Open the template and connect it to your Lakehouse

1. In the Fabric workspace, open the Lakehouse.
2. Open its **SQL analytics endpoint** and copy the **SQL connection string** from the endpoint settings. Also note the Lakehouse/database name.
3. Double-click `ESS - Fabric V2.pbit` to open it in Power BI Desktop.
4. Complete the parameter prompt:

   | Template parameter | Value |
   |---|---|
   | **Fabric SQL Endpoint** | The SQL connection string copied in Step 2 |
   | **Lakehouse Name** | The Lakehouse/database name |
   | **Enable_Dataverse** | `Include` |
   | **Enable_ProductFeedback** | `Include` when `user_feedback` is used; otherwise `Exclude` |
   | **Enable_Agent365** | `Include` only when the optional Agent 365 source table is supplied; otherwise `Exclude` |
   | **Enable_Consumption** | `Include` when the credit notebook was run; otherwise `Exclude` |
   | **Enable_CostConsumption** | `Include` only when cost-consumption inputs are supplied; otherwise `Exclude` |

5. When Power BI requests credentials, select **Organizational account**, sign in, and select **Connect**.
6. Select **Home → Refresh** and confirm the Lakehouse tables load without errors.

The supplied template uses Import mode. It does not provide selectable Direct Lake or DirectQuery behavior.

### Minimum successful first run

For the smallest working configuration:

1. Run only the transcript parser with a valid `agent-registry.csv`.
2. Confirm all eight required transcript outputs exist.
3. Open the PBIT and enter **Fabric SQL Endpoint** and **Lakehouse Name**.
4. Set **Enable_Dataverse** to `Include`.
5. Set Product Feedback, Agent 365, Consumption, and Cost Consumption to `Exclude`.
6. Refresh and confirm **Total Conversations** is non-zero.

Add optional feedback and credit inputs only after this first refresh succeeds.

> 💡 **Optional auxiliary tables:** `copilot_org_data`, `copilot_licensed_users`, and `copilot_interactions_parsed` are not produced by the two included notebooks. Fabric V2 treats them as typed-empty optional sources so refresh still succeeds. Populate them only through a separately implemented and validated Lakehouse ingestion process; this repository doesn't provide a local Org Data file parameter or those ingestion artifacts.

---

## Validation status — read before production use

`ESS - Fabric V2.pbit` and both notebooks have been validated end to end with fabricated data against a standard schema-less Fabric Lakehouse and Power BI Desktop. The transcript parser created all eight required outputs, including zero-row tables, and the credit ingester created the tenant, agent, and user credit tables while preserving decimal values. Power BI Service validation also completed successfully against the Lakehouse SQL analytics endpoint.

Optional auxiliary-table ingestion remains outside the two included notebooks. Before relying on a customer deployment in production:

- [ ] Run the ingestion → Lakehouse → refresh loop once against the customer's own environment(s).
- [ ] Confirm row counts in `agent_sessions`, `agent_catalogue`, `credit_consumption_tenant`, `credit_consumption_agent`, and `credit_consumption_user` look right.
- [ ] Confirm decimal totals remain decimal and reconcile to the source exports; do not round credit quantities to integers.
- [ ] Confirm blank `User Email` rows remain present as unmatched identities.
- [ ] If Product Feedback is used, reconcile `feedback-events.audit.json` to `user_feedback` and review `user_feedback_quarantine`.
- [ ] In Power BI Service, replace the default SQL connection with an explicit OAuth cloud connection before scheduling refresh.
- [ ] Validate the dashboard the same way described in [Step 6 of the CSV guide](SETUP-CSV-Download.md#step-6--validate-before-sharing) or [Step 7 of the Dataverse guide](SETUP-Dataverse.md#step-7--validate-before-sharing).

### Observed versus modeled attribution

Power Platform admin center credits are observed only at environment-day, agent-lookback, and user-agent-lookback grain. They can be linked to ESS by bare `Agent Id` and, for nonblank identities, normalized `User Email`; there is no conversation/session ID. Therefore any credit shown per resolved conversation, topic, or outcome is a **modeled allocation**, not observed billing.

A defensible model keeps each exported snapshot as the control total, retains blank-email credits in an unmatched bucket, then allocates a user-agent total only across in-scope resolved conversations using a documented weight (for example equal share, or proportional transcript diagnostic cost). Reconcile allocations back to each exported total, expose unmatched/unallocated amounts, and label all downstream conversation/topic/outcome figures as modeled.

---

## Attribution & license

This path adapts the community, MIT-licensed **[StudioLens-for-Copilot-Studio](https://github.com/Keithland89/StudioLens-for-Copilot-Studio)** project by **Keithland89**, which contributes the pattern used here for Fabric/Lakehouse ingestion via notebooks — parsing Copilot Studio transcript and credit-consumption data into Delta tables. The original project's MIT license is preserved and referenced in both notebooks; see the source repository for the full license text.

---

## Need more help?

- 🐛 [Open an issue](https://github.com/microsoft/ESS/issues)
- 📘 Not sure this is the right path? See [Choose your path ↗](README.md#quick-start--choose-your-path)
- 📖 The **Metric Glossary** page (inside the dashboard) has every measure's definition
