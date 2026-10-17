#!/usr/bin/env python3
"""Guide nontechnical users through building validated Dataverse templates."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path

from build_service_refresh_template import normalize_environment_url
from ess_feedback_normalizer import feedback_output_paths, reject_output_collisions


ROOT = Path(__file__).resolve().parents[1]
SOURCE_TEMPLATE = ROOT / "ESS Dashboard - Dynamic Topics (Dataverse) V21.pbit"
BUILDER = ROOT / "tools" / "build_service_refresh_template.py"
FEEDBACK_NORMALIZER = ROOT / "tools" / "ess_feedback_normalizer.py"
GENERATED_DIR = ROOT / "Generated Templates"
DEFAULT_SETTINGS = GENERATED_DIR / "dataverse-setup.json"
PREPARED_FEEDBACK = GENERATED_DIR / "Prepared Inputs" / "feedback-events.csv"
OUTPUT_NAMES = {
    "desktop-validation": (
        "ESS Dashboard - Dynamic Topics (Dataverse) V21 - "
        "Desktop Validation - DO NOT PUBLISH.pbit"
    ),
    "service-refresh": (
        "ESS Dashboard - Dynamic Topics (Dataverse) V21 - "
        "Power BI Service - PUBLISH THIS.pbit"
    ),
}
TOPIC_OUTPUT_NAME = (
    "ESS Dashboard - Dynamic Topics (Dataverse) V21 - "
    "Desktop Validation - Topics - DO NOT PUBLISH.pbit"
)


@dataclass
class SetupOptions:
    environment_url: str
    agent_registry_json: str = ""
    org_data_file: str = ""
    agent_credits_file: str = ""
    topic_overrides_json: str = ""
    feedback_events_json: str = ""
    feedback_input_files: list[str] = field(default_factory=list)


OPTIONAL_FILES = (
    (
        "agent_registry_json",
        "Agent registry",
        "Optional mapping for stable friendly agent names and feedback/credit IDs.",
        (("Registry files", "*.csv *.json"),),
    ),
    (
        "org_data_file",
        "Organization data",
        "Optional user CSV with UPN and available Department, Country, or Job Title.",
        (("CSV files", "*.csv"),),
    ),
    (
        "agent_credits_file",
        "Copilot credit consumption",
        "Optional User-Level Credit Consumption CSV from Power Platform admin center.",
        (("CSV files", "*.csv"),),
    ),
    (
        "topic_overrides_json",
        "Approved topic rules",
        "Optional customer-topic-overrides.json produced by the topic tuner.",
        (("JSON files", "*.json"),),
    ),
)
OPTIONAL_FILE_FIELDS = tuple(item[0] for item in OPTIONAL_FILES) + (
    "feedback_events_json",
    "feedback_input_files",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build validated ESS Dataverse templates through a guided setup."
    )
    parser.add_argument(
        "--mode",
        choices=("desktop-validation", "service-refresh"),
        default="desktop-validation",
    )
    parser.add_argument("--environment-url")
    parser.add_argument("--agent-registry-json", type=Path)
    parser.add_argument("--org-data-file", type=Path)
    parser.add_argument("--agent-credits-file", type=Path)
    parser.add_argument("--topic-overrides-json", type=Path)
    parser.add_argument("--tune-topics", action="store_true", help="Tune an exported transcript CSV using saved setup choices.")
    parser.add_argument("--topic-transcripts", type=Path, help="Optional transcript CSV for --tune-topics; otherwise a file picker opens.")
    parser.add_argument("--feedback-events-json", type=Path)
    parser.add_argument(
        "--feedback-input",
        type=Path,
        action="append",
        default=[],
        help="Raw Product Feedback or Monitor CSV; repeat for multiple exports.",
    )
    parser.add_argument("--output", type=Path)
    parser.add_argument("--settings-file", type=Path, default=DEFAULT_SETTINGS)
    parser.add_argument("--non-interactive", action="store_true")
    opening = parser.add_mutually_exclusive_group()
    opening.add_argument("--no-open", action="store_true")
    opening.add_argument("--open", action="store_true", dest="open_template")
    return parser.parse_args()


def load_settings(path: Path) -> SetupOptions | None:
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    return SetupOptions(
        environment_url=str(payload.get("environment_url") or ""),
        agent_registry_json=str(payload.get("agent_registry_json") or ""),
        org_data_file=str(payload.get("org_data_file") or ""),
        agent_credits_file=str(payload.get("agent_credits_file") or ""),
        topic_overrides_json=str(payload.get("topic_overrides_json") or ""),
        feedback_events_json=str(payload.get("feedback_events_json") or ""),
        feedback_input_files=[
            str(value)
            for value in payload.get("feedback_input_files") or []
            if str(value).strip()
        ],
    )


def setup_input_paths(options: SetupOptions | None) -> list[str]:
    if options is None:
        return []
    return [getattr(options, field_name) for field_name, _, _, _ in OPTIONAL_FILES] + [
        options.feedback_events_json, *options.feedback_input_files,
    ]


def staging_path(path: Path, suffix: str = ".stage") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=suffix, dir=path.parent)
    os.close(descriptor)
    return Path(name)


def save_settings(path: Path, options: SetupOptions) -> None:
    staged = staging_path(path)
    try:
        staged.write_text(json.dumps(asdict(options), indent=2) + "\n", encoding="utf-8")
        load_settings(staged)
        os.replace(staged, path)
    finally:
        staged.unlink(missing_ok=True)


def publish_template(staged_output: Path, output: Path, staged_settings: Path | None = None,
                     settings_file: Path | None = None) -> None:
    backup = None
    settings_committed = False
    publication_committed = False
    retain_backup = False
    try:
        if staged_settings is not None:
            if settings_file is None:
                raise ValueError("A settings destination is required for staged settings.")
            if settings_file.exists():
                backup = staging_path(settings_file, ".backup")
                shutil.copyfile(settings_file, backup)
            os.replace(staged_settings, settings_file)
            settings_committed = True
        os.replace(staged_output, output)
        publication_committed = True
    except OSError as error:
        if settings_committed:
            try:
                if backup is not None:
                    os.replace(backup, settings_file)
                else:
                    settings_file.unlink()
            except OSError as rollback_error:
                retain_backup = True
                recovery = f"Original settings backup retained at {backup}." if backup else "Original settings did not exist; the newly created settings could not be removed."
                raise RuntimeError(f"Template publication failed: {error}. Settings rollback failed for {settings_file}: {rollback_error}. {recovery}") from rollback_error
        raise RuntimeError(f"Template/settings publication failed; existing active files were preserved or restored: {error}") from error
    finally:
        if backup is not None and not retain_backup and not publication_committed:
            backup.unlink(missing_ok=True)
    if publication_committed and backup is not None:
        try:
            backup.unlink(missing_ok=True)
        except OSError as error:
            print(f"WARNING: Template and settings publication succeeded, but backup cleanup failed. Backup retained at {backup}: {error}")


def ask_yes_no(prompt: str, *, default: bool) -> bool:
    suffix = " [Y/n]: " if default else " [y/N]: "
    answer = input(prompt + suffix).strip().lower()
    if not answer:
        return default
    return answer in {"y", "yes"}


def clear_optional_files(options: SetupOptions) -> None:
    for field_name in OPTIONAL_FILE_FIELDS:
        setattr(
            options,
            field_name,
            [] if field_name == "feedback_input_files" else "",
        )


def same_environment(left: str, right: str) -> bool:
    if not left or not right:
        return False
    return normalize_environment_url(left) == normalize_environment_url(right)


def select_file(title: str, filetypes: tuple[tuple[str, str], ...]) -> str:
    try:
        import tkinter as tk
        from tkinter import filedialog
    except ImportError:
        return input(
            f"Enter the full path for {title}, or press Enter to skip: "
        ).strip().strip('"')
    try:
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        selected = filedialog.askopenfilename(
            title=title,
            filetypes=(*filetypes, ("All files", "*.*")),
        )
        root.destroy()
        return selected
    except (RuntimeError, tk.TclError):
        return input(
            f"Enter the full path for {title}, or press Enter to skip: "
        ).strip().strip('"')


def prompt_environment(default: str = "") -> str:
    print(
        "\nThe Dataverse Environment URL is the web address of the Power "
        "Platform environment that stores the agent transcripts."
    )
    print("Example: https://orgabc12345.crm.dynamics.com")
    while True:
        suffix = f" [{default}]" if default else ""
        value = input(f"Paste the Environment URL{suffix}: ").strip() or default
        try:
            return normalize_environment_url(value)
        except ValueError as error:
            print(f"That URL is not valid: {error}")


def merge_cli_options(
    args: argparse.Namespace,
    stored: SetupOptions | None,
) -> SetupOptions:
    options = stored or SetupOptions(environment_url="")
    if (
        stored
        and args.environment_url
        and not same_environment(stored.environment_url, args.environment_url)
    ):
        clear_optional_files(options)
    for field_name, _, _, _ in OPTIONAL_FILES:
        argument = getattr(args, field_name)
        if argument:
            setattr(options, field_name, str(argument.resolve()))
    if args.feedback_events_json:
        options.feedback_events_json = str(args.feedback_events_json.resolve())
        options.feedback_input_files = []
    feedback_inputs = getattr(args, "feedback_input", [])
    if feedback_inputs:
        options.feedback_input_files = [
            str(path.resolve()) for path in feedback_inputs
        ]
        options.feedback_events_json = ""
    if args.environment_url:
        options.environment_url = normalize_environment_url(
            args.environment_url
        )
    return options


def collect_interactive_options(
    args: argparse.Namespace,
    stored: SetupOptions | None,
) -> SetupOptions:
    if stored and ask_yes_no("Reuse the previously saved setup choices?", default=True):
        options = stored
        saved_environment = stored.environment_url
    else:
        options = SetupOptions(environment_url="")
        saved_environment = ""

    options.environment_url = prompt_environment(options.environment_url)
    if saved_environment and not same_environment(
        saved_environment,
        options.environment_url,
    ):
        clear_optional_files(options)
        print(
            "\nThe Environment URL changed, so saved customer files were "
            "cleared. Select files for this environment if needed."
        )
    elif any(getattr(options, field_name) for field_name in OPTIONAL_FILE_FIELDS):
        print("\nSaved optional files:")
        for field_name, label, _, _ in OPTIONAL_FILES:
            value = getattr(options, field_name)
            if value:
                print(f"  {label}: {value}")
        if options.feedback_input_files:
            print(
                "  Microsoft 365 feedback exports: "
                + ", ".join(options.feedback_input_files)
            )
        if not ask_yes_no(
            "Keep these saved optional files for this environment?",
            default=True,
        ):
            clear_optional_files(options)

    if args.mode == "service-refresh":
        return options

    if not ask_yes_no(
        "Do you want to choose or replace optional organization, credits, registry, topic, or feedback files?",
        default=False,
    ):
        return options

    for field_name, label, description, filetypes in OPTIONAL_FILES:
        print(f"\n{label}: {description}")
        current = getattr(options, field_name)
        if current:
            print(f"Current file: {current}")
        if ask_yes_no(f"Select a {label} file?", default=bool(current)):
            selected = select_file(f"Select {label}", filetypes)
            if selected:
                setattr(options, field_name, str(Path(selected).resolve()))
        else:
            setattr(options, field_name, "")

    print(
        "\nMicrosoft 365 feedback: optional raw Product Feedback or Monitor "
        "CSV exports. The guided setup prepares them locally."
    )
    if ask_yes_no(
        "Select one or more raw Microsoft 365 feedback exports?",
        default=bool(options.feedback_input_files),
    ):
        options.feedback_input_files = []
        while True:
            selected = select_file(
                "Select a Microsoft 365 feedback export",
                (("CSV files", "*.csv"),),
            )
            if selected:
                options.feedback_input_files.append(str(Path(selected).resolve()))
            if not selected or not ask_yes_no(
                "Add another feedback export?",
                default=False,
            ):
                break
        options.feedback_events_json = ""
    else:
        options.feedback_input_files = []
        options.feedback_events_json = ""
    return options


def build_feedback_command(options: SetupOptions, output: Path) -> list[str]:
    if not options.agent_registry_json:
        raise ValueError(
            "Microsoft 365 feedback requires an agent registry so tenant-wide "
            "rows can be attributed safely."
        )
    command = [sys.executable, str(FEEDBACK_NORMALIZER)]
    for path in options.feedback_input_files:
        command.extend(("--input", path))
    command.extend(
        (
            "--agent-registry",
            options.agent_registry_json,
            "--scope-mode",
            "ESS Safe",
            "--output",
            str(output),
        )
    )
    return command


def prepare_feedback(options: SetupOptions, protected_inputs: list | None = None) -> SetupOptions:
    if not options.feedback_input_files:
        return options
    for destination in feedback_output_paths(PREPARED_FEEDBACK):
        reject_output_collisions(destination, [SOURCE_TEMPLATE, *setup_input_paths(options), *(protected_inputs or [])])
    PREPARED_FEEDBACK.parent.mkdir(parents=True, exist_ok=True)
    completed = subprocess.run(
        build_feedback_command(options, PREPARED_FEEDBACK),
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )
    if completed.returncode:
        raise ValueError(
            "Microsoft 365 feedback preparation failed: "
            f"{last_process_message(completed)}"
        )
    prepared_json = feedback_output_paths(PREPARED_FEEDBACK)[1]
    if not prepared_json.exists():
        raise RuntimeError(
            "Microsoft 365 feedback preparation completed without creating the "
            "validated feedback data."
        )
    return replace(
        options,
        feedback_events_json=str(prepared_json),
    )


def build_command(
    mode: str,
    options: SetupOptions,
    output: Path,
) -> list[str]:
    command = [
        sys.executable,
        str(BUILDER),
        "--mode",
        mode,
        "--input",
        str(SOURCE_TEMPLATE),
        "--environment-url",
        options.environment_url,
        "--output",
        str(output),
    ]
    reusable = (
        ("agent_registry_json", "--agent-registry-json"),
        ("topic_overrides_json", "--topic-overrides-json"),
        ("feedback_events_json", "--feedback-events-json"),
    )
    desktop_only = (
        ("org_data_file", "--org-data-file"),
        ("agent_credits_file", "--agent-credits-file"),
    )
    for field_name, argument in reusable:
        value = getattr(options, field_name)
        if value:
            command.extend((argument, value))
    if mode == "desktop-validation":
        for field_name, argument in desktop_only:
            value = getattr(options, field_name)
            if value:
                command.extend((argument, value))
    return command


def validate_runtime() -> None:
    if sys.version_info < (3, 10):
        raise RuntimeError(
            "Python 3.10 or later is required. Download it from "
            "https://www.python.org/downloads/windows/."
        )
    for path in (SOURCE_TEMPLATE, BUILDER, FEEDBACK_NORMALIZER):
        if not path.exists():
            raise FileNotFoundError(
                f"Required package file is missing: {path}. Download and "
                "extract the complete ESS package again."
            )


def validation_summary(validation: dict) -> list[str]:
    lines = ["Dataverse Environment URL: valid"]
    aliases = int(validation.get("registryAliases") or 0)
    if aliases:
        lines.append(f"Agent registry: {aliases} aliases")
    labels = {
        "Org Data": "Organization data",
        "Power Platform admin center User-Level Credit Consumption": (
            "Copilot credit consumption"
        ),
        "Customer Topic Overrides": "Approved topic rules",
        "Feedback Events": "Prepared feedback",
    }
    for source in validation.get("sources") or []:
        label = labels.get(source.get("contract"), source.get("contract"))
        count = source.get("rows")
        if count is None:
            count = source.get("enabledRules")
        if count is None:
            count = source.get("events")
        lines.append(f"{label}: {count} rows")
    return lines


def last_process_message(completed: subprocess.CompletedProcess[str]) -> str:
    output = completed.stderr or completed.stdout or ""
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    return lines[-1] if lines else "The template builder returned an unknown error."


def tune_topics(args: argparse.Namespace) -> int:
    if args.mode != "desktop-validation":
        raise ValueError("Topic tuning creates a Desktop Validation template. Use the Desktop launcher.")
    settings_file = args.settings_file.resolve()
    stored = load_settings(settings_file)
    if stored is None or not stored.environment_url:
        raise ValueError("Complete START-HERE-DATAVERSE.cmd once for the baseline before tuning topics.")
    source = args.topic_transcripts
    if source is None:
        if args.non_interactive:
            raise ValueError("Non-interactive topic tuning requires --topic-transcripts.")
        selected = select_file("Select the exported Dataverse ConversationTranscript CSV", (("CSV files", "*.csv"),))
        if not selected:
            print("No export selected. Template unchanged.")
            return 0
        source = Path(selected)
    output = args.output or GENERATED_DIR / TOPIC_OUTPUT_NAME
    protected_inputs = [SOURCE_TEMPLATE, settings_file, source, *setup_input_paths(stored)]
    reject_output_collisions(output, [*feedback_output_paths(PREPARED_FEEDBACK), *protected_inputs])
    if stored.feedback_input_files:
        for destination in feedback_output_paths(PREPARED_FEEDBACK):
            reject_output_collisions(destination, [output, *protected_inputs])
    command = [
        sys.executable, str(ROOT / "tools" / "ess_topic_tuner.py"),
        "--input", str(source.resolve()), "--output-dir", str(settings_file.parent / "Topic Review"),
        "--settings-file", str(settings_file),
        "--template-output", str(output.resolve()),
    ]
    if args.no_open:
        command.append("--no-open")
    if args.non_interactive:
        command.append("--non-interactive")
    return subprocess.run(command, check=False).returncode


def main() -> int:
    args = parse_args()
    validate_runtime()
    if args.tune_topics:
        return tune_topics(args)
    settings_file = args.settings_file.resolve()
    stored = load_settings(settings_file)

    protected_inputs = [SOURCE_TEMPLATE, settings_file, args.topic_transcripts, *setup_input_paths(stored)]
    print("\nESS Insights - Guided Dataverse Setup")
    print("=" * 39)
    if args.mode == "desktop-validation":
        print(
            "This creates a LOCAL DESKTOP VALIDATION template used to test "
            "Dataverse and optional local files."
        )
        print(
            "Do not publish this file for scheduled refresh. After validation, "
            "run BUILD-SERVICE-REFRESH.cmd to create the publishable report."
        )
    else:
        print(
            "This creates the Power BI Service publication template for "
            "scheduled Dataverse refresh."
        )
        print(
            "Organization and credit files are intentionally excluded because "
            "Power BI Service cannot refresh those local files without a gateway."
        )
        if not stored and not args.environment_url:
            raise RuntimeError(
                "No saved Desktop setup was found. Run "
                "START-HERE-DATAVERSE.cmd first."
            )

    if args.non_interactive:
        options = merge_cli_options(args, stored)
        if not options.environment_url:
            raise RuntimeError("--environment-url is required.")
    else:
        options = collect_interactive_options(args, stored)

    output = (
        args.output.resolve()
        if args.output
        else GENERATED_DIR / OUTPUT_NAMES[args.mode]
    )
    protected_inputs.extend(setup_input_paths(options))
    reject_output_collisions(output, [*feedback_output_paths(PREPARED_FEEDBACK), *protected_inputs])

    print("\nChecking the supplied information and building the template...")
    prepared_options = prepare_feedback(options, [output, *protected_inputs])
    staged_output = staging_path(output)
    staged_settings = None
    try:
        completed = subprocess.run(
            build_command(args.mode, prepared_options, staged_output),
            check=False,
            capture_output=True,
            text=True,
        )
        if completed.returncode:
            print(
                "\nSetup stopped because one of the supplied values or files "
                "did not pass validation."
            )
            print(f"Details: {last_process_message(completed)}")
            return completed.returncode
        try:
            validation = json.loads(completed.stdout)
        except json.JSONDecodeError:
            print(
                "\nSetup stopped because the template builder returned an "
                "unexpected result."
            )
            return 1
        if not isinstance(validation, dict):
            raise ValueError("The template builder did not return a validation object.")
        summary = validation_summary(validation)
        with zipfile.ZipFile(staged_output) as package:
            if "DataModelSchema" not in package.namelist() or package.testzip() is not None:
                raise ValueError("The staged PBIT failed package integrity validation.")
        if args.mode == "desktop-validation":
            staged_settings = staging_path(settings_file)
            save_settings(staged_settings, options)
            if load_settings(staged_settings) != options:
                raise ValueError("The staged settings did not preserve the selected setup choices.")
        publish_template(staged_output, output, staged_settings,
                         settings_file if staged_settings is not None else None)
    finally:
        staged_output.unlink(missing_ok=True)
        if staged_settings is not None:
            staged_settings.unlink(missing_ok=True)

    print("\nValidation complete:")
    for line in summary:
        print(f"  - {line}")
    warnings = validation.get("warnings") or []
    if warnings:
        print("\nImportant notes:")
        for warning in warnings:
            print(f"  - {warning}")

    print(f"\nTemplate created successfully:\n{output}")
    if args.mode == "desktop-validation":
        print(
            "\nIn Power BI Desktop, wait until the displayed values are visible "
            "and stable. Then select Load, sign in with Organizational account, "
            "and refresh."
        )
        print(
            "\nDESKTOP VALIDATION ONLY - DO NOT PUBLISH THIS FILE FOR SCHEDULED "
            "REFRESH.\nIf you need Power BI Service, run "
            "BUILD-SERVICE-REFRESH.cmd after validation."
        )
    else:
        print(
            "\nPOWER BI SERVICE PUBLICATION FILE - PUBLISH THIS VERSION.\n"
            "Refresh it in Power BI Desktop, save it as PBIX, and publish it. "
            "In Power BI Service, configure the Dataverse credentials as OAuth2 "
            "/ Organizational, run Refresh now, confirm Refresh history shows "
            "Completed, and only then enable Scheduled refresh."
        )

    open_template = args.open_template
    if not open_template and not args.no_open and not args.non_interactive:
        try:
            open_template = ask_yes_no("Open the generated template now?", default=True)
        except EOFError:
            print("Template and settings were saved. No open response received; open the template manually.")
    if open_template:
        try:
            os.startfile(output)
        except OSError as error:
            print(f"WARNING: The template and settings were saved, but Desktop could not be opened: {error}. Open {output} manually.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError, zipfile.BadZipFile) as error:
        print(f"\nSetup could not continue: {error}")
        raise SystemExit(1) from error
