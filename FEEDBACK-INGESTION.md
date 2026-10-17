# Microsoft 365 Copilot feedback: export, prepare, and load

ESS Insights reads reactions stored in Dataverse transcripts automatically. Microsoft 365 Copilot and exported Copilot Studio Monitor reactions use a separate export because they are not written to the same transcript records.

| Channel/source | Stored source | How to add it |
|---|---|---|
| Copilot Studio channels with Dataverse transcripts | Reaction activity inside `ConversationTranscript.Content` | No extra input; parsed automatically |
| Copilot Studio agents used in Microsoft 365 Copilot | Microsoft 365 admin center **Health -> Product feedback** export | Dataverse guided setup accepts the raw export; CSV and Fabric use the preparation steps below |
| Copilot Studio Monitor | Exported reaction CSV | Dataverse guided setup accepts the raw export; CSV and Fabric use the same preparation steps below |

The Microsoft 365 export is tenant-wide and can contain feedback from many products and agents. ESS Insights includes only rows whose **Agent ID** matches an enabled `M365Title` alias in the agent registry. Blank or unmatched Agent IDs are excluded and are never inferred from the user, time, prompt, response, or app.

> [!IMPORTANT]
> The export can contain comments, prompts, responses, user identifiers, and diagnostics. Keep it in an approved customer-controlled location. Preparation runs locally and makes no network calls.

Microsoft documentation:

- [Understand downloaded Copilot Studio conversation transcripts](https://learn.microsoft.com/en-us/microsoft-copilot-studio/analytics-transcripts-powerapps)
- [Learn about Microsoft feedback for your organization](https://learn.microsoft.com/en-us/privacy/microsoft-365/feedback/feedback-overview)

## Before you start

All paths need:

- an administrator or reader account that can open **Product feedback** in the Microsoft 365 admin center;
- a reviewed agent registry CSV or JSON containing the agent's `M365Title` alias; and
- an approved customer-controlled folder such as `C:\AgentData`.

All Microsoft 365 administrators and readers can view and export Product feedback. Only Compliance Administrators and Global Administrators can see user identity details and delete feedback. Use the least-privileged role that meets your needs.

**Dataverse Direct:** use the [guided Dataverse setup](SETUP-Dataverse.md#action-2---run-the-guided-setup-and-validate-the-report). Select the reviewed registry and raw feedback exports; do not prepare a JSON file first.

**CSV or Fabric:** download and extract the [complete ESS package](https://github.com/microsoft/ESS/archive/refs/heads/main.zip). These paths use the included local preparation tool after export.

## Step 1 - Identify the Microsoft 365 Agent ID

Skip this step if the registry already has a working `M365Title` row for the agent.

1. Publish the Copilot Studio agent to Microsoft 365 Copilot.
2. Open that agent in Microsoft 365 Copilot.
3. Ask a harmless test question that contains no private information.
4. Select **Thumbs up** or **Thumbs down** on the response.
5. If a comment box appears, enter a unique marker such as `ESS feedback setup YYYY-MM-DD`. Do not include customer, employee, or case information.
6. Wait for the item to appear in the Microsoft 365 Product feedback list.
7. Export Product feedback by following Step 2 and open the downloaded CSV.
8. Find the row by its unique comment, submitted time, or test prompt.
9. In **Agent ID**, copy only the value beginning with `T_`.
10. Add a registry row with `AliasType` set to `M365Title` and `AliasValue` set to that `T_...` value. Reuse the agent's approved `AgentKey`, `AgentLabel`, environment fields, and scope flags.
11. Review the registry by following [Agent registry and reporting scope](AGENT-REGISTRY.md).

Do not use `App = M365 Chat` as proof of agent ownership. Standard Copilot Chat and other custom agents can use the same app value.

If the controlled row has a blank Agent ID, the export cannot safely identify the receiving agent. Exclude it.

## Step 2 - Export Product feedback

1. Sign in to the [Microsoft 365 admin center](https://admin.microsoft.com).
2. If **Health** is not visible, select **Show all** or customize the navigation.
3. Select **Health -> Product feedback**.
4. Wait for the list to load.
5. Select **Export** or **Export to CSV**.
6. Save the CSV in the approved customer-controlled folder.

The downloaded file remains tenant-wide even when the page is filtered. Do not load it directly into Power BI or Fabric.

If Copilot Studio Monitor also provides a reaction export, save that CSV in the same approved folder.

## Step 3 - Prepare and load for your path

### Dataverse Direct

1. Open the extracted ESS package and run the guided Dataverse setup again.
2. Reuse the saved Environment URL.
3. Choose to add or replace data.
4. Select the reviewed registry CSV or JSON under **Agent registry**.
5. Select the raw Product Feedback export when asked for Microsoft 365 feedback.
6. Add the Monitor export when available.
7. Open and refresh the prepared report.
8. On **Agent Feedback**, confirm the cross-channel totals and verdicts are plausible.

The guided setup filters, deduplicates, validates, and embeds matching rows locally. Product Feedback requires an approved registry match. A Monitor reaction uses a registry Bot/Agent ID when present; otherwise the report includes it only after its exported Conversation ID matches one exact loaded conversation. Rows with neither form of identity are excluded.

If the report will be published, follow [Build and publish the Service report](SETUP-Dataverse.md#action-3---build-and-publish-the-service-report) after the Desktop result is correct.

### CSV V18 or Fabric V2

Confirm Python 3.10 or later from the extracted `ESS-main` folder:

```powershell
python --version
```

Then prepare one or more raw exports:

```powershell
python tools\ess_feedback_normalizer.py `
  --input "C:\AgentData\ProductFeedback.csv" `
  --agent-registry "C:\AgentData\agent-registry.csv" `
  --scope-mode "ESS Safe" `
  --output "C:\AgentData\feedback-events.csv"
```

For a Monitor export, add another input:

```powershell
python tools\ess_feedback_normalizer.py `
  --input "C:\AgentData\ProductFeedback.csv" `
  --input "C:\AgentData\MonitorReactions.csv" `
  --agent-registry "C:\AgentData\agent-registry.csv" `
  --scope-mode "ESS Safe" `
  --output "C:\AgentData\feedback-events.csv"
```

The command creates:

| File | Use |
|---|---|
| `feedback-events.csv` | Upload to Fabric |
| `feedback-events.json` | Paste into CSV V18 |
| `feedback-events.audit.json` | Review before loading |

The tool includes only registry-approved Product Feedback Agent IDs, maps each `T_...` value to the canonical `AgentKey`, normalizes verdicts, and removes duplicate event IDs.

Check the audit before loading:

- `outputFeedbackEvents` is greater than zero when matching feedback is expected;
- `productFeedbackRowsIncludedByAllowlist` is the expected number of agent rows;
- excluded-without-ID and outside-allowlist counts are plausible; and
- `duplicatesRemoved` is plausible.

Do not switch to `All Agents` to bypass a no-match result. Confirm the controlled row's `T_...` value and the registry alias.

#### Load into CSV V18

1. Open the report in Power BI Desktop.
2. Select **Home -> Transform data -> Edit parameters**.
3. Paste the full reviewed registry JSON into **Agent Registry JSON**.
4. Paste the full `feedback-events.json` contents into **Feedback Events JSON (optional)**.
5. Select **OK**, refresh, and confirm **Agent Feedback**.

#### Load into Fabric V2

1. In the Lakehouse attached to the transcript-parser notebook, create `Files/feedback` if needed.
2. Upload `feedback-events.csv` to `Files/feedback/feedback-events.csv`.
3. Run all cells in `Copilot_Agent_Transcript_Parser.ipynb`.
4. Confirm expected mapped rows in `user_feedback`.
5. Review `user_feedback_quarantine`; it contains identifiers only for unmapped rows.

## Step 4 - Refresh the feedback snapshot

The Product feedback export is a snapshot, not a live connection.

- **Dataverse Direct:** export the latest CSV, rerun guided setup, select the registry and new raw export, then refresh the newly prepared report.
- **CSV V18:** rerun the preparation command, replace the JSON parameter, and refresh.
- **Fabric V2:** rerun preparation, replace `Files/feedback/feedback-events.csv`, and rerun the transcript notebook.

This repository does not include a process that signs in to the Microsoft 365 admin center or downloads Product feedback automatically.

## Common issues

| Symptom | Cause | Fix |
|---|---|---|
| **Health** or **Product feedback** is missing | Navigation is collapsed or the account lacks an administrator/reader role | Select **Show all** and confirm the account role |
| Test feedback is not listed yet | Feedback has not reached the admin center | Wait several minutes, refresh, and confirm the reaction came from the published agent |
| Agent ID is blank | The export cannot identify the receiving agent | Exclude the row; do not infer the agent |
| No Product Feedback rows match | Registry has the wrong or missing `M365Title` alias | Recheck the controlled row and copy only the `T_...` value |
| PowerShell says `python` is not recognized | Python is unavailable for the CSV/Fabric preparation path | Install Python 3.10+ with **Add Python to PATH**, then reopen PowerShell |
| Power BI shows old feedback | The latest guided report, JSON parameter, or Fabric CSV was not loaded | Replace the applicable prepared input and refresh |

## Attribution boundary

Microsoft 365 Product Feedback proves which published agent received a reaction when Agent ID is populated. It does not provide the supported conversation identifier needed to link that reaction to one exact transcript turn or child agent. Report it at agent level; keep per-conversation and child-agent attribution separate.

`SampleData/feedback-events.csv` and `SampleData/feedback-events.json` contain fabricated examples for testing.
