# Tune customer-specific topics (optional)

Use this optional workflow when meaningful customer terminology is repeatedly left as **Other / Uncategorized** or assigned to a topic that is too broad.

The tuner first applies deterministic ESS rules, then uses the bundled local multilingual model to rank closed-taxonomy suggestions for unresolved first-user messages. The local model does not send transcript text off-device and never activates its own label. It groups similar suggestions into review rows containing at most ten redacted examples. A person approves, corrects, or leaves each group unclassified; only those decisions become exact conversation-ID mappings.

The tuner does not change Copilot Studio topics, send credentials to Power BI, or make model calls during Power BI Desktop or Service refresh.

## Should you use the topic tuner?

| Use it when | Skip it when |
|---|---|
| The same meaningful customer terms are missed across several conversations. | Meaningful native Copilot Studio topics and the built-in ESS taxonomy already classify the conversations correctly. |
| You have representative conversations that can validate the intended coverage. | The gap is caused by missing transcript access or missing user-message text. |
| The customer permits local processing of its exported transcript on its own device. | The baseline report has an access, environment, retention, or loading problem. |

> [!IMPORTANT]
> Topic tuning is not required for the ESS report. Complete the [guided Dataverse baseline setup](SETUP-Dataverse.md#option-b---guided-setup-with-optional-enhancements) first so the tuner has saved setup state. Topic rules cannot repair missing permissions, an incorrect Environment URL, expired transcripts, or disabled transcript capture.

## Customer journey

| Step | Customer action | Result |
|---|---|---|
| 1 | [Confirm the baseline and prepare evidence](#step-1---confirm-the-baseline-and-prepare-evidence) | A working Dataverse report and representative conversations |
| 2 | [Export the conversations](#step-2---export-the-conversations) | A local `ConversationTranscript` CSV |
| 3 | [Run the topic tuner](#step-3---run-the-topic-tuner) | A `READY`, `REVIEW REQUIRED`, or `STOP` result |
| 4 | [Follow the result](#step-4---follow-the-result) | Approved rules and grouped semantic decisions embedded in a new validation template |
| 5 | [Validate the improvement](#step-5---validate-the-improvement) | Confirmed topic behavior in Power BI Desktop |
| 6 | [Publish only if needed](#step-6---publish-only-if-needed) | A separate Service-safe report for scheduled refresh |

## Before you start

You need:

- the [complete validated V23.2 package](https://github.com/microsoft/ESS/releases/download/dataverse-v23.2/ESS-039417f-optional-fixes-V23.2.zip), extracted with its folder structure intact;
- [Python 3.14](https://www.python.org/downloads/windows/) with **Add Python to PATH** selected during installation. Python 3.10 through 3.14 is supported; Python 3.15 is not yet supported by the required NumPy and ONNX Runtime libraries;
- a successful [Dataverse V23 baseline](SETUP-Dataverse.md);
- permission to export `ConversationTranscript` from the same Dataverse environment; and
- a customer-controlled folder for the transcript export and review files.

The complete release package includes the hash-verified multilingual E5 model. On the first local semantic run, the launcher prepares the required Python runtime libraries automatically if they are not already installed. This downloads runtime libraries only; transcript text is not uploaded.

The optional Azure provider additionally requires:

- explicit customer approval to send redacted unresolved first-user messages to a model;
- a customer-owned Azure OpenAI or Microsoft Foundry endpoint ending in `.openai.azure.com`, `.services.ai.azure.com`, or `.cognitiveservices.azure.com`;
- an approved model deployment that supports structured JSON output; and
- an API key supplied through the secure prompt or the temporary `ESS_SEMANTIC_API_KEY` environment variable.

The endpoint, deployment, and API key are not embedded in the generated report. The API key is never written to settings or diagnostics.

## Step 1 - Confirm the baseline and prepare evidence

1. Complete [Option B in the Dataverse setup guide](SETUP-Dataverse.md#option-b---guided-setup-with-optional-enhancements).
2. Confirm that **Total Conversations** is non-zero and the expected agent appears in the Agent filter.
3. Identify recurring customer terms that are currently unclassified or classified too broadly.
4. Include several distinct conversations that demonstrate the intended meaning. Automatic deterministic and semantic learning both require at least five distinct supporting conversations by default.
5. Use **Start over** between test conversations so each example is retained as a separate conversation.

Meaningful native Copilot Studio business-topic evidence is the safest source for automatic learning. Generic states such as `[System] - Response Preparation`, internal/admin/debug/test topics, fallback, greeting, sign-in, and reset topics are not treated as authoritative business labels; they fall through to the shared classifier.

The five-conversation gate applies to reusable learned rules. Local model scores and margins are advisory ranking signals, not proof of correctness. Every local semantic group requires human approval before its conversation IDs receive a topic. Low-information messages are omitted from review and remain **Other / Uncategorized**.

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

1. Open the extracted `ESS-039417f-optional-fixes-V23.2` folder in File Explorer.
2. If Windows created a nested package folder, open the inner `ESS-039417f-optional-fixes-V23.2` folder.
3. Confirm that the folder directly contains:
   - `START-HERE-DATAVERSE.cmd`
   - `TUNE-TOPICS.cmd`
   - the `tools` folder
4. Double-click **`TUNE-TOPICS.cmd`**.
5. Select the exported `ConversationTranscript` CSV.
6. Leave the window open while the bundled local classifier analyzes unresolved messages.
7. If the local Python runtime libraries are missing, the launcher prepares them once. This step does not send transcript data.

Local semantic processing stays on the customer's device. Common email, URL, GUID, IPv4, phone-number, and long-number patterns are still removed before inference and rule learning to minimize retained evidence.

By default, the tuner deliberately reuses the Dataverse URL and optional inputs saved by setup. It does not ask you to select those files again, and does not silently discard a missing saved file. To change them interactively, rerun `START-HERE-DATAVERSE.cmd` first and independently keep, replace, or skip each enhancement.

For explicit opt-outs, the tuner accepts `--skip-agent-registry`, `--skip-org-data`, `--skip-agent-credits`, and `--skip-feedback`. It forwards those choices to guided apply and retains them in printed review/recovery commands. A successful apply saves the resulting Desktop selections. For example, from the V23 package folder:

```powershell
python tools\ess_topic_tuner.py `
  --input "C:\AgentData\ConversationTranscript.csv" `
  --output-dir "C:\AgentData\TopicReview" `
  --skip-agent-registry --skip-org-data --skip-agent-credits --skip-feedback
```

The guided `--tune-topics` entry point forwards the same four flags. Do not use `--skip-topic-overrides` with tuning: tuning applies new approved rules rather than skipping them. Other saved enhancements remain deliberately reusable unless explicitly skipped.

For unattended local semantic execution, pass `--semantic-classification --semantic-provider local`. Azure remains available only as an explicit alternative with `--semantic-provider azure`, `--semantic-endpoint`, and `--semantic-deployment`; provide its API key only through `ESS_SEMANTIC_API_KEY`.

Review files are written under:

```text
Generated Templates\Topic Review
```

If that folder already contains results, the next run uses a new `run-*` subfolder so previous approvals are not overwritten.

## Step 4 - Follow the result

The tool reports one of three outcomes:

| Result | What it means | What you do |
|---|---|---|
| **READY** | One or more deterministic rules are ready without semantic review. | Continue with the new validation template opened by the tool. |
| **REVIEW REQUIRED - grouped semantic suggestions** | The local model grouped unresolved conversations and prefilled likely topics and alternatives. | Approve, correct, or leave each group disabled in `semantic-topic-review.csv`; save and return to the same window. |
| **REVIEW REQUIRED** | Candidate rules need customer judgment. | Review one CSV, then return to the same window. |
| **STOP** | No safe, useful rule can be produced from this export. | Keep the existing report unchanged. |

A local suggestion becomes a Power BI topic only after a person enables its review group and confirms or corrects the taxonomy decision. Every redacted example in the group is displayed, groups contain at most ten conversations, and mixed groups must remain disabled. The resulting embedded mapping contains the conversation ID, human-approved topic, vertical, and review provenance—never the prompt.

### READY

The tuner validates approved deterministic rules and any human-approved semantic groups, embeds them in a new template, and opens:

```text
Generated Templates\ESS Dashboard - Dynamic Topics (Dataverse) V23 - Desktop Validation - Topics - LOCAL ONLY.pbit
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
| No usable native topic evidence | Confirm the complete package contains the local model pack and rerun. The customer does not need an Azure endpoint. |
| Semantic results are low-confidence, abstained, or inconsistent | Keep those conversations unclassified. Do not weaken the confidence or validation gates merely to force coverage. |

`STOP` is a safe result, not a failed installation.

## Step 5 - Validate the improvement

In the newly opened **Desktop Validation - Topics - LOCAL ONLY** template:

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

1. Meaningful native Copilot Studio business topic
2. Exact human-approved semantic mapping for the current conversation ID
3. Explicit reviewed customer rule
4. Previously approved legacy customer rule without recorded provenance
5. Cross-validated native-topic learned rule
6. Cross-validated semantic learned rule
7. Built-in ESS taxonomy
8. Other / Uncategorized

Generic system/internal/admin/debug/test topics are not preserved as business topics. They fall through to human-approved exact mappings and deterministic rules. The local model is used only while tuning; Power BI Desktop and Power BI Service refresh use embedded conversation mappings and deterministic rules and never load or call the model.

> [!IMPORTANT]
> This is the local topic-validation output and may contain local Organization or Credits file paths. For shared Power BI Service access, continue to Step 6 and generate the separate **Power BI Service - PUBLISH THIS** output.

## Step 6 - Publish only if needed

If the report is only for Desktop use, save the validated PBIX and stop here.

For shared Power BI Service access:

1. Close the Desktop validation report.
2. Return to the extracted `ESS-039417f-optional-fixes-V23.2` folder.
3. Double-click **`BUILD-SERVICE-REFRESH.cmd`**.
4. When asked whether to reuse the saved setup, choose **Yes**, then explicitly **keep** the approved topic rules. Human-approved exact conversation mappings are retained with that saved setup. Independently keep, replace, or skip the other enhancements.
5. Confirm the validation summary lists the expected approved rule count and exact semantic conversation-topic file.
6. Open the generated file whose name ends with:

   ```text
   Power BI Service - PUBLISH THIS.pbit
   ```

7. Refresh it successfully in Power BI Desktop.
8. Save it as PBIX and publish it.
9. Follow the [automatic refresh guide](AUTO-REFRESH.md#path-a--dataverse-direct-recommended) to configure OAuth2 credentials, run **Refresh now**, verify **Refresh history**, and enable the schedule.

In the Service builder, explicitly **keep** the saved approved topic rules; Enter now skips a saved enhancement. You do not run the tuner again. Registry, cloud organization data, and feedback remain independent keep/replace/skip choices. Local Organization and Credits files are intentionally excluded from this Service-safe report. Organization can still refresh from a direct SharePoint Online/OneDrive for Business CSV URL; use [Fabric](SETUP-Fabric.md) for automated credits or organization ingestion directly from Entra/Graph.

## Troubleshooting

| Message or symptom | What to do |
|---|---|
| **No saved Dataverse setup** | Complete the [guided Dataverse baseline](SETUP-Dataverse.md#option-b---guided-setup-with-optional-enhancements) once from this extracted package. |
| **Python is not recognized or Python 3.15 is selected** | Install [Python 3.14](https://www.python.org/downloads/windows/) with **Add Python to PATH**, then reopen the launcher. Python 3.15 may remain installed; the corrected launcher prefers 3.14. |
| `TUNE-TOPICS.cmd` is missing | Extract the complete corrected `ESS-039417f-optional-fixes-V23.2.zip`. Open the inner package folder if Windows created nested folders; do not download individual scripts. |
| A saved optional file is missing | Restore it, rerun guided setup to replace/skip it, or use the applicable tuner skip flag for registry, organization, credits, or feedback. Printed recovery commands retain skip flags. New approved topic rules replace the saved topic-rule selection. Other saved choices are not silently discarded. |
| **STOP** with no rules | Keep the existing report. Collect better evidence only when a meaningful classification gap remains. |
| Local model file is missing or fails its hash check | Extract the complete release ZIP again. Do not download individual scripts or model files. |
| Local semantic runtime cannot be prepared | Confirm Python can reach PyPI for the one-time runtime-library download, or ask IT to allow/install `numpy`, `onnxruntime`, and `tokenizers`. No transcript text is included in that download. |
| Azure endpoint is rejected | Azure is optional. Use the bundled local provider, or supply an HTTPS customer-owned Azure resource endpoint with an approved suffix. |
| Many rows remain **Other / Uncategorized** | Review `semantic-classification-audit.csv`. Low-information, low-similarity, closely tied, or out-of-taxonomy messages intentionally remain unclassified. |
| A generated PBIT cannot be replaced | Close the previously opened Topics validation report, then retry. |
| Queries are blocked or a cyclic reference appears after opening the PBIT | Close without saving, reopen it, wait for all parameter values to stabilize, and then select **Load**. |
| Scheduled refresh is unavailable | Confirm that you published **Power BI Service - PUBLISH THIS**. The **Desktop Validation - LOCAL ONLY** report is the separate local input-checking output. |

## Privacy and safety

- Deterministic and default semantic processing are local.
- The bundled model is pinned to `intfloat/multilingual-e5-small` revision `614241f622f53c4eeff9890bdc4f31cfecc418b3`; its model and tokenizer hashes are verified before every load.
- Local inference uses ONNX Runtime with `CPUExecutionProvider`; no transcript text is sent to a model service.
- Azure processing is optional, disabled unless explicitly selected, and requires customer approval.
- When Azure is selected, only unresolved first-user messages are sent to the customer-owned approved endpoint.
- Common email, URL, phone, GUID, IP-address, and long-number patterns are removed first, and text is capped at 4,000 characters.
- Redaction reduces exposure but does not guarantee anonymity. Names, uncommon identifiers, customer terminology, and confidential business phrases may remain.
- Requests use structured output constrained to the checked-in ESS taxonomy and set `store` to `false`.
- The provider cannot add a new canonical topic. Unknown, malformed, missing, duplicate, low-confidence, or out-of-taxonomy results are rejected.
- The API key comes from a secure prompt or `ESS_SEMANTIC_API_KEY`; it is never persisted.
- Semantic audit files contain hashes, labels, confidence, status, provider version, and deployment name, but no prompt text.
- Local model output is suggestion-only. A human must approve or correct each grouped pattern before a prompt-free exact conversation mapping is embedded.
- Power BI receives validated deterministic rules and human-approved prompt-free exact conversation mappings. Desktop and Service refresh never load the local model or call an endpoint.
- Keep transcripts and tuner outputs inside the customer environment and review them before sharing.
- Existing approved rules are preserved until another validated template build succeeds.

## Other ESS data paths

This guided apply workflow targets **Dataverse V23**. The unchanged V22 and V21 templates remain available for comparison and rollback.

- **CSV V18:** paste the active approved JSON into **Customer Topic Overrides JSON (optional)**, then refresh. Use `customer-topic-overrides.json` after an automatic **READY** result or `approved-*.json` after **REVIEW REQUIRED**. See [CSV setup](SETUP-CSV-Download.md).
- **Fabric V2:** upload the reviewed `customer-topic-overrides.csv` to `Files/config/customer-topic-overrides.csv`. See [Fabric setup](SETUP-Fabric.md).

<details>
<summary><strong>Advanced technical reference</strong></summary>

### Learning and matching safeguards

Automatic rules require at least five distinct supporting conversations, at least 90% cross-topic precision, and deterministic conversation-level five-fold validation with at least three correct held-out matches and 90% precision. Local cosine similarity and runner-up margin are displayed only to help review; they never bypass human approval.

Meaningful native business topics remain authoritative. Generic system/internal/admin/debug/test states are excluded from learning and fall through to the shared classifier. Explicit reviewed rules take precedence over saved approved rules, native-topic learned rules, semantic learned rules, and built-in rules.

When locale is unknown, candidate extraction uses the combined supported-language stop-word set while retaining wildcard locale matching. This prevents common words such as `what`, `the`, `can`, and `for` from becoming customer rules merely because Dataverse did not provide a locale.

English customer rules include explicit singular/plural alternatives for a limited vocabulary, including `ticket/tickets`, `device/devices`, and `policy/policies`. This is not general fuzzy matching or synonym generation.

Python and the embedded Power Query classifier share a fixed Unicode 16.0 punctuation and whitespace separator table. Equivalent capitalization and punctuation are normalized and deduplicated. Regional locales use their language prefix, so `en-US` and `en-GB` both become `en`. Rules whose keywords become empty after normalization are rejected.

### Saved-rule behavior

Each analysis validates and loads the previously approved rules selected in saved setup. New approvals are merged with those rules rather than replacing them.

Merge precedence is:

1. Explicit reviewed overrides
2. Previously approved legacy rules without recorded provenance
3. Meaningful native-topic learned rules
4. Semantic learned rules

Equivalent rules use normalized locale, keyword, and exclusion sets. Within one source, higher priority wins, followed by stable topic and vertical ordering. Rules with distinct match conditions are retained.

Newly published rules retain their recorded provenance on later runs, so an explicit reviewed rule remains explicit and learned rules retain their native or semantic safeguards.

A missing, invalid, or empty saved-rules file stops analysis before outputs are written. `STOP` and failed review runs leave the active setup unchanged.

### Diagnostic files

| File | Purpose |
|---|---|
| `customer-topic-overrides.csv` | Deterministic approved rules plus disabled rule candidates |
| `semantic-topic-review.csv` | Grouped local suggestions, alternatives, all redacted examples in each group, and customer decision fields |
| `semantic-review-evidence.json` | Prompt-free conversation IDs and model candidates used to apply approved review groups; do not edit |
| `semantic-review-integrity.key` | Local integrity key binding displayed review context to exact conversation IDs; keep it in the Topic Review folder and do not edit or share it |
| `customer-topic-overrides.json` | Enabled rules embedded by the build |
| `approved-*.json` | Active reviewed-rules file referenced by saved setup after a successful reviewed build; retain it while using that setup |
| `topic-enrichment.csv` | Hashed conversation keys and predicted topics |
| `classification-audit.csv` | Matching, ambiguity, source, and classifier diagnostics |
| `topic-learning-audit.csv` | Native evidence and held-out validation metrics |
| `semantic-classification-audit.csv` | Hashed suggestion or Azure classification, confidence, status, provider version, and deployment; no prompt text |
| `semantic-learning-audit.csv` | Deterministic rule-learning and held-out validation metrics derived from accepted Azure labels; local suggestions never train rules before review |
| `semantic-conversation-topics.json` | Exact conversation ID, human-approved closed-taxonomy topic, vertical, and review provenance; no prompt text |
| `privacy-report.json` | Aggregate counts, redactions, semantic request metrics, and workflow outcome |

The PBIT output cannot replace the source template, customer inputs, saved setup, any tuner diagnostic, or prepared-feedback file. Paths are normalized case-insensitively and checked before writes.

Template publication stages and validates the PBIT and settings before replacement. If publication fails, the prior settings and template remain active or the retained recovery artifact is identified explicitly.

### Command-line use

The launcher is recommended for customers. Advanced users can run:

```powershell
python .\tools\ess_topic_tuner.py --input "C:\AgentData\ConversationTranscripts.csv" --output-dir "C:\AgentData\topic-review"
```

Default local semantic mode:

```powershell
python .\tools\ess_topic_tuner.py `
  --input "C:\AgentData\ConversationTranscripts.csv" `
  --output-dir "C:\AgentData\topic-review" `
  --semantic-classification `
  --semantic-provider local
```

Optional customer-approved Azure provider:

```powershell
$env:ESS_SEMANTIC_API_KEY = Read-Host "Azure OpenAI API key" -MaskInput
python .\tools\ess_topic_tuner.py `
  --input "C:\AgentData\ConversationTranscripts.csv" `
  --output-dir "C:\AgentData\topic-review" `
  --semantic-classification `
  --semantic-provider azure `
  --semantic-endpoint "https://customer-resource.openai.azure.com" `
  --semantic-deployment "approved-deployment"
Remove-Item Env:\ESS_SEMANTIC_API_KEY
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
| `--semantic-classification` | Enable closed-taxonomy semantic classification; guided tuning enables the local provider by default |
| `--semantic-provider` | `local` by default, or explicit optional `azure` |
| `--local-model-dir` | Hash-verified bundled multilingual E5 model directory |
| `--local-min-similarity` | Advisory local similarity threshold recorded for diagnostics; it does not auto-approve labels |
| `--local-min-margin` | Advisory top-topic margin recorded for diagnostics; it does not auto-approve labels |
| `--semantic-endpoint` | Customer-owned Azure OpenAI or Microsoft Foundry resource endpoint |
| `--semantic-deployment` | Approved customer model deployment |
| `--semantic-min-confidence` | Minimum accepted model confidence; default `0.90` |
| `--apply` / `--review` | Recovery actions printed by the tool |

`--json` and `--analyze-only` cannot be combined with `--apply` or `--review`.

The automated suite compares the source PBIT's applied and pending Power Query expressions with the generator. A separate `PQTest.exe` regression compares the generated Power Query classifier with Python across Unicode punctuation, regional locales, deduplication, and invalid normalized keywords.

</details>
