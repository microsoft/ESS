# Employee Self-Service Adoption Intelligence

Use this Power BI solution to understand adoption, conversation outcomes, employee feedback, topics, business impact, and improvement opportunities for Microsoft Copilot Studio Employee Self-Service agents.

![Animated preview of the ESS Adoption Intelligence dashboard](./images/dashboard-preview.gif)

Preview resources:

- [Short ESS Insights overview video](https://github.com/user-attachments/assets/efa683f8-edec-4a53-897b-8e02fc112f3f)
- [YouTube overview (1m 41s)](https://youtu.be/dQqgcUs9Ly4)
- [ESS Insights Dashboard - Interpretation Guide](./ESS%20Insights%20Dashboard%20-%20Interpretation%20Guide.pptx)
- [Topic to Time Savings companion deck](./Topic%20to%20Time%20Savings.pptx)

## Start here

Complete three actions:

1. **Download and choose one path.** Select [Download ZIP](https://github.com/microsoft/ESS/archive/refs/heads/main.zip), extract it, and choose Dataverse Direct, CSV Upload, or Fabric below.
2. **Validate the transcript-only baseline.** Follow only that path's guide and confirm the report works before adding other data.
3. **Enable the report areas you need.** Add their data one source at a time. For Dataverse, validate with `START-HERE-DATAVERSE.cmd`, but publish only the separate report created by `BUILD-SERVICE-REFRESH.cmd`.

> [!IMPORTANT]
> Download the complete ZIP rather than individual templates, scripts, or notebooks. The included files were tested together.
>
> The Dataverse guided setup creates two intentionally different artifacts. **Desktop Validation - DO NOT PUBLISH** can include local Organization and Credits files. **Power BI Service - PUBLISH THIS** excludes those local sources and is the only Dataverse artifact intended for scheduled Service refresh.

## Choose your data path

| Path | Best for | First setup | Refresh model | Start |
|---|---|---:|---|---|
| **Dataverse Direct - Recommended** | Ongoing reporting from one supported Dataverse environment | 15-25 min | Two-stage validation and publication; gateway-free Service refresh | **[Open the Dataverse guide](./SETUP-Dataverse.md)** |
| **CSV Upload** | Evaluation, snapshots, offline copies, or controlled sharing | 20-30 min | Export a new CSV and refresh | **[Open the CSV guide](./SETUP-CSV-Download.md)** |
| **Fabric - Advanced** | Multiple environments, durable Lakehouse history, or large-scale ingestion | 45-90 min | Scheduled notebooks plus Power BI refresh | **[Open the Fabric guide](./SETUP-Fabric.md)** |

### 1. [Dataverse Direct - Recommended](./SETUP-Dataverse.md)

Choose this path when the report will use one Production, Sandbox, or Default Dataverse environment. The only required template input is the Dataverse Environment URL; conversation data is read directly from Dataverse, not from an exported transcript CSV.

**Required access:** Bot Transcript Viewer, or a custom Dataverse role with organization-level Read on `conversationtranscript`. Environment Maker alone is not enough.

**Included setup:** the [Dataverse guide](./SETUP-Dataverse.md) walks through the Environment URL, a local Desktop validation build, and a separate Service publication build. Python prepares the templates; Power BI Service refreshes Dataverse directly and does not run Python.

When the report opens, wait until every prefilled parameter value is visible and stable before selecting **Load**.

**[Follow the Dataverse Direct steps ->](./SETUP-Dataverse.md)**

### 2. [CSV Upload](./SETUP-CSV-Download.md)

Choose this path for a one-time snapshot, a proof of concept, or a report that must be distributed without a live Dataverse connection. Export the transcript table, build a small agent registry, and open the included CSV template.

**Required access:** Bot Transcript Viewer, or a custom Dataverse role with organization-level Read on `conversationtranscript`.

**Included files:** [`ESS Dashboard - Dynamic Topics (CSV) V18.pbit`](./ESS%20Dashboard%20-%20Dynamic%20Topics%20%28CSV%29%20V18.pbit) and [`tools\agent_registry.py`](./tools/agent_registry.py).

**[Follow the CSV Upload steps ->](./SETUP-CSV-Download.md)**

### 3. [Fabric - Advanced](./SETUP-Fabric.md)

Choose this path only when you need multiple environments, independently governed history beyond the Dataverse retention window, or Lakehouse-based ingestion at scale. An administrator must configure an Entra application and a Dataverse Application User in every source environment.

**Required access:** Fabric workspace Contributor, Member, or Admin; an Entra app registration; and a Dataverse Application User with organization-level Read on `conversationtranscript`.

**Included files:** [`ESS - Fabric V2.pbit`](./ESS%20-%20Fabric%20V2.pbit), [`Copilot_Agent_Transcript_Parser.ipynb`](./Fabric/notebooks/Copilot_Agent_Transcript_Parser.ipynb), and the optional [`Copilot_Credit_Consumption_Ingester.ipynb`](./Fabric/notebooks/Copilot_Credit_Consumption_Ingester.ipynb).

**Report experience:** Fabric V2 uses Studio pages for topic exploration, conversation quality, performance, errors, feedback, knowledge files, value, and credit consumption. It does not use the CSV/Dataverse layout shown in the demo PBIX.

**[Follow the Fabric steps ->](./SETUP-Fabric.md)**

## What is required for the first successful report?

Each path guide shows the portal, exact click path, required role, expected output, and included helper beside the action that needs it.

| Path | Required input | Required role | Template and helper | Success checkpoint |
|---|---|---|---|---|
| **Dataverse Direct** | Dataverse Environment URL; no transcript CSV export | Bot Transcript Viewer or custom organization-level transcript Read | [Guided Dataverse setup](./SETUP-Dataverse.md) | Total Conversations is non-zero |
| **CSV Upload** | Untouched `ConversationTranscript` CSV and validated `agent-registry.json` | Bot Transcript Viewer or custom organization-level transcript Read | [CSV V18](./ESS%20Dashboard%20-%20Dynamic%20Topics%20%28CSV%29%20V18.pbit) plus [`tools\agent_registry.py`](./tools/agent_registry.py) | Total Conversations is non-zero and the intended agent is shown |
| **Fabric** | Dataverse URL, application credentials, and `agent-registry.csv` | Fabric Contributor+; Entra/Power Platform admin help; Application User with transcript Read | [Fabric V2](./ESS%20-%20Fabric%20V2.pbit) plus [transcript-parser notebook](./Fabric/notebooks/Copilot_Agent_Transcript_Parser.ipynb) | Eight transcript tables exist and Total Conversations is non-zero |

Power BI Desktop is required for all three paths. The guided setup and optional local tools validate their own prerequisites.

## Optional data for full report functionality

These inputs enable specific report areas; they are not required for the transcript-only baseline. Validate the baseline first to isolate access or source errors, then load the data needed for the report functionality you intend to use.

| Enhancement | What it adds | Where to retrieve it | Required role | Included helper or guide |
|---|---|---|---|---|
| **Users / organization** | Department, country, job title, display name | Microsoft 365 admin center: **Users -> Active users -> Export users**, or an approved HR/Viva Insights/Graph source | Global Reader, User Administrator, or Global Administrator for the Microsoft 365 export; other sources use their own access model | CSV and Dataverse Desktop accept `OrgData.csv`; Fabric requires a customer-built Lakehouse ingestion |
| **Copilot Credits** | Observed tenant, agent, and user credit consumption | Power Platform admin center: **Licensing -> Copilot Studio -> Summary -> Download report** | Power Platform Administrator is recommended least privilege; tenant administrator or Dynamics 365 Administrator also works | CSV/Dataverse Desktop use the User-Level file; Fabric uses all three files and [`Copilot_Credit_Consumption_Ingester.ipynb`](./Fabric/notebooks/Copilot_Credit_Consumption_Ingester.ipynb) |
| **External Product Feedback** | Microsoft 365 Copilot Chat and exported Monitor reactions beyond the reactions already found in transcripts | Microsoft 365 admin center: **Health -> Product feedback -> Export to CSV** | A Microsoft 365 administrator or reader with Product Feedback access; Compliance Administrator or Global Administrator only when identity details or deletion are required | Dataverse prepares raw exports in its guided setup; CSV/Fabric use the [feedback guide](./FEEDBACK-INGESTION.md) |
| **Customer-specific topics** | Better coverage for recurring customer language that native and built-in topics do not classify reliably | Learn from the customer's native Copilot Studio topic evidence | Transcript read access; no additional cloud role | Use the [optional topic tuner](./TOPIC-TUNER.md) only after reviewing when to use or skip it |

To share the report or schedule refresh, follow the [refresh and publication guide](./AUTO-REFRESH.md) after the intended data sources work in Desktop.

## Approved release files

The downloadable ZIP contains these current report artifacts:

| File | Use |
|---|---|
| [`ESS Dashboard - Dynamic Topics (Dataverse) V21.pbit`](./ESS%20Dashboard%20-%20Dynamic%20Topics%20%28Dataverse%29%20V21.pbit) | Approved Dataverse V21 report used by the guided setup |
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

See [Customer-specific topic tuning](./TOPIC-TUNER.md) for the optional post-validation workflow.

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
- [Customer-specific topic tuning](./TOPIC-TUNER.md)
- [Parent and child agent attribution](./CHILD-AGENT-ATTRIBUTION.md)
- [Automatic refresh and publication](./AUTO-REFRESH.md)
- [Open a GitHub issue](https://github.com/microsoft/ESS/issues)

## License

[MIT](./LICENSE)
