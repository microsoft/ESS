#!/usr/bin/env python3
"""Guide nontechnical users through building validated Dataverse templates."""

from __future__ import annotations

import argparse
import csv
import importlib.util
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
from ess_feedback_normalizer import (
    feedback_output_paths,
    is_product_feedback_export,
    reject_output_collisions,
)


SETUP_VERSION = "V23"
ROOT = Path(__file__).resolve().parents[1]
SOURCE_TEMPLATE = (
    ROOT
    / f"ESS Dashboard - Dynamic Topics (Dataverse) {SETUP_VERSION} - Power BI Service - PUBLISH THIS.pbit"
)
BUILDER = ROOT / "tools" / "build_service_refresh_template.py"
FEEDBACK_NORMALIZER = ROOT / "tools" / "ess_feedback_normalizer.py"
GENERATED_DIR = ROOT / "Generated Templates"
DEFAULT_SETTINGS = GENERATED_DIR / "dataverse-setup.json"
PREPARED_FEEDBACK = GENERATED_DIR / "Prepared Inputs" / "feedback-events.csv"
LOCAL_RUNTIME_DIR = (
    Path(os.environ.get("LOCALAPPDATA") or Path.home())
    / "ESS"
    / "semantic-runtime"
    / f"python-{sys.version_info.major}.{sys.version_info.minor}"
)
OUTPUT_NAMES = {
    "desktop-validation": (
        f"ESS Dashboard - Dynamic Topics (Dataverse) {SETUP_VERSION} - "
        "Desktop Validation - LOCAL ONLY.pbit"
    ),
    "service-refresh": (
        f"ESS Dashboard - Dynamic Topics (Dataverse) {SETUP_VERSION} - "
        "Power BI Service - PUBLISH THIS.pbit"
    ),
}
TOPIC_OUTPUT_NAME = (
    f"ESS Dashboard - Dynamic Topics (Dataverse) {SETUP_VERSION} - "
    "Desktop Validation - Topics - LOCAL ONLY.pbit"
)


@dataclass
class SetupOptions:
    environment_url: str
    agent_registry_json: str = ""
    org_data_file: str = ""
    org_data_url: str = ""
    agent_credits_file: str = ""
    topic_overrides_json: str = ""
    conversation_topics_json: str = ""
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
    "conversation_topics_json",
    "org_data_url",
    "feedback_events_json",
    "feedback_input_files",
)


SKIP_FIELDS = {
    "--skip-agent-registry": ("agent_registry_json",),
    "--skip-org-data": ("org_data_file", "org_data_url"),
    "--skip-agent-credits": ("agent_credits_file",),
    "--skip-topic-overrides": (
        "topic_overrides_json",
        "conversation_topics_json",
    ),
    "--skip-feedback": ("feedback_events_json", "feedback_input_files"),
}


def selected_skip_flags(args: argparse.Namespace) -> list[str]:
    return [
        flag for flag in SKIP_FIELDS
        if getattr(args, flag[2:].replace("-", "_"), False)
    ]


def apply_skip_options(options: SetupOptions, args: argparse.Namespace) -> SetupOptions:
    for flag in selected_skip_flags(args):
        for field_name in SKIP_FIELDS[flag]:
            setattr(options, field_name, [] if field_name == "feedback_input_files" else "")
    return options


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=f"Build validated ESS Dataverse {SETUP_VERSION} templates through a guided setup."
    )
    parser.add_argument("--version", action="version", version=f"ESS Dataverse setup {SETUP_VERSION} (Python 3.10-3.14)")
    parser.add_argument(
        "--mode",
        choices=("desktop-validation", "service-refresh"),
        default="desktop-validation",
    )
    parser.add_argument("--environment-url")
    registry = parser.add_mutually_exclusive_group()
    registry.add_argument("--agent-registry-json", type=Path)
    registry.add_argument("--skip-agent-registry", action="store_true", help="Ignore any saved agent registry.")
    organization = parser.add_mutually_exclusive_group()
    organization.add_argument("--org-data-file", type=Path)
    organization.add_argument("--org-data-url")
    organization.add_argument("--skip-org-data", action="store_true", help="Ignore saved local and cloud organization data.")
    credits = parser.add_mutually_exclusive_group()
    credits.add_argument("--agent-credits-file", type=Path)
    credits.add_argument("--skip-agent-credits", action="store_true", help="Ignore any saved credit-consumption file.")
    topics = parser.add_mutually_exclusive_group()
    topics.add_argument("--topic-overrides-json", type=Path)
    topics.add_argument("--skip-topic-overrides", action="store_true", help="Use native and built-in topics only.")
    parser.add_argument(
        "--conversation-topics-json",
        type=Path,
        help=argparse.SUPPRESS,
    )
    parser.add_argument("--tune-topics", action="store_true", help="Tune an exported transcript CSV using saved setup choices.")
    parser.add_argument("--topic-transcripts", type=Path, help="Optional transcript CSV for --tune-topics; otherwise a file picker opens.")
    semantic = parser.add_mutually_exclusive_group()
    semantic.add_argument(
        "--semantic-classification",
        action="store_true",
        dest="semantic_classification",
        help="Use closed-taxonomy semantic classification for unresolved messages.",
    )
    semantic.add_argument(
        "--no-semantic-classification",
        action="store_false",
        dest="semantic_classification",
        help="Run deterministic topic tuning without a semantic provider.",
    )
    parser.set_defaults(semantic_classification=None)
    parser.add_argument(
        "--semantic-provider",
        choices=("local", "azure"),
        default=None,
        help="Use the bundled local classifier by default; Azure remains optional.",
    )
    parser.add_argument(
        "--semantic-endpoint",
        default=os.environ.get("ESS_SEMANTIC_ENDPOINT", ""),
    )
    parser.add_argument(
        "--semantic-deployment",
        default=os.environ.get("ESS_SEMANTIC_DEPLOYMENT", ""),
    )
    parser.add_argument(
        "--local-model-dir",
        type=Path,
        default=ROOT / "models" / "multilingual-e5-small",
    )
    parser.add_argument("--local-min-similarity", type=float, default=0.82)
    parser.add_argument("--local-min-margin", type=float, default=0.01)
    feedback = parser.add_mutually_exclusive_group()
    feedback.add_argument("--feedback-events-json", type=Path)
    feedback.add_argument(
        "--feedback-input",
        type=Path,
        action="append",
        default=[],
        help="Raw Product Feedback or Monitor CSV; repeat for multiple exports.",
    )
    feedback.add_argument("--skip-feedback", action="store_true", help="Ignore saved raw exports and prepared feedback JSON.")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--settings-file", type=Path, default=DEFAULT_SETTINGS)
    parser.add_argument("--non-interactive", action="store_true")
    opening = parser.add_mutually_exclusive_group()
    opening.add_argument("--no-open", action="store_true")
    opening.add_argument("--open", action="store_true", dest="open_template")
    args = parser.parse_args()
    if args.tune_topics and args.skip_topic_overrides:
        parser.error("--skip-topic-overrides cannot be combined with --tune-topics, which builds new topic rules.")
    return args


def load_settings(path: Path) -> SetupOptions | None:
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    return SetupOptions(
        environment_url=str(payload.get("environment_url") or ""),
        agent_registry_json=str(payload.get("agent_registry_json") or ""),
        org_data_file=str(payload.get("org_data_file") or ""),
        org_data_url=str(payload.get("org_data_url") or ""),
        agent_credits_file=str(payload.get("agent_credits_file") or ""),
        topic_overrides_json=str(payload.get("topic_overrides_json") or ""),
        conversation_topics_json=str(
            payload.get("conversation_topics_json") or ""
        ),
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
    return [
        getattr(options, field_name)
        for field_name, _, _, _ in OPTIONAL_FILES
    ] + [
        options.conversation_topics_json,
        options.feedback_events_json,
        *options.feedback_input_files,
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
    options = replace(stored, feedback_input_files=list(stored.feedback_input_files)) if stored else SetupOptions(environment_url="")
    if (
        stored
        and args.environment_url
        and not same_environment(stored.environment_url, args.environment_url)
    ):
        clear_optional_files(options)
    for field_name, _, _, _ in OPTIONAL_FILES:
        argument = getattr(args, field_name, None)
        if argument:
            setattr(options, field_name, str(argument.resolve()))
    conversation_topics = getattr(args, "conversation_topics_json", None)
    if conversation_topics:
        options.conversation_topics_json = str(
            conversation_topics.resolve()
        )
    org_data_url = getattr(args, "org_data_url", None)
    if org_data_url:
        options.org_data_url = org_data_url.strip()
        options.org_data_file = ""
    elif args.org_data_file:
        options.org_data_url = ""
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
    return apply_skip_options(options, args)


def product_feedback_inputs(paths: list[str]) -> list[str]:
    matches = []
    for path in paths:
        with Path(path).open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            if not reader.fieldnames:
                raise ValueError(f"{path} has no CSV header")
            if is_product_feedback_export(reader.fieldnames):
                matches.append(path)
    return matches


def enhancement_action(label: str, current: str, *, skipped: bool = False) -> str:
    if skipped:
        return "skip"
    if not current:
        return "replace" if ask_yes_no(f"Add {label}?", default=False) else "skip"
    print(f"Current selection: {current}")
    choices = {"k": "keep", "keep": "keep", "r": "replace", "replace": "replace", "s": "skip", "skip": "skip", "": "skip"}
    while True:
        answer = input(f"{label}: keep, replace, or skip? [k/r/S]: ").strip().lower()
        if answer in choices:
            return choices[answer]
        print("Enter keep, replace, or skip.")


def collect_feedback(options: SetupOptions, *, skipped: bool = False, registry_skipped: bool = False) -> None:
    print(
        "\nMicrosoft 365 feedback is optional: choose raw CSV exports or prepared "
        "feedback-events.json. Product Feedback needs an agent registry for safe "
        "attribution. Monitor exports with Conversation IDs do not."
    )
    current = ", ".join([path for path in [options.feedback_events_json, *options.feedback_input_files] if path])
    action = enhancement_action("Microsoft 365 feedback", current, skipped=skipped)
    if action != "keep":
        options.feedback_events_json = ""
        options.feedback_input_files = []
    if action == "skip":
        return
    if action == "replace":
        selected = select_file(
            "Select a Microsoft 365 feedback CSV or prepared feedback JSON",
            (("Feedback files", "*.csv *.json"),),
        )
        if not selected:
            return
        if Path(selected).suffix.lower() == ".json":
            options.feedback_events_json = str(Path(selected).resolve())
            return
        options.feedback_input_files.append(str(Path(selected).resolve()))
        while ask_yes_no("Add another feedback export?", default=False):
            selected = select_file("Select a Microsoft 365 feedback export", (("CSV files", "*.csv"),))
            if not selected:
                break
            options.feedback_input_files.append(str(Path(selected).resolve()))

    if options.agent_registry_json or not options.feedback_input_files:
        return
    product_feedback = product_feedback_inputs(options.feedback_input_files)
    if not product_feedback:
        return
    print(
        "\nMicrosoft 365 Product Feedback needs an agent registry. "
        "This does not affect Monitor files or the rest of setup."
    )
    if not registry_skipped and ask_yes_no("Select an agent registry now?", default=False):
        selected_registry = select_file("Select Agent registry", (("Registry files", "*.csv *.json"),))
        if selected_registry:
            options.agent_registry_json = str(Path(selected_registry).resolve())
    if not options.agent_registry_json:
        excluded = {str(Path(path).resolve()) for path in product_feedback}
        options.feedback_input_files = [
            path for path in options.feedback_input_files
            if str(Path(path).resolve()) not in excluded
        ]
        options.feedback_events_json = ""
        print("Product Feedback was skipped because no agent registry was selected. Setup will continue.")


def collect_interactive_options(
    args: argparse.Namespace,
    stored: SetupOptions | None,
) -> SetupOptions:
    if stored and ask_yes_no("Reuse the previously saved setup choices?", default=True):
        options = replace(stored, feedback_input_files=list(stored.feedback_input_files))
        saved_environment = stored.environment_url
    else:
        options = SetupOptions(environment_url="")
        saved_environment = ""

    options.environment_url = prompt_environment(options.environment_url)
    if saved_environment and not same_environment(saved_environment, options.environment_url):
        clear_optional_files(options)
        print(
            "\nThe Environment URL changed, so saved customer files were "
            "cleared. Select files for this environment if needed."
        )
    apply_skip_options(options, args)
    skipped_fields = {field_name for flag in selected_skip_flags(args) for field_name in SKIP_FIELDS[flag]}
    print("\nChoose each enhancement independently. New enhancements default to skip; saved selections require keep, replace, or skip.")

    for field_name, label, description, filetypes in OPTIONAL_FILES:
        if args.mode == "service-refresh" and field_name == "agent_credits_file":
            options.agent_credits_file = ""
            print("\nCopilot credit consumption: skipped (Desktop/manual refresh only).")
            continue
        cloud_organization = args.mode == "service-refresh" and field_name == "org_data_file"
        if cloud_organization:
            options.org_data_file = ""
            current = options.org_data_url
            print("\nOrganization data: optional direct HTTPS CSV path from SharePoint Online or OneDrive for Business.")
        else:
            current = getattr(options, field_name)
            print(f"\n{label}: {description}")
        action = enhancement_action(label, current, skipped=field_name in skipped_fields)
        if action == "keep":
            continue
        setattr(options, field_name, "")
        if field_name == "org_data_file":
            options.org_data_url = ""
        if action == "replace":
            if cloud_organization:
                options.org_data_url = input("Paste the direct organization CSV URL, or press Enter to skip: ").strip().strip('"')
            else:
                selected = select_file(f"Select {label}", filetypes)
                if selected:
                    setattr(options, field_name, str(Path(selected).resolve()))

    collect_feedback(
        options,
        skipped="feedback_input_files" in skipped_fields,
        registry_skipped="agent_registry_json" in skipped_fields,
    )
    return options


def print_selection_summary(mode: str, options: SetupOptions) -> None:
    print("\nEnhancements selected for this build:")
    for field_name, label, _, _ in OPTIONAL_FILES:
        if mode == "service-refresh" and field_name == "agent_credits_file":
            value = ""
        elif mode == "service-refresh" and field_name == "org_data_file":
            value = options.org_data_url
        else:
            value = getattr(options, field_name)
        print(f"  - {label}: {value or 'skipped'}")
    print(
        "  - Exact semantic conversation topics: "
        f"{options.conversation_topics_json or 'skipped'}"
    )
    feedback = ", ".join(options.feedback_input_files) or options.feedback_events_json
    print(f"  - Microsoft 365 feedback: {feedback or 'skipped'}")


def build_feedback_command(options: SetupOptions, output: Path) -> list[str]:
    command = [sys.executable, str(FEEDBACK_NORMALIZER)]
    for path in options.feedback_input_files:
        command.extend(("--input", path))
    if options.agent_registry_json:
        command.extend(
            (
                "--agent-registry",
                options.agent_registry_json,
                "--scope-mode",
                "ESS Safe",
            )
        )
    command.extend(("--output", str(output)))
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
        ("conversation_topics_json", "--conversation-topics-json"),
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
    elif options.org_data_url:
        command.extend(("--org-data-url", options.org_data_url))
    return command


def validate_runtime() -> None:
    if not (3, 10) <= sys.version_info[:2] < (3, 15):
        raise RuntimeError(
            "Python 3.10 through 3.14 is required. Python 3.15 is not yet "
            "supported by the required NumPy and ONNX Runtime libraries. "
            "Download Python 3.14 from https://www.python.org/downloads/windows/."
        )
    for path in (SOURCE_TEMPLATE, BUILDER, FEEDBACK_NORMALIZER):
        if not path.exists():
            raise FileNotFoundError(
                f"Required package file is missing: {path}. Download and "
                "extract the complete ESS package again."
            )


def validation_summary(validation: dict) -> list[str]:
    lines = ["Dataverse Environment URL: valid"]
    if validation.get("organizationDataUrl"):
        lines.append("Organization data URL format: valid")
    aliases = int(validation.get("registryAliases") or 0)
    if aliases:
        lines.append(f"Agent registry: {aliases} aliases")
    labels = {
        "Org Data": "Organization data",
        "Power Platform admin center User-Level Credit Consumption": (
            "Copilot credit consumption"
        ),
        "Customer Topic Overrides": "Approved topic rules",
        "Customer Conversation Topics": (
            "Human-approved conversation topics"
        ),
        "Feedback Events": "Prepared feedback",
    }
    for source in validation.get("sources") or []:
        label = labels.get(source.get("contract"), source.get("contract"))
        count = source.get("rows")
        if count is None:
            count = source.get("enabledRules")
        if count is None:
            count = source.get("events")
        if count is None:
            count = source.get("classifiedConversations")
        lines.append(f"{label}: {count} rows")
    return lines


def last_process_message(completed: subprocess.CompletedProcess[str]) -> str:
    output = completed.stderr or completed.stdout or ""
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    return lines[-1] if lines else "The template builder returned an unknown error."


def local_semantic_environment() -> dict[str, str]:
    environment = os.environ.copy()
    required = ("numpy", "onnxruntime", "tokenizers")
    if all(importlib.util.find_spec(name) is not None for name in required):
        return environment

    LOCAL_RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    if sys.version_info >= (3, 14):
        packages = (
            "numpy==2.4.6",
            "onnxruntime==1.26.0",
            "tokenizers==0.23.1",
        )
    else:
        packages = (
            "numpy==2.2.6",
            "onnxruntime==1.23.2",
            "tokenizers==0.22.1",
        )
    print(
        "\nPreparing the local semantic runtime once. This downloads Python "
        "runtime libraries only; no transcript data is uploaded."
    )
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "--only-binary=:all:",
            "--target",
            str(LOCAL_RUNTIME_DIR),
            *packages,
        ],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if completed.returncode:
        raise ValueError(
            "The local semantic runtime could not be installed: "
            f"{last_process_message(completed)}"
        )
    environment["PYTHONPATH"] = os.pathsep.join(
        [
            str(LOCAL_RUNTIME_DIR),
            environment.get("PYTHONPATH", ""),
        ]
    ).rstrip(os.pathsep)
    verification = subprocess.run(
        [
            sys.executable,
            "-c",
            "import numpy, onnxruntime, tokenizers",
        ],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=environment,
    )
    if verification.returncode:
        raise ValueError(
            "The local semantic runtime was installed but could not be loaded: "
            f"{last_process_message(verification)}"
        )
    return environment


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
    use_semantic = getattr(args, "semantic_classification", None)
    semantic_endpoint = str(getattr(args, "semantic_endpoint", "") or "").strip()
    semantic_deployment = str(getattr(args, "semantic_deployment", "") or "").strip()
    if use_semantic is None:
        use_semantic = True
    use_semantic = bool(use_semantic)
    requested_provider = getattr(args, "semantic_provider", None)
    semantic_provider = str(
        requested_provider
        or (
            "azure"
            if semantic_endpoint or semantic_deployment
            else "local"
        )
    ).strip().lower()
    local_model_dir = Path(
        getattr(
            args,
            "local_model_dir",
            ROOT / "models" / "multilingual-e5-small",
        )
    )
    local_min_similarity = float(
        getattr(args, "local_min_similarity", 0.82)
    )
    local_min_margin = float(getattr(args, "local_min_margin", 0.01))
    if use_semantic and semantic_provider == "local":
        print(
            "\nThe bundled local semantic classifier will analyze unresolved "
            "messages on this device. Transcript text is not sent to a model service."
        )
    if use_semantic and semantic_provider == "azure":
        print(
            "\nAzure semantic mode sends PII-redacted unresolved first-user "
            "messages to the customer-owned approved endpoint."
        )
        print(
            "Redaction reduces exposure but does not guarantee anonymity. Use Azure "
            "mode only with customer approval."
        )
        if not semantic_endpoint:
            if args.non_interactive:
                raise ValueError(
                    "Semantic topic tuning requires --semantic-endpoint."
                )
            semantic_endpoint = input(
                "Paste the customer-owned Azure OpenAI resource endpoint: "
            ).strip()
        if not semantic_deployment:
            if args.non_interactive:
                raise ValueError(
                    "Semantic topic tuning requires --semantic-deployment."
                )
            semantic_deployment = input(
                "Enter the approved Azure model deployment name: "
            ).strip()
    output = args.output or GENERATED_DIR / TOPIC_OUTPUT_NAME
    protected_inputs = [SOURCE_TEMPLATE, settings_file, source, *setup_input_paths(stored)]
    reject_output_collisions(output, [*feedback_output_paths(PREPARED_FEEDBACK), *protected_inputs])
    selected = apply_skip_options(replace(stored, feedback_input_files=list(stored.feedback_input_files)), args)
    if selected.feedback_input_files:
        for destination in feedback_output_paths(PREPARED_FEEDBACK):
            reject_output_collisions(destination, [output, *protected_inputs])
    command = [
        sys.executable, str(ROOT / "tools" / "ess_topic_tuner.py"),
        "--input", str(source.resolve()), "--output-dir", str(settings_file.parent / "Topic Review"),
        "--settings-file", str(settings_file),
        "--template-output", str(output.resolve()),
    ]
    command.extend(selected_skip_flags(args))
    if use_semantic:
        command.extend(
            [
                "--semantic-classification",
                "--semantic-provider",
                semantic_provider,
                "--local-model-dir",
                str(local_model_dir.resolve()),
                "--local-min-similarity",
                str(local_min_similarity),
                "--local-min-margin",
                str(local_min_margin),
            ]
        )
        if semantic_provider == "azure":
            command.extend(
                [
                "--semantic-endpoint",
                semantic_endpoint,
                "--semantic-deployment",
                semantic_deployment,
                ]
            )
    if args.no_open:
        command.append("--no-open")
    if args.non_interactive:
        command.append("--non-interactive")
    environment = (
        local_semantic_environment()
        if use_semantic and semantic_provider == "local"
        else os.environ.copy()
    )
    return subprocess.run(
        command,
        check=False,
        env=environment,
    ).returncode


def main() -> int:
    args = parse_args()
    validate_runtime()
    if args.tune_topics:
        return tune_topics(args)
    settings_file = args.settings_file.resolve()
    stored = load_settings(settings_file)

    protected_inputs = [SOURCE_TEMPLATE, settings_file, args.topic_transcripts, *setup_input_paths(stored)]
    print(f"\nESS Insights - Guided Dataverse Setup {SETUP_VERSION}")
    print("=" * 43)
    if args.mode == "desktop-validation":
        print(
            "This creates a LOCAL DESKTOP VALIDATION template used to test "
            "Dataverse and optional local files."
        )
        print(
            "This is the local input-checking output. After validation, run "
            "BUILD-SERVICE-REFRESH.cmd to create the separate Power BI Service "
            "publication report."
        )
    else:
        print(
            "This creates the Power BI Service publication template for "
            "scheduled Dataverse refresh."
        )
        print(
            "Local organization and credit files are excluded. Organization data "
            "can use a direct SharePoint or OneDrive CSV URL for scheduled refresh."
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

    print_selection_summary(args.mode, options)
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
            "\nLOCAL DESKTOP VALIDATION FILE.\nThis is the first of two "
            "intentional outputs. For shared Power BI Service access, run "
            "BUILD-SERVICE-REFRESH.cmd after validation and publish the version "
            "named Power BI Service - PUBLISH THIS."
        )
    else:
        print(
            "\nPOWER BI SERVICE PUBLICATION FILE - PUBLISH THIS VERSION.\n"
            "Refresh it in Power BI Desktop, save it as PBIX, and publish it. "
            "In Power BI Service, map the Dataverse source and, when organization "
            "data is enabled, the SharePoint source under Gateway and cloud "
            "connections using OAuth2 / Organizational credentials. Run Refresh "
            "now, confirm Refresh history shows Completed, and only then enable "
            "Scheduled refresh."
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
