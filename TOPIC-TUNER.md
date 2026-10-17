# Optional Dataverse V21 topic tuning

The local tuner reports one of three outcomes. Only approved, non-empty rules can change the template.

| Outcome | What you do |
|---|---|
| **READY** | The tool automatically builds and opens a new Desktop Validation PBIT with approved rules embedded. No second run or JSON import. |
| **REVIEW REQUIRED** | Review only `customer-topic-overrides.csv`, then press Enter in the same window to validate and build. |
| **STOP** | No useful rules were produced. Keep the existing template unchanged. Do not import the empty JSON. No apply command is offered. |

## What the tool can and cannot learn

Read this before running anything:

- It can learn recurring terminology from conversations with usable native Copilot Studio topic evidence and match similar conversations without native topics.
- Repeated unlabeled phrases are **disabled candidates**, not authoritative business topics. The customer must supply their meaning.
- It cannot invent trustworthy business labels from 500 completely unlabeled conversations or guarantee that every unclassified conversation will receive a topic.
- Native topics remain authoritative. Weak or ambiguous mappings are not automatically enabled. Customer rules take precedence over built-in rules only when no native topic exists.
- English customer rules include explicit singular/plural alternatives for a small vocabulary, including **ticket/tickets**, **device/devices**, and **policy/policies**. Evidence is combined before validation; exclusions receive the same alternatives. This is not general fuzzy matching, synonym generation, or support for every inflection.

Keyword and exclusion alternatives are serialized in their normalized matching form and deduplicated. Capitalization, equivalent punctuation, or repeated spellings do not multiply match scores. Singular/plural expansion applies only to the supported English vocabulary.

Python and the embedded Power Query classifier use the same fixed Unicode 16.0 punctuation and whitespace separator table, independent of the installed Python version. It includes curly quotes and Unicode dashes. Rules whose keywords become empty after normalization are rejected, including saved rules and direct apply/build inputs. Rule locales use language prefixes: for example, `en-US` and `en-GB` both become `en`; a blank rule locale becomes `*`.

Skip tuning if existing topics already cover your conversations. One conversation about **holidays**, already classified as **HR / Time Off & Attendance**, produces no customer rule and cannot demonstrate an improvement.

## Before you start

Use the [complete ESS package](https://github.com/microsoft/ESS/archive/refs/heads/main.zip), Python 3.10 or later, and a customer-controlled output folder. No additional Python packages are required. Complete the [Dataverse baseline setup](SETUP-Dataverse.md) first, using the same extracted package. It saves your URL and optional inputs in `Generated Templates/dataverse-setup.json`.

The tuner processes data locally using the standard library. It makes no network, LLM, or external API calls. It cannot repair missing permissions, expired transcripts, or the wrong environment URL.

## 1. Export representative conversations

1. In [Power Apps](https://make.powerapps.com), select the report's environment.
2. Select **Tables -> All**, find **ConversationTranscript**, then select **Export -> Export data**.
3. Download and extract the export. Keep the CSV in a customer-controlled folder.

Do not open or save this transcript CSV in Excel; doing so can corrupt the JSON in its Content column. Include repeated native-labeled examples and matching unresolved conversations. The default automatic gate needs at least five distinct supporting conversations, not five turns in one conversation. Use **Start over** between test conversations.

## 2. Run one local tool

1. Open the extracted ESS folder in File Explorer. If an outer folder such as `ESS-main (3)` contains another `ESS-main`, open the inner folder. The correct folder directly contains `tools`, `START-HERE-DATAVERSE.cmd`, and `TUNE-TOPICS.cmd`.
2. Double-click **TUNE-TOPICS.cmd** and select the exported transcript CSV.

The tool reuses saved setup choices without asking you to select customer files again. It explains its limits, analyzes the export, and follows one of the outcomes below. No PowerShell command is required. Review outputs go beside the saved setup in `Generated Templates/Topic Review`.

Each analysis validates and loads the previously approved rules selected in saved setup. New approved rules are merged with those rules, not substituted for them. A missing, invalid, or empty saved rules file stops analysis before outputs are written; restore that file rather than silently starting over. Previously approved rules also remain enabled in the review CSV unless you deliberately change them during review.

If the output folder already contains files, the next run writes to a new `run-*` subfolder. Follow the printed review-file path for that run. Existing approved rules and review files are never overwritten by a later analysis, including STOP and review-only runs; saved setup continues to reference the previously applied rules until another build succeeds.

If Python is missing, install Python 3.10 or later from [python.org](https://www.python.org/downloads/windows/) with **Add Python to PATH**, then reopen the launcher.

## 3. Follow your outcome

### READY

The tool states how many rules are approved, builds the new PBIT, and opens it automatically in this run. If disabled review items also exist, they are excluded; only approved rules are applied.

The apply action:

- validates that the approved JSON is non-empty;
- calls guided Dataverse setup with `--topic-overrides-json`, without a setup interview;
- reuses the saved customer URL, registry, organization, credits, and feedback inputs;
- replaces only the saved topic-rule selection;
- creates **Desktop Validation - Topics - DO NOT PUBLISH.pbit** in **Generated Templates**, leaving the baseline Desktop Validation PBIT untouched; and
- opens the new PBIT in Power BI Desktop.

**Do not browse for the JSON in Power BI, add it as a data source, enter its path on a data-source page, or edit report parameters manually.** Its contents are embedded. Refresh does not require the local JSON. Keep the saved inputs available if you want to rebuild or prepare a Service template later.

### REVIEW REQUIRED

No rules are ready yet. Open only the printed `customer-topic-overrides.csv` path. Do not edit the raw transcript export.

1. Supply or confirm **Vertical** and **CanonicalTopic** using customer-approved business labels.
2. Adjust **Keywords** or **Exclusions** if needed. Separate alternatives with `|`.
3. Set **Enabled=true** only for rules you approve. Leave ambiguous or weak rows disabled.
4. Keep the other columns, save the CSV, and close the editor.
5. Return to the same tool window and press **Enter** to validate and build. Type **skip** instead to leave the template unchanged.

The same session validates enabled rows, creates a uniquely named `approved-*.json` candidate beside the CSV, and applies it through the saved-settings path described under READY. It never overwrites previously approved JSON. Saved setup references the new candidate only when the build and publication succeed. Failed inactive candidates are removed; if saved settings cannot be verified or rollback fails, the error identifies the retained candidate for recovery. It does not rerun learning or require another transcript export. Invalid enabled rows stop the action with an error. If no rows are enabled, it stops without building or opening a template. The printed `--review` command is only a recovery option if you close or skip the session; noninteractive runs also print it instead of waiting.

Customer review supplies meaning; this is not automatic validation of a newly invented label. Test the resulting rule against both matching and unrelated conversations.

### STOP

Do not change the template. A JSON file containing `[]` is not an actionable result and cannot be applied by the tool.

The message explains the reason and what would be needed next:

- **No unclassified rows:** native or built-in topics already cover this export; keep the baseline.
- **Insufficient repeated evidence:** collect more distinct conversations with consistent terminology.
- **Ambiguity:** collect native-labeled examples that distinguish the different meanings; do not force a label.
- **No usable native topic evidence:** include conversations with meaningful native topic evidence for automatic learning. Repeated unlabeled phrases can only become candidates for customer review.

## 4. Refresh and verify the improvement

In the newly opened **Desktop Validation - Topics - DO NOT PUBLISH.pbit**, wait for the prefilled values to stabilize, select **Load**, authenticate if needed, and select **Home -> Refresh**. Do not add the transcript CSV or rules JSON as a data source. Dataverse remains the transcript source.

Use the same environment and retained conversation IDs as your baseline. On **Conversation Details**, verify that intended previously unclassified conversations now receive the approved topic. Confirm native topics are unchanged and unrelated conversations have not moved into the customer topic. Review **Improvement Opportunities**, **Adjust Topic Assumptions**, and the **Glossary** load diagnostics. Unmatched or ambiguous conversations may legitimately remain unclassified.

The improvement comes from the embedded keyword/exclusion mappings, not from importing the enrichment CSV or editing the template's built-in taxonomy. An already-open report is not modified. Later apply runs replace the Topics validation file; save a validated report as PBIX when you need to retain it.

After Desktop validation, use `BUILD-SERVICE-REFRESH.cmd` if shared Service access is required. It reuses the saved approved rules. Desktop success and Python tests do not prove Power BI Service refresh; validate the published semantic model separately.

## Troubleshooting

| Message or symptom | Action |
|---|---|
| No saved Dataverse setup | Complete the baseline once in this package, then open the topic launcher. Do not substitute another tenant's settings. |
| A saved optional file is missing or invalid | Restore that saved input and retry. The tool does not silently clear or skip unrelated inputs. |
| No approved rules | Keep the template unchanged; empty JSON is never imported. For review items, approve only rows whose business meaning is known. |
| File cannot be found | Confirm the inner package folder and the full transcript path. File Explorer's **Copy as path** can help. |
| A generated PBIT cannot be replaced | Close that Topics validation report before retrying; retain your baseline PBIX. |

## Technical Reference

Automatic rules retain the existing safety gates: at least five distinct supporting conversations, at least 90% cross-topic precision, and deterministic five-fold conversation-level validation with at least three correct held-out matches and 90% precision. Do not lower these thresholds merely to force output.

Analysis merges saved approved JSON, enabled rows from an explicit `--overrides` CSV, and newly validated rules. Equivalent rules have the same locale and the same normalized keyword and exclusion sets. For those conflicts, explicit overrides take precedence over saved approvals, which take precedence over newly learned rules. Within one source, higher priority wins, then stable topic/vertical ordering breaks ties. Rules with distinct match conditions are retained. The review CSV and approved JSON use the same merged approvals, and successful publication embeds that full JSON in the PBIT. Carrying forward existing approvals alone does not trigger another build; runs without new or updated approvals still report STOP or REVIEW REQUIRED and leave active setup unchanged.

Publication checks compare the desired rule payload with the raw validated saved JSON, before expansion or normalization. Expanding an older singular-only rule to include its plural variant is a publication change: it reports READY and rebuilds the PBIT even without newly learned rules. An unchanged follow-up run does not republish.

The automated tests check the source PBIT's applied and pending Power Query expressions against the generator. A separate cross-runtime regression evaluates the generated customer-rule query and classifier with Microsoft's standalone `PQTest.exe` and compares results with Python, including Unicode punctuation, regional locales, deduplication, and invalid normalized keywords. Put `PQTest.exe` on PATH or set `ESS_PQTEST` to its executable path before running the tests. Without that runtime, this regression explicitly skips; the other tests do not establish M execution parity. No Desktop or Service interaction is needed for this standalone test.

The direct CLI also analyzes and builds in one invocation:

```powershell
python .\tools\ess_topic_tuner.py --input "C:\AgentData\ConversationTranscripts.csv" --output-dir "C:\AgentData\topic-review"
```

Use `--analyze-only` to generate rules without building or opening a template. For automation, `--json` implies analysis-only and prints the report with an `outcome` object, without prompts or subprocess output. `--settings-file` selects a specific saved setup; recovery commands preserve that selection. `--no-open` builds without launching Desktop. Existing flat-input column options and `--overrides` remain supported; `--apply` and `--review` remain available as recovery actions. The launcher accepts `--topic-transcripts "C:\AgentData\ConversationTranscripts.csv"` to bypass its file picker.

`--json` and `--analyze-only` cannot be combined with either `--apply` or `--review`; these invalid combinations stop before writing files or changing saved setup. Use `--non-interactive` to suppress the review prompt even when running in a terminal. The launcher forwards this flag to the tuner and requires `--topic-transcripts` instead of a file picker. Review-required runs print a recovery command without applying anything; an interactive review session that receives end-of-input also leaves the template unchanged.

The PBIT destination must not be an input file. The tuner and guided setup compare resolved paths case-insensitively using Windows path normalization and reject collisions before creating analysis outputs, rule candidates, or staging files. Protected paths include the base PBIT, transcripts, taxonomy, prior overrides, reviewed CSV, applied and saved rules JSON, settings, registry, organization, credit, and feedback files. Choose a separate output path when the error identifies a conflicting input.

The PBIT also cannot replace any of the six tuner outputs: `topic-enrichment.csv`, `classification-audit.csv`, `topic-learning-audit.csv`, `customer-topic-overrides.csv`, `customer-topic-overrides.json`, or `privacy-report.json`. These destinations are checked before analysis and checked again in the selected output folder, including any new `run-*` folder, before diagnostics are written.

Prepared feedback has three destinations: `feedback-events.csv`, `feedback-events.json`, and `feedback-events.audit.json`. The PBIT cannot replace any of them. When raw feedback exports are supplied, all three destinations are checked against the protected inputs and final PBIT before normalization, analysis, or rule-candidate writes. The standalone feedback normalizer also rejects destinations that conflict with its raw inputs, registry, or another output, including a custom audit path. A collision error identifies the conflicting path and leaves the inputs unchanged.

Template publication builds and validates a staged PBIT in the destination directory, then prepares validated settings in the settings directory. Settings are replaced first; if template replacement fails, the original settings are restored byte-for-byte. A settings-commit failure leaves the existing template untouched. Staging and backup files are cleaned after success or handled failure. If settings rollback itself fails, the explicit error identifies the settings artifact and retains its original backup for recovery. Standalone settings saves also use atomic replacement. This handles application-level failures, not process termination, power loss, or concurrent writers across the two-file commit. Desktop opening happens after publication; an opening error reports that the files were saved and asks you to open the PBIT manually.

These files remain available for diagnostics, not as a customer checklist:

| File | Purpose |
|---|---|
| `customer-topic-overrides.csv` | The only customer review file; enabled rules plus disabled candidates |
| `customer-topic-overrides.json` | Enabled rules only; the apply action embeds the contents |
| `approved-*.json` | Unique reviewed-rule candidate; saved setup references it only after successful publication |
| `topic-enrichment.csv` | Hashed conversation keys and predicted topics |
| `classification-audit.csv` | Matching, ambiguity, source, and classifier diagnostics |
| `topic-learning-audit.csv` | Native evidence and held-out validation metrics |
| `privacy-report.json` | Aggregate counts, redactions, and the workflow outcome |

Redaction removes common email, URL, phone, GUID, IP-address, and long-number patterns before learning. It does not guarantee anonymity: repeated business terms and short phrases can still be sensitive. Keep transcripts and outputs inside the customer environment and review them before sharing.

Rules apply across the report's selected agent scope. Use rules valid across that scope. This apply action targets **Dataverse V21 only**. Fabric can still consume enabled rows from the reviewed CSV at `Files/config/customer-topic-overrides.csv`; see [Fabric setup](SETUP-Fabric.md). CSV V18 users should follow their separate setup rather than running the Dataverse apply action.
