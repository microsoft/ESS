# Tune customer-specific topics (optional)

Use this optional workflow when meaningful customer terminology is repeatedly left as **Other / Uncategorized** or assigned to a topic that is too broad.

The tuner runs locally, proposes reusable topic rules, and creates a new validation report. It does not change native Copilot Studio topics or modify an existing report.

## Should you use the topic tuner?

| Use it when | Skip it when |
|---|---|
| The same meaningful customer terms are missed across several conversations. | Native Copilot Studio topics and the built-in ESS taxonomy already classify the conversations correctly. |
| You have representative conversations that can support or validate a rule. | The gap is isolated, ambiguous, or lacks enough evidence for a safe rule. |
| A customer can review and approve the proposed business labels. | The baseline report has an access, environment, retention, or loading problem. |

> [!IMPORTANT]
> Topic tuning is not required for the ESS report. Complete the [Dataverse baseline setup](SETUP-Dataverse.md#action-2---run-the-guided-setup-and-validate-the-report) first. Topic rules cannot repair missing permissions, an incorrect Environment URL, expired transcripts, or disabled transcript capture.

## Customer journey

| Step | Customer action | Result |
|---|---|---|
| 1 | [Confirm the baseline and prepare evidence](#step-1---confirm-the-baseline-and-prepare-evidence) | A working Dataverse report and representative conversations |
| 2 | [Export the conversations](#step-2---export-the-conversations) | A local `ConversationTranscript` CSV |
| 3 | [Run the topic tuner](#step-3---run-the-topic-tuner) | A `READY`, `REVIEW REQUIRED`, or `STOP` result |
| 4 | [Follow the result](#step-4---follow-the-result) | Approved rules embedded in a new validation template |
| 5 | [Validate the improvement](#step-5---validate-the-improvement) | Confirmed topic behavior in Power BI Desktop |
| 6 | [Publish only if needed](#step-6---publish-only-if-needed) | A separate Service-safe report for scheduled refresh |

## Before you start

You need:

- the [complete ESS package](https://github.com/microsoft/ESS/archive/refs/heads/main.zip), extracted with its folder structure intact;
- [Python 3.10 or later](https://www.python.org/downloads/windows/) with **Add Python to PATH** selected during installation;
- a successful [Dataverse V21 baseline](SETUP-Dataverse.md);
- permission to export `ConversationTranscript` from the same Dataverse environment; and
- a customer-controlled folder for the transcript export and review files.

No additional Python packages, PowerShell commands, LLM, or external classification service are required.

## Step 1 - Confirm the baseline and prepare evidence

1. Complete [Action 2 in the Dataverse setup guide](SETUP-Dataverse.md#action-2---run-the-guided-setup-and-validate-the-report).
2. Confirm that **Total Conversations** is non-zero and the expected agent appears in the Agent filter.
3. Identify recurring customer terms that are currently unclassified or classified too broadly.
4. Include several distinct conversations that demonstrate the intended meaning. For automatic learning, the default gate requires at least five distinct supporting conversations.
5. Use **Start over** between test conversations so each example is retained as a separate conversation.

Native Copilot Studio topic evidence is the safest source for automatic learning. Repeated terms without native topic evidence can still become review candidates, but the customer must provide and approve their meaning.

## Step 2 - Export the conversations

1. Sign in to [Power Apps](https://make.powerapps.com).
2. Select the same environment used by the Dataverse report.
3. Select **Tables -> All**.
4. Search for and open **ConversationTranscript**.
5. Select **Export -> Export data**.
6. When the export finishes, download and extract it.
7. Keep the CSV in a customer-controlled folder.

> [!WARNING]
> Do not open or save the transcript CSV in Excel. Excel can corrupt the JSON stored in its `Content` column.

The CSV is used only as local evidence for the tuner. Dataverse remains the report's conversation data source.

## Step 3 - Run the topic tuner

1. Open the extracted `ESS-main` folder in File Explorer.
2. If that folder contains another `ESS-main` folder, open the inner folder.
3. Confirm that the folder directly contains:
   - `START-HERE-DATAVERSE.cmd`
   - `TUNE-TOPICS.cmd`
   - the `tools` folder
4. Double-click **`TUNE-TOPICS.cmd`**.
5. Select the exported `ConversationTranscript` CSV.
6. Leave the window open while the tuner analyzes the file.

The tuner reuses the Dataverse URL and optional inputs saved by the baseline setup. It does not ask you to select those files again.

Review files are written under:

```text
Generated Templates\Topic Review
```

If that folder already contains results, the next run uses a new `run-*` subfolder so previous approvals are not overwritten.

## Step 4 - Follow the result

The tool reports one of three outcomes:

| Result | What it means | What you do |
|---|---|---|
| **READY** | One or more approved rules are ready. | Continue with the new validation template opened by the tool. |
| **REVIEW REQUIRED** | Candidate rules need customer judgment. | Review one CSV, then return to the same window. |
| **STOP** | No safe, useful rule can be produced from this export. | Keep the existing report unchanged. |

### READY

The tuner validates the approved rules, embeds them in a new template, and opens:

```text
Generated Templates\ESS Dashboard - Dynamic Topics (Dataverse) V21 - Desktop Validation - Topics - DO NOT PUBLISH.pbit
```

Continue to [Step 5](#step-5---validate-the-improvement).

Do not browse for a rules JSON in Power BI or add it as a data source. The approved rules are already embedded.

### REVIEW REQUIRED

1. Open only the `customer-topic-overrides.csv` path printed by the tool.
2. For each rule you understand:
   - confirm or enter **Vertical**;
   - confirm or enter **CanonicalTopic**;
   - adjust **Keywords** or **Exclusions** if needed, separating alternatives with `|`; and
   - set **Enabled** to `true` only when the rule is safe and approved.
3. Leave weak or ambiguous rows disabled.
4. Keep the remaining columns unchanged.
5. Save and close the CSV.
6. Return to the same tuner window.
7. Press **Enter** to validate, build, and open the new template.

Type `skip` instead of pressing Enter if you do not want to apply the reviewed rules. The existing template and saved approvals remain unchanged.

Customer review supplies the business meaning. Test every approved rule against both matching and unrelated conversations.

After a successful reviewed build, keep the generated `approved-*.json` file in its Topic Review folder. Saved setup references that file for later tuning and Service-template builds.

### STOP

Do not change the template or import the empty JSON. The message explains why the tuner stopped:

| Reason | Recommended action |
|---|---|
| Existing topics already cover the export | Keep the baseline report. |
| Too little repeated evidence | Collect more distinct representative conversations. |
| Ambiguous terminology | Add native-labeled examples that distinguish the meanings. |
| No usable native topic evidence | Add meaningful native topic evidence, or review repeated terms manually when candidates are available. |

`STOP` is a safe result, not a failed installation.

## Step 5 - Validate the improvement

In the newly opened **Desktop Validation - Topics - DO NOT PUBLISH** template:

1. Wait until every prefilled parameter value is visible and stable.
2. Select **Load**.
3. Sign in with **Organizational account** if prompted.
4. Select **Home -> Refresh**.
5. Open **Conversation Details** and confirm the intended previously unresolved conversations now use the approved topic.
6. Confirm:
   - native Copilot Studio topics are unchanged;
   - unrelated conversations did not move into the customer topic;
   - ambiguous conversations remain unassigned when appropriate;
   - topic counts are plausible on **Conversation Details**, **Improvement Opportunities**, and **Adjust Topic Assumptions**; and
   - the **Glossary** load diagnostics show no blocking topic-rule error.

Classification follows this order:

1. Native Copilot Studio topic
2. Approved customer rule
3. Built-in ESS taxonomy
4. Other / Uncategorized

> [!IMPORTANT]
> This file is for Desktop validation only. Its filename includes **DO NOT PUBLISH** because it may contain local Organization or Credits file paths.

## Step 6 - Publish only if needed

If the report is only for Desktop use, save the validated PBIX and stop here.

For shared Power BI Service access:

1. Close the Desktop validation report.
2. Return to the extracted `ESS-main` folder.
3. Double-click **`BUILD-SERVICE-REFRESH.cmd`**.
4. When asked whether to reuse the saved setup, choose **Yes**. Choosing No starts without the approved topic-rule selection.
5. Confirm the validation summary lists **Approved topic rules** with the expected non-zero rule count.
6. Open the generated file whose name ends with:

   ```text
   Power BI Service - PUBLISH THIS.pbit
   ```

7. Refresh it successfully in Power BI Desktop.
8. Save it as PBIX and publish it.
9. Follow the [automatic refresh guide](AUTO-REFRESH.md#path-a--dataverse-direct-recommended) to configure OAuth2 credentials, run **Refresh now**, verify **Refresh history**, and enable the schedule.

The Service builder reuses the approved topic rules. You do not run the tuner again. Local Organization and Credits files are intentionally excluded from this Service-safe report; use [Fabric](SETUP-Fabric.md) when those sources must also refresh automatically.

## Troubleshooting

| Message or symptom | What to do |
|---|---|
| **No saved Dataverse setup** | Complete the [Dataverse baseline](SETUP-Dataverse.md#action-2---run-the-guided-setup-and-validate-the-report) once from this extracted package. |
| **Python is not recognized** | Install [Python 3.10 or later](https://www.python.org/downloads/windows/) with **Add Python to PATH**, then reopen the launcher. |
| `TUNE-TOPICS.cmd` is missing | Download and extract the [complete ESS ZIP](https://github.com/microsoft/ESS/archive/refs/heads/main.zip). Open the inner `ESS-main` folder if Windows created nested folders. |
| A saved optional file is missing | Restore the saved registry, organization, credits, topic, or feedback input and retry. The tuner does not silently discard saved choices. |
| **STOP** with no rules | Keep the existing report. Collect better evidence only when a meaningful classification gap remains. |
| A generated PBIT cannot be replaced | Close the previously opened Topics validation report, then retry. |
| Queries are blocked or a cyclic reference appears after opening the PBIT | Close without saving, reopen it, wait for all parameter values to stabilize, and then select **Load**. |
| Scheduled refresh is unavailable | Confirm that you published **Power BI Service - PUBLISH THIS**, not a **DO NOT PUBLISH** Desktop report. |

## Privacy and safety

- Processing is local and uses the Python standard library.
- The tuner makes no network, LLM, or external API calls.
- Common email, URL, phone, GUID, IP-address, and long-number patterns are removed before phrase learning.
- Redaction reduces exposure but does not guarantee anonymity; business terms can still be sensitive.
- Keep transcripts and tuner outputs inside the customer environment and review them before sharing.
- Existing approved rules are preserved until another validated template build succeeds.

## Other ESS data paths

This guided apply workflow targets **Dataverse V21**.

- **CSV V18:** paste the active approved JSON into **Customer Topic Overrides JSON (optional)**, then refresh. Use `customer-topic-overrides.json` after an automatic **READY** result or `approved-*.json` after **REVIEW REQUIRED**. See [CSV setup](SETUP-CSV-Download.md).
- **Fabric V2:** upload the reviewed `customer-topic-overrides.csv` to `Files/config/customer-topic-overrides.csv`. See [Fabric setup](SETUP-Fabric.md).

<details>
<summary><strong>Advanced technical reference</strong></summary>

### Learning and matching safeguards

Automatic rules require at least five distinct supporting conversations, at least 90% cross-topic precision, and deterministic conversation-level five-fold validation with at least three correct held-out matches and 90% precision. Do not lower these thresholds merely to force output.

Native topics remain authoritative. Customer rules apply only when a native topic is absent. Approved customer rules then take precedence over built-in rules.

English customer rules include explicit singular/plural alternatives for a limited vocabulary, including `ticket/tickets`, `device/devices`, and `policy/policies`. This is not general fuzzy matching or synonym generation.

Python and the embedded Power Query classifier share a fixed Unicode 16.0 punctuation and whitespace separator table. Equivalent capitalization and punctuation are normalized and deduplicated. Regional locales use their language prefix, so `en-US` and `en-GB` both become `en`. Rules whose keywords become empty after normalization are rejected.

### Saved-rule behavior

Each analysis validates and loads the previously approved rules selected in saved setup. New approvals are merged with those rules rather than replacing them.

Merge precedence is:

1. Explicit reviewed overrides
2. Saved approved rules
3. Newly learned rules

Equivalent rules use normalized locale, keyword, and exclusion sets. Within one source, higher priority wins, followed by stable topic and vertical ordering. Rules with distinct match conditions are retained.

A missing, invalid, or empty saved-rules file stops analysis before outputs are written. `STOP` and failed review runs leave the active setup unchanged.

### Diagnostic files

| File | Purpose |
|---|---|
| `customer-topic-overrides.csv` | The only customer review file; approved rules plus disabled candidates |
| `customer-topic-overrides.json` | Enabled rules embedded by the build |
| `approved-*.json` | Active reviewed-rules file referenced by saved setup after a successful reviewed build; retain it while using that setup |
| `topic-enrichment.csv` | Hashed conversation keys and predicted topics |
| `classification-audit.csv` | Matching, ambiguity, source, and classifier diagnostics |
| `topic-learning-audit.csv` | Native evidence and held-out validation metrics |
| `privacy-report.json` | Aggregate counts, redactions, and workflow outcome |

The PBIT output cannot replace the source template, customer inputs, saved setup, any tuner diagnostic, or prepared-feedback file. Paths are normalized case-insensitively and checked before writes.

Template publication stages and validates the PBIT and settings before replacement. If publication fails, the prior settings and template remain active or the retained recovery artifact is identified explicitly.

### Command-line use

The launcher is recommended for customers. Advanced users can run:

```powershell
python .\tools\ess_topic_tuner.py --input "C:\AgentData\ConversationTranscripts.csv" --output-dir "C:\AgentData\topic-review"
```

Useful options:

| Option | Purpose |
|---|---|
| `--analyze-only` | Generate analysis without building or opening a template |
| `--json` | Produce machine-readable analysis; implies analysis-only |
| `--non-interactive` | Never wait for customer review |
| `--no-open` | Build without opening Power BI Desktop |
| `--settings-file` | Select a specific saved Dataverse setup |
| `--overrides` | Include a previously reviewed override CSV |
| `--apply` / `--review` | Recovery actions printed by the tool |

`--json` and `--analyze-only` cannot be combined with `--apply` or `--review`.

The automated suite compares the source PBIT's applied and pending Power Query expressions with the generator. A separate `PQTest.exe` regression compares the generated Power Query classifier with Python across Unicode punctuation, regional locales, deduplication, and invalid normalized keywords.

</details>
