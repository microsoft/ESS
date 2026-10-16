# Employee Self-Service Adoption Intelligence

Use this Power BI solution to understand adoption, conversation outcomes, employee feedback, topics, business impact, and improvement opportunities for Microsoft Copilot Studio Employee Self-Service agents.

![Animated preview of the ESS Adoption Intelligence dashboard](./images/dashboard-preview.gif)

Preview resources:

- [Short ESS Insights overview video](https://github.com/user-attachments/assets/efa683f8-edec-4a53-897b-8e02fc112f3f)
- [ESS Insights Dashboard - Interpretation Guide](./ESS%20Insights%20Dashboard%20-%20Interpretation%20Guide.pptx)
- [Topic to Time Savings companion deck](./Topic%20to%20Time%20Savings.pptx)

## Start here

Complete these steps in order:

1. **Preview the result.** Open the included synthetic [`ESS Dashboard - DEMO PBIX.pbix`](./ESS%20Dashboard%20-%20DEMO%20PBIX.pbix), or review the dashboard pages below. This preview reflects the CSV and Dataverse report layout; Fabric V2 uses its own advanced Studio/Lakehouse layout.
2. **Download the complete package.** Select [Download ZIP](https://github.com/microsoft/ESS/archive/refs/heads/main.zip), extract it, and keep the folder structure intact.
3. **Choose one data path.** Use the three choices below. Do not combine setup steps from different paths.
4. **Confirm transcript capture.** Before collecting data, complete the [environment and transcript-settings preflight](#before-collecting-data). The settings affect future conversations only.
5. **Build the minimum transcript-only report.** Confirm that it works before adding organization data, credits, feedback, or custom topics.
6. **Add optional data one source at a time.** Refresh after each addition so any issue is easy to isolate.
7. **Publish only after Desktop validation succeeds.**

> [!IMPORTANT]
> Download the complete ZIP rather than individual templates, scripts, or notebooks. The included files were tested together.

## Choose your data path

| Path | Best for | First setup | Refresh model | Start |
|---|---|---:|---|---|
| **Dataverse Direct - Recommended** | Ongoing reporting from one supported Dataverse environment | 15-25 min | Live cloud connection; gateway-free Service refresh | **[Open the Dataverse guide](./SETUP-Dataverse.md)** |
| **CSV Upload** | Evaluation, snapshots, offline copies, or controlled sharing | 20-30 min | Export a new CSV and refresh | **[Open the CSV guide](./SETUP-CSV-Download.md)** |
| **Fabric - Advanced** | Multiple environments, durable Lakehouse history, or large-scale ingestion | 45-90 min | Scheduled notebooks plus Power BI refresh | **[Open the Fabric guide](./SETUP-Fabric.md)** |

### 1. [Dataverse Direct - Recommended](./SETUP-Dataverse.md)

Choose this path when the report will use one Production, Sandbox, or Default Dataverse environment. The included launcher creates a validated Desktop template for that environment; after validation, a second launcher creates the cloud-only Service-refresh template.

**Required access:** Bot Transcript Viewer, or a custom Dataverse role with organization-level Read on `conversationtranscript`. Environment Maker alone is not enough.

**Included files:** `ESS Dashboard - Dynamic Topics (Dataverse) V21.pbit`, `START-HERE-DATAVERSE.cmd`, and `BUILD-SERVICE-REFRESH.cmd`.

**[Follow the Dataverse Direct steps ->](./SETUP-Dataverse.md)**

### 2. [CSV Upload](./SETUP-CSV-Download.md)

Choose this path for a one-time snapshot, a proof of concept, or a report that must be distributed without a live Dataverse connection. Export the transcript table, build a small agent registry, and open the included CSV template.

**Required access:** Bot Transcript Viewer, or a custom Dataverse role with organization-level Read on `conversationtranscript`.

**Included files:** `ESS Dashboard - Dynamic Topics (CSV) V18.pbit` and `tools\agent_registry.py`.

**[Follow the CSV Upload steps ->](./SETUP-CSV-Download.md)**

### 3. [Fabric - Advanced](./SETUP-Fabric.md)

Choose this path only when you need multiple environments, independently governed history beyond the Dataverse retention window, or Lakehouse-based ingestion at scale. An administrator must configure an Entra application and a Dataverse Application User in every source environment.

**Required access:** Fabric workspace Contributor, Member, or Admin; an Entra app registration; and a Dataverse Application User with organization-level Read on `conversationtranscript`.

**Included files:** `ESS - Fabric V2.pbit`, `Copilot_Agent_Transcript_Parser.ipynb`, and the optional credit-ingestion notebook.

**Report experience:** Fabric V2 uses Studio pages for topic exploration, conversation quality, performance, errors, feedback, knowledge files, value, and credit consumption. It does not use the CSV/Dataverse layout shown in the demo PBIX.

**[Follow the Fabric steps ->](./SETUP-Fabric.md)**

## What is required for the first successful report?

Each path guide shows the portal, exact click path, required role, expected output, and included helper beside the action that needs it.

| Path | Required input | Required role | Template and helper | Success checkpoint |
|---|---|---|---|---|
| **Dataverse Direct** | Dataverse Environment URL | Bot Transcript Viewer or custom organization-level transcript Read | Dataverse V21 plus `START-HERE-DATAVERSE.cmd` | Total Conversations is non-zero |
| **CSV Upload** | Untouched `ConversationTranscript` CSV and validated `agent-registry.json` | Bot Transcript Viewer or custom organization-level transcript Read | CSV V18 plus `tools\agent_registry.py` | Total Conversations is non-zero and the intended agent is shown |
| **Fabric** | Dataverse URL, application credentials, and `agent-registry.csv` | Fabric Contributor+; Entra/Power Platform admin help; Application User with transcript Read | Fabric V2 plus transcript-parser notebook | Eight transcript tables exist and Total Conversations is non-zero |

Power BI Desktop is required for all three paths. Python 3.10 or later is required for the guided Dataverse setup, the CSV registry, and the optional local preparation tools; the included Python tools use only the standard library.

## Add optional data only after the baseline works

| Enhancement | What it adds | Where to retrieve it | Required role | Included helper or guide |
|---|---|---|---|---|
| **Users / organization** | Department, country, job title, display name | Microsoft 365 admin center: **Users -> Active users -> Export users**, or an approved HR/Viva Insights/Graph source | Global Reader, User Administrator, or Global Administrator for the Microsoft 365 export; other sources use their own access model | CSV and Dataverse Desktop accept `OrgData.csv`; Fabric requires a customer-built Lakehouse ingestion |
| **Copilot Credits** | Observed tenant, agent, and user credit consumption | Power Platform admin center: **Licensing -> Copilot Studio -> Summary -> Download report** | Power Platform Administrator is recommended least privilege; tenant administrator or Dynamics 365 Administrator also works | CSV/Dataverse Desktop use the User-Level file; Fabric uses all three files and `Copilot_Credit_Consumption_Ingester.ipynb` |
| **External Product Feedback** | Microsoft 365 Copilot Chat and exported Monitor reactions beyond the reactions already found in transcripts | Microsoft 365 admin center: **Health -> Product feedback -> Export to CSV** | A Microsoft 365 administrator or reader with Product Feedback access; Compliance Administrator or Global Administrator only when identity details or deletion are required | [`tools\ess_feedback_normalizer.py`](./FEEDBACK-INGESTION.md) |
| **Customer-specific topics** | Reviewed local topic rules without changing the template | Learn from the customer's native Copilot Studio topic evidence | Transcript read access; no additional cloud role | [`tools\ess_topic_tuner.py`](./TOPIC-TUNER.md) |
| **Power BI publication** | Shared report and scheduled refresh | Power BI Desktop: **Home -> Publish** | Workspace Contributor, Member, or Admin plus the applicable Power BI license | [Refresh and publication guide](./AUTO-REFRESH.md) |

## Approved release files

The downloadable ZIP contains these current report artifacts:

| File | Use |
|---|---|
| [`ESS Dashboard - Dynamic Topics (Dataverse) V21.pbit`](./ESS%20Dashboard%20-%20Dynamic%20Topics%20%28Dataverse%29%20V21.pbit) | Base input used by the two Dataverse launchers |
| [`ESS Dashboard - Dynamic Topics (CSV) V18.pbit`](./ESS%20Dashboard%20-%20Dynamic%20Topics%20%28CSV%29%20V18.pbit) | CSV Upload template |
| [`ESS - Fabric V2.pbit`](./ESS%20-%20Fabric%20V2.pbit) | Fabric/Lakehouse template |
| [`ESS Dashboard - DEMO PBIX.pbix`](./ESS%20Dashboard%20-%20DEMO%20PBIX.pbix) | Synthetic demonstration report; not a customer template |

Older Dataverse template backups are not included in the release.

## Before collecting data

<details>
<summary><strong>Confirm the environment and transcript settings</strong></summary>

### Supported environment types

| Environment type | Transcripts written to Dataverse? | Supported for customer reporting? |
|---|---|---|
| Production | Yes | Yes |
| Sandbox | Yes | Yes |
| Default | Yes | Yes |
| Developer | Only the maker's conversations | Demo only |
| Microsoft Teams environment | No | No |
| Microsoft 365 Copilot environment | No | No |

Check the type in the [Power Platform admin center](https://admin.powerplatform.microsoft.com): **Environments -> select the environment**.

### Enable the required transcript settings

1. Open the agent in [Copilot Studio](https://copilotstudio.microsoft.com).
2. Select **Settings -> Advanced -> Conversation transcripts**.
3. Turn on **Save conversation transcripts to Dataverse**.
4. Turn on **Include node-level details in transcripts**.
5. Save and publish the agent.
6. Run several new test conversations and allow a few minutes for the records to appear.

These settings affect future conversations only. Node-level details are required for topic, turn, duration, outcome, and parent/child-agent analysis.

### Plan the retention window

Dataverse commonly deletes conversation transcripts after 30 days through a recurring bulk-delete job. A longer report lookback does not restore deleted records.

To change retention, use the agent's **Settings -> Advanced -> Conversation transcripts** setting when available. A System Administrator can also review the environment's recurring job under **Settings -> Data management -> Bulk record deletion**.

[Microsoft Learn: manage conversation transcripts](https://learn.microsoft.com/en-us/microsoft-copilot-studio/analytics-transcripts-powerapps)

</details>

## What the CSV and Dataverse dashboard answers

| Page | Question answered |
|---|---|
| Executive Summary | What are the top adoption, outcome, quality, productivity, and value signals? |
| Conversation Outcomes | Which conversations resolve, escalate, or end without resolution? |
| Adoption | Who uses the agent, how often, and from which organizations? |
| Time to Knowledge | How long and how many turns does it take to help an employee? |
| Conversation Details | What happened in an individual conversation? |
| Business Impact | What ticket deflection, time savings, value, and credit consumption are modeled? |
| Improvement Opportunities | Which topics and child agents need authoring attention? |
| Agent Feedback | What do users like or dislike? |
| Adjust Topic Assumptions | Which time-saved assumptions should be reviewed for each topic? |
| Glossary | How is every metric defined and sourced? |

All CSV and Dataverse pages work from transcript data. Optional sources enrich specific visuals; they are not required to prove the baseline report. Fabric V2 presents the same source domains through its separate Studio/Lakehouse page set.

## Topic classification and privacy

- Copilot Studio's native topic remains authoritative when present.
- Conversations without a native topic use the shared English, Spanish, and Chinese taxonomy in `taxonomy/topics-taxonomy.csv`.
- Matching is conservative: complete words or phrases, scoring, exclusions, confidence, and ambiguity handling prevent weak matches from becoming business labels.
- The optional private tuner learns only from local transcript evidence and emits reviewed rule files without exporting full prompts.
- Classification runs locally in Power Query or inside the customer's Fabric workspace. No transcript text is sent to an external classification service.

See [Private adaptive topic tuning](./TOPIC-TUNER.md) for the optional post-validation workflow.

## Synthetic validation data

The [`SampleData`](./SampleData/) folder contains fabricated `example.com` users and synthetic identifiers. It is safe for demonstrations and validates the same contracts used by the templates.

| Sample | Purpose |
|---|---|
| `ConversationTranscripts.csv` | 168 fabricated conversations |
| `OrgData.csv` | Matching organization attributes |
| `agent-registry.csv` / `agent-registry.json` | Cross-source agent aliases |
| `feedback-events.csv` / `feedback-events.json` | Prepared cross-channel feedback |
| Three `*MCSMessages*` CSVs | Environment, agent, and user Copilot Credits contracts |

The synthetic credit files reconcile to **1,651.75 total credits**. CSV V18 and Dataverse V21 Desktop use the User-Level file; Fabric V2 uses all three.

## Help and reference

- [Agent registry and reporting scope](./AGENT-REGISTRY.md)
- [Cross-channel feedback ingestion](./FEEDBACK-INGESTION.md)
- [Private adaptive topic tuning](./TOPIC-TUNER.md)
- [Parent and child agent attribution](./CHILD-AGENT-ATTRIBUTION.md)
- [Automatic refresh and publication](./AUTO-REFRESH.md)
- [Open a GitHub issue](https://github.com/microsoft/ESS/issues)

## License

[MIT](./LICENSE)
