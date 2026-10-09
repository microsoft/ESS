# Microsoft 365 Copilot feedback: export, prepare, and load

ESS Insights uses two stored feedback sources because reactions from Microsoft 365 Copilot Chat are not written to Dataverse conversation transcripts.

| Channel/source | Stored source | ESS Insights path |
|---|---|---|
| Copilot Studio channels with Dataverse transcripts | Reaction activity inside `ConversationTranscript.Content` | Parsed automatically |
| Copilot Studio agents used in Microsoft 365 Copilot | Microsoft 365 admin center **Health → Product feedback** export | Prepare with `ess_feedback_normalizer.py` |
| Copilot Studio Monitor reaction export | Exported CSV | Prepare with the same tool |

The Microsoft 365 export can include feedback from many products and agents. ESS Insights includes only rows whose **Agent ID** matches an enabled agent in your registry. A blank Agent ID cannot be safely attributed to ESS and is excluded.

Microsoft documentation:

- [Understand downloaded Copilot Studio conversation transcripts](https://learn.microsoft.com/en-us/microsoft-copilot-studio/analytics-transcripts-powerapps)
- [Learn about Microsoft feedback for your organization](https://learn.microsoft.com/en-us/privacy/microsoft-365/feedback/feedback-overview)

## Before you start

You need:

- the [complete ESS package](https://github.com/microsoft/ESS/archive/refs/heads/main.zip) downloaded and extracted;
- Python 3.10 or later;
- an administrator or reader account that can open **Product feedback** in the Microsoft 365 admin center;
- `agent-registry.csv` with the ESS agent's `M365Title` alias; and
- an approved customer-controlled folder such as `C:\AgentData`.

All Microsoft 365 administrators and readers can view and export Product feedback. Only Compliance Administrators and Global Administrators can see user identity details and delete feedback. Use the least-privileged role that meets your needs.

> The export can contain comments, prompts, responses, user identifiers, and diagnostics. Store it only in an approved customer-controlled location. The preparation script runs locally and makes no network calls.

> Keep the package structure intact and run the command from the extracted `ESS-main` folder. Do not download `ess_feedback_normalizer.py` by itself; it imports `tools/agent_registry.py`.

## Step 1 - Confirm Python

1. Open the extracted `ESS-main` folder in File Explorer.
2. Click the address bar, type `powershell`, and press **Enter**. A PowerShell window opens in the correct folder.
3. Run:

```powershell
python --version
```

The expected result is `Python 3.10` or later. If Windows says that Python is not recognized, install Python from [python.org](https://www.python.org/downloads/windows/), select **Add Python to PATH** during setup, close PowerShell, and repeat these steps.

No Python packages need to be installed.

## Step 2 - Identify the ESS Microsoft 365 Agent ID

Skip this step if `agent-registry.csv` already has a working `M365Title` row for the agent.

1. Publish the Copilot Studio agent to Microsoft 365 Copilot.
2. Open that agent in Microsoft 365 Copilot.
3. Ask a harmless test question that contains no private information.
4. Select **Thumbs up** or **Thumbs down** on the response.
5. If a comment box appears, enter a unique marker such as `ESS feedback setup YYYY-MM-DD`. Do not include customer, employee, or case information.
6. Wait for the item to appear in the Microsoft 365 Product feedback list. This can take several minutes.
7. Complete Step 3 and open the downloaded CSV.
8. Find the row by its unique comment, submitted time, or test prompt.
9. Copy the value from **Agent ID**. It is normally stored as a JSON-style value such as `["T_example"]`; copy only the value beginning with `T_`.
10. Add a row to `agent-registry.csv` with `AliasType` set to `M365Title` and `AliasValue` set to that `T_...` value. Use the same `AgentKey`, `AgentLabel`, environment fields, and scope flags as the agent's transcript alias.
11. Validate the registry by following [Build and validate the registry](AGENT-REGISTRY.md#step-7---build-and-validate-the-registry).

> **Do not use `App = M365 Chat` as proof of ESS ownership.** Standard Copilot Chat and other custom agents can use the same app value. The `T_...` Agent ID is the supported agent-level filter for this workflow.

If the controlled test row has a blank Agent ID, the export does not provide enough information to attribute that reaction to ESS. Do not guess from the user, time, prompt, response, or app name.

## Step 3 - Export Product feedback from Microsoft 365

1. Sign in to the [Microsoft 365 admin center](https://admin.microsoft.com).
2. If **Health** is not visible in the left navigation, select **Show all** or customize the navigation to display it.
3. Select **Health → Product feedback**.
4. Wait for the feedback list to load.
5. Select **Export** or **Export to CSV** on the command bar.
6. Save the downloaded CSV as:

```text
C:\AgentData\ProductFeedback.csv
```

The downloaded file is tenant-wide even when the page is filtered. The local preparation step below is therefore required; do not load the raw export directly into Power BI or Fabric.

If Copilot Studio Monitor also provides a reaction export for the agent, save that CSV in the same folder. You can provide both files to the preparation command.

## Step 4 - Prepare and filter the export

From the PowerShell window opened in Step 1, run:

```powershell
python tools\ess_feedback_normalizer.py `
  --input "C:\AgentData\ProductFeedback.csv" `
  --agent-registry "C:\AgentData\agent-registry.csv" `
  --scope-mode "ESS Safe" `
  --output "C:\AgentData\feedback-events.csv"
```

If you also have a Copilot Studio Monitor reaction export, add another input:

```powershell
python tools\ess_feedback_normalizer.py `
  --input "C:\AgentData\ProductFeedback.csv" `
  --input "C:\AgentData\MonitorReactions.csv" `
  --agent-registry "C:\AgentData\agent-registry.csv" `
  --scope-mode "ESS Safe" `
  --output "C:\AgentData\feedback-events.csv"
```

The command creates three files:

| File | Use |
|---|---|
| `feedback-events.csv` | Upload to Fabric |
| `feedback-events.json` | Paste into CSV V18 or Dataverse V19 |
| `feedback-events.audit.json` | Review before loading |

The tool:

- recognizes the current Microsoft 365 Product Feedback export and common Monitor reaction columns;
- includes only Product Feedback Agent IDs allowed by the selected registry scope;
- maps the Microsoft 365 `T_...` ID to the same agent key used by transcripts and credits;
- converts reactions to **Thumbs Up** or **Thumbs Down**;
- records channel, source, comment, and available identifiers;
- removes duplicate external rows with the same feedback event ID; and
- never sends data to an external service.

## Step 5 - Check the result before loading

Open `feedback-events.audit.json` in Notepad and check:

- `outputFeedbackEvents` is greater than zero when you expect matching feedback;
- `productFeedbackRowsIncludedByAllowlist` is the expected number of ESS rows;
- `productFeedbackRowsExcludedWithoutAgentId` shows how many rows could not be safely attributed;
- `productFeedbackRowsExcludedOutsideAllowlist` shows how many tenant rows belonged to other agents; and
- `duplicatesRemoved` is plausible.

You can also open `feedback-events.csv` and confirm that `AgentId` contains your customer-defined `AgentKey`, not an unrelated title ID. The prepared CSV may contain prompt, response, and comment text, so keep it in the same approved location as the source export.

If the command says no rows matched, do not switch to `All Agents` to bypass the error. Confirm the controlled feedback row's `T_...` value and the registry's `M365Title` row.

## Step 6 - Load the prepared output

### CSV V18 and Dataverse V19

1. Open the report in Power BI Desktop.
2. Select **Home → Transform data → Edit parameters**.
3. Open `C:\AgentData\feedback-events.json` in Notepad.
4. Select all text, copy it, and paste it into **Feedback Events JSON (optional)**.
5. Select **OK**, then **Home → Refresh**.
6. Open the **Agent Feedback** page and confirm the totals and verdicts are plausible.

The report combines exported events with reactions already present in transcripts. When an exported event has the same exact conversation, agent, and verdict as a transcript reaction, the exported event replaces the duplicate. An agent-matched event without a conversation ID remains visible at agent level but is not guessed onto a conversation.

### Fabric V2

1. In the Fabric workspace, open the Lakehouse attached to the transcript-parser notebook.
2. In the Lakehouse Explorer, open **Files**.
3. Create the `feedback` folder if it does not exist.
4. Upload `feedback-events.csv` to:

```text
Files/feedback/feedback-events.csv
```

5. Run all cells in `Copilot_Agent_Transcript_Parser.ipynb`.
6. Confirm the `user_feedback` table contains the expected mapped rows.
7. Review `user_feedback_quarantine`. It contains identifiers only for unmapped rows; prompts, responses, and comments are not copied there.

## Step 7 - Repeat for each refresh

The Product feedback export is a snapshot, not a real-time connection.

1. Export the latest Product feedback CSV.
2. Replace `C:\AgentData\ProductFeedback.csv`.
3. Run the same preparation command.
4. Replace the JSON parameter in CSV V18/Dataverse V19, or replace the Fabric CSV.
5. Refresh the report.

For an automated Fabric deployment, schedule the approved export and Lakehouse landing process separately. This repository does not include a process that signs in to the Microsoft 365 admin center or downloads the export automatically.

## Common issues

| Symptom | Cause | Fix |
|---|---|---|
| **Health** or **Product feedback** is missing | The navigation is collapsed or the signed-in account is not an administrator/reader | Select **Show all** and confirm the account has an appropriate Microsoft 365 role |
| Test feedback is not listed yet | Product feedback has not reached the admin center | Wait several minutes, refresh the page, and confirm the reaction was submitted from the published agent |
| Agent ID is blank | The export cannot safely identify the receiving agent | Exclude the row; do not infer ESS from app, user, time, prompt, or response |
| `No Microsoft 365 Product Feedback rows matched` | The registry has the wrong or missing `M365Title` alias | Recheck the controlled test row and copy only the `T_...` value |
| PowerShell says `python` is not recognized | Python is not installed or not on PATH | Install Python 3.10+ with **Add Python to PATH**, then reopen PowerShell |
| Power BI shows old feedback | The JSON parameter or Fabric CSV was not replaced | Replace the prepared output and refresh again |

## Attribution boundary

Microsoft 365 Product Feedback proves which published agent received a reaction when Agent ID is populated. The export does not provide the supported conversation identifier needed to link that reaction to one exact transcript turn or child agent. Report it at agent level; keep per-conversation and child-agent attribution separate.

`SampleData/feedback-events.csv` and `SampleData/feedback-events.json` contain fabricated examples for testing.
