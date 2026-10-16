# Optional private adaptive topic tuner

Use this optional tool when recurring customer terminology remains unclassified or is repeatedly classified under a broad built-in topic. It can improve **Conversation Details**, **Improvement Opportunities**, **Adjust Topic Assumptions**, and Fabric topic exploration without changing native Copilot Studio topics.

| Decision | Guidance |
|---|---|
| **Use it** | Native and built-in classification repeatedly miss meaningful customer terms, and enough representative conversations exist to validate a rule. |
| **Skip it** | Native and built-in topics already provide adequate coverage, the gaps are rare, or there is not enough evidence to validate a customer rule safely. |

Start with the report's existing topic results. This tool does not unlock the baseline report and is not required for transcript, adoption, outcome, feedback, or business-impact analysis.

> [!IMPORTANT]
> The **Optional topic tuner** link opens this guide; it does not run the tuner or change the report. The tuner is a separate local preparation step. It reads an exported transcript CSV and creates `customer-topic-overrides.json`. You then run the Dataverse guided setup again and select that JSON under **Approved topic rules**.

The transcript CSV is used only to learn and review topic rules locally. Dataverse V21 continues to read report data directly from Dataverse; the CSV is not added as a report data source.

## Dataverse V21 customer path

If you arrived here from the Dataverse setup guide, use this sequence:

| Stage | Customer action | Result |
|---|---|---|
| 1. Confirm the baseline | Complete the URL-only Dataverse setup first | A working report before optional topic changes |
| 2. Export evidence | Export the untouched `ConversationTranscript` table | Local CSV used only by the tuner |
| 3. Run and review | Run the tuner and review its results | Approved `customer-topic-overrides.json` |
| 4. Add the rules | Run `START-HERE-DATAVERSE.cmd` again and select the JSON | New Desktop Validation PBIT with the rules embedded |
| 5. Validate and publish | Check topic results, then use the normal Service publication step if needed | Validated PBIX or Service Refresh PBIT |

Do not continue with the tuner until the transcript-only Dataverse report loads successfully. Optional topic rules cannot repair an incorrect environment URL, missing transcript access, expired records, or disabled transcript capture.

### Step 1 - Export representative topic evidence

Use a representative set of retained conversations. To test automatic learning, include at least five distinct conversations in which recurring customer terminology is associated with the same meaningful native Copilot Studio topic. Use **Start over** between business questions so each question is retained as a separate conversation.

1. Sign in to [Power Apps](https://make.powerapps.com).
2. Select the same environment used by the Dataverse report.
3. Select **Tables**.
4. Select **All**, search for `conversation`, and open **ConversationTranscript**.
5. Select **Export -> Export data**.
6. Wait for the export to finish, then select **Download exported data**.
7. Extract the downloaded ZIP.
8. Create `C:\AgentData`, move the CSV there, and rename it `ConversationTranscripts.csv`.

Do not open or save the transcript CSV in Excel. Excel can corrupt the JSON in its `Content` column.

### Step 2 - Create the topic-rule files

1. Open the extracted `ESS-main` folder in File Explorer. Confirm that the file list includes the `tools` folder and `START-HERE-DATAVERSE.cmd`.
2. Press **Alt+D** to select the File Explorer address bar. The complete folder path should become highlighted.
3. Type `powershell.exe` exactly, including `.exe`, and press **Enter**. Do not use the **Search ESS-main** box or select an address suggestion.
4. Confirm that a PowerShell terminal window opens and its prompt ends with `\ESS-main>`. If another File Explorer folder opens, return to `ESS-main` and repeat steps 2-3 using `powershell.exe`.
5. Run the following three commands **one at a time**. Press **Enter** and wait for the result before moving to the next command.

**Command 1 - Check the Python version**

```powershell
python --version
```

The result must be `Python 3.10` or later.

**Command 2 - Confirm that the tuner script is in the current folder**

```powershell
Test-Path .\tools\ess_topic_tuner.py
```

The result must be `True`.

**Command 3 - Run the tuner**

```powershell
python tools\ess_topic_tuner.py --input "C:\AgentData\ConversationTranscripts.csv" --output-dir "C:\AgentData\topic-review" --min-frequency 5
```

The third command creates `C:\AgentData\topic-review` and the six files described below.

Open `topic-learning-audit.csv` and check `Status`:

- If every required rule is `AutoValidated` and its validation metrics are acceptable, use `C:\AgentData\topic-review\customer-topic-overrides.json`.
- If a required rule is `NeedsReview` or `Candidate`, complete the review process in [Review only unresolved items](#3-review-only-unresolved-items). Use the `customer-topic-overrides.json` from the resulting `topic-review-approved` folder.
- If the result is `InsufficientEvidence`, collect more representative conversations or skip the custom rule. Do not lower safety thresholds merely to force a result.

### Step 3 - Add the approved JSON to Dataverse V21

The tuner does not update a report that is already open. After choosing the approved JSON:

1. Return to the extracted `ESS-main` folder.
2. Double-click `START-HERE-DATAVERSE.cmd`.
3. Select **Yes** to reuse the saved setup choices.
4. Confirm the saved Dataverse Environment URL.
5. Select **Yes** when asked whether to choose or replace optional files.
6. Keep or skip the Agent registry, Organization data, and Copilot credit files as appropriate for the current test.
7. At **Approved topic rules**, select **Yes** and choose `customer-topic-overrides.json`.
8. Keep or skip Microsoft 365 feedback as appropriate for the current test.
9. Confirm that the validation summary reports **Approved topic rules** with a non-zero row count.
10. Open the generated Desktop Validation PBIT, wait until every parameter value is visible and stable, and then select **Load**.

The guided setup validates and embeds the JSON. It also saves the approved file selection for the same environment, so `BUILD-SERVICE-REFRESH.cmd` can reuse it later.

### Step 4 - Validate the customer experience

Confirm:

- native Copilot Studio topics remain unchanged;
- the expected customer rule classifies the intended previously unresolved conversations;
- unrelated conversations do not move into the customer topic;
- ambiguous conversations remain unassigned rather than being forced into a topic;
- topic counts are plausible on **Conversation Details**, **Improvement Opportunities**, and **Adjust Topic Assumptions**; and
- the **Glossary** load-diagnostics entry shows no blocking topic-rule error.

If the Desktop result is correct and shared Service access is required, close the report, run `BUILD-SERVICE-REFRESH.cmd`, open the generated Service Refresh PBIT, refresh it, save it as PBIX, and publish it. The publication helper reuses the saved approved topic rules; you do not run the tuner again.

`tools/ess_topic_tuner.py` learns customer-specific topic rules from the customer's own Copilot Studio native-topic evidence and applies those rules to similar conversations that have no native topic. It processes every user turn locally, uses only the Python standard library, and makes no network, LLM, or external API calls.

Native Copilot Studio topics remain authoritative. The corrected built-in English, Spanish, and Chinese taxonomy remains the fallback when Python is not used or when the local evidence is insufficient. The tuner does not force an assignment when evidence is ambiguous.

When an enabled customer rule and a built-in rule both match, the customer rule wins. Score and priority resolve collisions only among rules from the same source.

Automatic rules must pass deterministic conversation-level five-fold validation. Each conversation is excluded from the training data for one fold, the rule is relearned, and its prediction is checked against that held-out native topic. This prevents the reported precision from being only a measurement of the same rows used to learn the phrases.

The tuner can automatically reuse topic labels that are present in native `IntentRecognition` events. It cannot safely invent an authoritative business label for a topic that has never appeared in native evidence; those remaining repeated gaps are written as disabled review candidates instead.

Topic overrides apply to every agent included in the current report scope. For substantially different agent domains, use **Selected Agents** or maintain rules that are valid across all included agents.

## Download the tuner

[Download the complete ESS package as a ZIP](https://github.com/microsoft/ESS/archive/refs/heads/main.zip), select **Extract All**, and run the commands in this guide from the extracted `ESS-main` folder. The package includes:

- `tools/ess_topic_tuner.py`;
- `tools/topic_classifier.py`; and
- `taxonomy/topics-taxonomy.csv`.

> Do not download `ess_topic_tuner.py` by itself. It imports the companion classifier and loads the shared taxonomy using repository-relative paths.

## What it produces

| File | Purpose | Contains transcript text? |
|---|---|---|
| `customer-topic-overrides.csv` | Auto-validated rules plus any disabled items requiring review | No prompt field; a learned phrase can equal a short prompt |
| `customer-topic-overrides.json` | Enabled auto-validated and customer-approved rules ready for the templates | No |
| `topic-enrichment.csv` | Hashed conversation key plus assigned topic and confidence | No |
| `classification-audit.csv` | Hashed conversation key plus rule, score, ambiguity, and version diagnostics | No |
| `topic-learning-audit.csv` | Native-topic support, in-sample screening, out-of-fold precision/coverage, and enablement decision | No prompt field; includes learned phrases |
| `privacy-report.json` | Aggregate counts, suppression threshold, and redaction summary | No |

> **Privacy boundary:** the tool removes common email, URL, phone, GUID, IP-address, and long-number patterns before learning or candidate extraction. It also requires evidence from multiple distinct conversations. This reduces exposure but does not guarantee anonymity: repeated project names or other business-sensitive terms can still appear. Keep all output inside the customer environment and review it before sharing.

## Before you start

You need:

- the [complete ESS package](https://github.com/microsoft/ESS/archive/refs/heads/main.zip) downloaded and extracted;
- a raw Dataverse `ConversationTranscript` CSV;
- Python 3.10 or later; and
- an approved customer-controlled output folder.

Use the transcript export steps in [CSV setup - Step 1](SETUP-CSV-Download.md#step-1--export-your-conversation-transcripts--required). Do not open or save the transcript CSV in Excel because Excel can corrupt the JSON in its `Content` column.

### Confirm Python

1. Open the unzipped `ESS-main` folder in File Explorer and confirm that the file list includes the `tools` folder.
2. Press **Alt+D** to select the address bar. The complete folder path should become highlighted.
3. Type `powershell.exe` exactly, including `.exe`, and press **Enter**. Do not use the search box or select an address suggestion.
4. Confirm that a PowerShell terminal window opens and its prompt ends with `\ESS-main>`.
5. Run these commands **one at a time**, pressing **Enter** after each command:

```powershell
python --version
```

The result must be `Python 3.10` or later.

```powershell
Test-Path .\tools\ess_topic_tuner.py
```

The result must be `True`. If `Test-Path` returns `False`, the terminal is not open in the complete extracted package. If Windows says that Python is not recognized, install Python from [python.org](https://www.python.org/downloads/windows/), select **Add Python to PATH** during setup, close PowerShell, and repeat these steps.

No Python packages need to be installed.

## 1. Run the tuner

A raw Dataverse `ConversationTranscript` CSV is detected automatically. From the PowerShell window opened above, run:

```powershell
python tools\ess_topic_tuner.py --input "C:\AgentData\ConversationTranscripts.csv" --output-dir "C:\AgentData\topic-review" --min-frequency 5
```

Replace the input path with the full path to your transcript CSV. The output folder is created automatically. A successful run prints a summary and creates the six files listed above.

The raw transcript path is preferred because it lets the tuner learn from every user turn and its paired native topic. The tool also accepts a flat CSV containing a prompt column such as `first_user_prompt`, `FirstUserMessage`, or `Prompt`. Include a native-topic column to enable adaptive learning. Use `--prompt-column`, `--locale-column`, `--id-column`, or `--native-topic-column` when the column names are different.

The default automatic acceptance rules are:

- evidence from at least five distinct conversations;
- at least 90% in-sample cross-topic precision;
- at least 90% conversation-level out-of-fold precision with at least three correctly matched validation conversations;
- privacy reduction before phrase learning; and
- no forced label when the evidence is weak or ambiguous.

Use `--min-native-topic-precision`, `--validation-folds`, or `--min-validation-conversations` only when the customer deliberately accepts a different validation policy. Lowering a threshold can increase coverage but also increases the risk of incorrect assignments.

## 2. Verify the automatic result

Open `topic-learning-audit.csv` and check the `Status` column:

| Status | Meaning | Loaded into JSON? |
|---|---|---|
| `AutoValidated` | Label came from native evidence and met the support and precision thresholds | Yes |
| `NeedsReview` | Native label is known, but the phrases did not meet the automatic precision threshold | No |
| `InsufficientEvidence` | Too few repeated phrases were available | No |
| `ExistingOverride` | The supplied override file already contains this topic and locale | Uses the existing enabled setting |

Then check:

- `privacy-report.json` for processed rows, automatic rule counts, and redaction counts;
- `topic-learning-audit.csv` for `ValidationStatus = Passed`, `ValidationPrecision`, `ValidationCoverage`, and zero or acceptably low `ValidationFalsePositiveConversations`;
- `classification-audit.csv` for collisions, ambiguity, native-topic preservation, and rule source; and
- `topic-enrichment.csv` for assigned topic counts by hashed conversation key.

If every required customer topic is `AutoValidated` and its out-of-fold metrics are acceptable, use the first run's `customer-topic-overrides.json` directly. Low coverage is safe but incomplete: unmatched conversations continue to the built-in taxonomy or remain uncategorized. A false positive is more serious than an unassigned row.

## 3. Review only unresolved items

Open `customer-topic-overrides.csv` only when `NeedsReview` or `Candidate` rows require customer judgment:

1. For `NeedsReview`, confirm the native `CanonicalTopic`, edit its keywords or exclusions, and change `Enabled` to `true` only when the rule is safe.
2. For `Candidate`, provide the customer-approved `Vertical` and `CanonicalTopic`, edit the keywords or exclusions, and change `Enabled` to `true`.
3. Keep labels short and understandable. Do not use employee names, case numbers, or other identifying values.
4. Re-run the tuner with the reviewed file:

```powershell
python tools\ess_topic_tuner.py --input "C:\AgentData\ConversationTranscripts.csv" --overrides "C:\AgentData\topic-review\customer-topic-overrides.csv" --output-dir "C:\AgentData\topic-review-approved" --min-frequency 5
```

The new `customer-topic-overrides.json` includes the reviewed enabled rules plus any automatically validated rules not already represented in the supplied file.

## 4. Apply without a template release

### CSV V18

Open **Transform data → Edit parameters** and paste the full contents of `customer-topic-overrides.json` into **Customer Topic Overrides JSON (optional)**. Refresh the model. Because the override is a parameter, it does not add a second data source or create a Formula Firewall dependency.

### Dataverse V21

Follow [Action 2 in the Dataverse Direct guide](SETUP-Dataverse.md#action-2---run-the-guided-setup-and-validate-the-report). When adding data, select `customer-topic-overrides.json` under **Approved topic rules**. Guided setup validates and embeds the reviewed rules. If shared Service access is needed, follow the guide's collapsed publication section after the Desktop result is correct.

### Fabric V2

Upload `customer-topic-overrides.csv` to:

```text
Files/config/customer-topic-overrides.csv
```

Run `Copilot_Agent_Transcript_Parser.ipynb`. The notebook reads only rows where `Enabled` is true, gives them `RuleSource = Customer`, and writes the classifier version with a `+CUSTOMER` suffix. If the file is absent, the notebook uses only the built-in taxonomy.

## Common issues

| Symptom | Cause | Fix |
|---|---|---|
| Typing `powershell` opens another File Explorer folder such as `Documents\PowerShell` | File Explorer interpreted the text as a folder name instead of the PowerShell executable | Return to the extracted `ESS-main` folder, press **Alt+D**, type `powershell.exe` including `.exe`, and press **Enter** without selecting a suggestion |
| `python: can't open file 'tools\ess_topic_tuner.py'` | PowerShell is open in the wrong folder, or only the script was downloaded | Open PowerShell from the extracted `ESS-main` folder and keep the complete package structure intact |
| PowerShell says `python` is not recognized | Python is not installed or not on PATH | Install Python 3.10+ with **Add Python to PATH**, then reopen PowerShell |
| `Input file not found` | The transcript path is incomplete or mistyped | In File Explorer, Shift+right-click the file and select **Copy as path**, then paste that path after `--input` |
| No automatic customer rules are produced | The export has no usable native topic evidence, too few distinct conversations, or the observed precision is below the threshold | Check `topic-learning-audit.csv`; keep the corrected built-in fallback or review disabled items locally |
| A known topic is `NeedsReview` after previously appearing strong | It did not match at least three held-out conversations or fell below the out-of-fold precision threshold | Check `ValidationStatus`, `ValidationPrecision`, and `ValidationCoverage`; collect more resolved examples or keep the rule disabled |
| A learned term contains a sensitive business term | Redaction reduces common PII but cannot identify every customer-specific term | Disable or remove the term and keep all outputs inside the customer environment |
| Approved rules do not appear in the report | The edited CSV was not supplied on the second run, or `Enabled` is not `true` | Rerun with `--overrides`, then load the newly prepared JSON/CSV and refresh |
| One retained thread contains several business questions | The report has one primary topic per conversation | Use **Start over** so each question is retained as a separate conversation; the tuner still learns from all paired user turns |

## Production validation cycle

1. Start with the built-in classifier and confirm native Copilot Studio topics are present.
2. Export a representative resolved transcript set; for large tenants, use a window that includes ordinary, rare, and seasonally important requests.
3. Run the tuner and promote only `AutoValidated` rules with `ValidationStatus = Passed`.
4. Load the reviewed rules through the applicable report setup and confirm native topics remain unchanged, enabled customer rules classify only unresolved rows, ambiguous rows remain unassigned, and topic counts are plausible.
5. If publishing Dataverse V21, use its publication step so the same approved rules are included in the report prepared for Power BI Service.
6. Re-run the tuner after material topic or wording changes. Replace the approved JSON deliberately; do not append every historical candidate indefinitely.

## Sharing guidance

Keep raw transcripts and all tuner outputs inside the customer environment. If taxonomy help is needed, the smallest useful package is the reviewed `customer-topic-overrides.csv`, `topic-learning-audit.csv`, and `privacy-report.json`; all still require customer review and approval before sharing.
