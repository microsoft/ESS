# Private topic tuner

`tools/ess_topic_tuner.py` helps customers find repeated gaps in a Copilot Studio topic taxonomy without sending conversation transcripts outside their environment. It is agent-agnostic, uses only the Python standard library, and makes no network, LLM, or external API calls.

Topic overrides apply to every agent included in the current report scope. For substantially different agent domains, use **Selected Agents** while reviewing candidates or maintain a shared taxonomy whose rules are valid across all included agents.

## Download the tuner

[Download the complete ESS package as a ZIP](https://github.com/microsoft/ESS/archive/refs/heads/main.zip), select **Extract All**, and run the commands in this guide from the extracted `ESS-main` folder. The package includes:

- `tools/ess_topic_tuner.py`;
- `tools/topic_classifier.py`; and
- `taxonomy/topics-taxonomy.csv`.

> Do not download `ess_topic_tuner.py` by itself. It imports the companion classifier and loads the shared taxonomy using repository-relative paths.

## What it produces

| File | Purpose | Contains transcript text? |
|---|---|---|
| `customer-topic-overrides.csv` | Review queue for candidate keywords and approved customer rules | No full prompts; candidate terms can still be sensitive |
| `customer-topic-overrides.json` | Enabled rules ready to paste into CSV/Dataverse templates | No |
| `topic-enrichment.csv` | Hashed conversation key plus assigned topic and confidence | No |
| `classification-audit.csv` | Hashed conversation key plus rule, score, ambiguity, and version diagnostics | No |
| `privacy-report.json` | Aggregate counts, suppression threshold, and redaction summary | No |

> **Privacy boundary:** the tool removes common email, URL, phone, GUID, IP-address, and long-number patterns before candidate extraction and suppresses terms below the minimum frequency. This reduces exposure but does not guarantee anonymity: repeated project names or other business-sensitive terms can still become candidates. Review all output locally before sharing it.

## Before you start

You need:

- the [complete ESS package](https://github.com/microsoft/ESS/archive/refs/heads/main.zip) downloaded and extracted;
- a raw Dataverse `ConversationTranscript` CSV;
- Python 3.10 or later; and
- an approved customer-controlled output folder.

Use the transcript export steps in [CSV setup - Step 1](SETUP-CSV-Download.md#step-1--export-your-conversation-transcripts--required). Do not open or save the transcript CSV in Excel because Excel can corrupt the JSON in its `Content` column.

### Confirm Python

1. Open the unzipped ESS repository folder in File Explorer.
2. Click the address bar, type `powershell`, and press **Enter**.
3. Run:

```powershell
python --version
```

The expected result is `Python 3.10` or later. If Windows says that Python is not recognized, install Python from [python.org](https://www.python.org/downloads/windows/), select **Add Python to PATH** during setup, close PowerShell, and repeat these steps.

No Python packages need to be installed.

## 1. Run the first review

A raw Dataverse `ConversationTranscript` CSV is detected automatically. From the PowerShell window opened above, run:

```powershell
python tools\ess_topic_tuner.py `
  --input "C:\AgentData\ConversationTranscripts.csv" `
  --output-dir "C:\AgentData\topic-review" `
  --min-frequency 5
```

Replace the input path with the full path to your transcript CSV. The output folder is created automatically. A successful run prints a summary and creates the five files listed above.

The tool also accepts a flat CSV containing a first-user-prompt column such as `first_user_prompt`, `FirstUserMessage`, or `Prompt`. Use `--prompt-column`, `--locale-column`, `--id-column`, or `--native-topic-column` when the column names are different.

Rows with a native Copilot Studio topic remain native. Candidate extraction only examines non-ambiguous conversations that the shared classifier leaves uncategorized.

## 2. Review candidates

Open `C:\AgentData\topic-review\customer-topic-overrides.csv` and review each candidate. This output is safe to open in Excel because it does not contain the raw transcript JSON.

1. Set `Vertical` and `CanonicalTopic` to the approved business labels.
2. Edit `Keywords` and add any `Exclusions` needed to prevent collisions.
3. Keep `Priority` above the matching built-in rule when the customer rule should win; generated candidates default to `110`.
4. Change `Enabled` to `true` only after review.

Do not enable a row with blank `Vertical`, `CanonicalTopic`, or `Keywords`.

Keep labels short and understandable to report users. Avoid customer names, employee names, case numbers, and other identifying values in `CanonicalTopic`, `Keywords`, and `Exclusions`.

## 3. Re-run with approved rules

```powershell
python tools\ess_topic_tuner.py `
  --input "C:\AgentData\ConversationTranscripts.csv" `
  --overrides "C:\AgentData\topic-review\customer-topic-overrides.csv" `
  --output-dir "C:\AgentData\topic-review-approved" `
  --min-frequency 5
```

The second run tests the approved rules and writes `customer-topic-overrides.json` containing only enabled rules.

Before loading the rules, check:

- `privacy-report.json` for the number of processed, redacted, and suppressed items;
- `classification-audit.csv` for unexpected collisions or ambiguous matches; and
- `topic-enrichment.csv` for the resulting topic counts by hashed conversation key.

Do not share these files outside the customer environment without customer review.

## 4. Apply without a template release

### CSV V18 and Dataverse V19

Open **Transform data → Edit parameters** and paste the full contents of `customer-topic-overrides.json` into **Customer Topic Overrides JSON (optional)**. Refresh the model. Because the override is a parameter, it does not add a second data source or create a Formula Firewall dependency.

### Fabric V2

Upload the reviewed `customer-topic-overrides.csv` to:

```text
Files/config/customer-topic-overrides.csv
```

Run `Copilot_Agent_Transcript_Parser.ipynb`. The notebook reads only rows where `Enabled` is true, gives them `RuleSource = Customer`, and writes the classifier version with a `+CUSTOMER` suffix. If the file is absent, the notebook uses only the built-in taxonomy.

## Common issues

| Symptom | Cause | Fix |
|---|---|---|
| `python: can't open file 'tools\ess_topic_tuner.py'` | PowerShell is open in the wrong folder, or only the script was downloaded | Open PowerShell from the extracted `ESS-main` folder and keep the complete package structure intact |
| PowerShell says `python` is not recognized | Python is not installed or not on PATH | Install Python 3.10+ with **Add Python to PATH**, then reopen PowerShell |
| `Input file not found` | The transcript path is incomplete or mistyped | In File Explorer, Shift+right-click the file and select **Copy as path**, then paste that path after `--input` |
| No candidate rules are produced | Repeated terms did not meet `--min-frequency`, or conversations already have native/derived topics | Review the privacy report; if appropriate, rerun with a lower value such as `3` |
| A candidate contains a sensitive business term | Redaction reduces common PII but cannot identify every customer-specific term | Leave it disabled, remove the term, and keep all outputs inside the customer environment |
| Approved rules do not appear in the report | The edited CSV was not supplied on the second run, or `Enabled` is not `true` | Rerun with `--overrides`, then load the newly generated JSON/CSV and refresh |

## Sharing guidance

Keep raw transcripts, `topic-enrichment.csv`, and `classification-audit.csv` inside the customer environment. If taxonomy help is needed, the smallest useful package is the reviewed `customer-topic-overrides.csv` plus `privacy-report.json`; both still require customer review and approval before sharing.
