from __future__ import annotations

import fnmatch
import json
import os
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

DEFAULT_CONFIG = {
    "input_folder": r"C:\Users\eansdix\OneDrive - Ericsson\Daily Work\2026\Sep\gleaninvtool\Input",
    "mailbox_name": "",
    "lookback_days": 3,
    "sender_patterns": ["ENABLE-NOREPLY"],
    "rules": [
        {
            "vendor": "Huawei",
            "subject_contains": ["DTAC-OF-TH | RAN - True Huawei Daily Cell NE Status |"],
            "attachment_patterns": ["Report.zip"],
        },
        {
            "vendor": "Ericsson",
            "subject_contains": ["TRUE_BO_RAN_ERICSSON_ENABLE_Daily_Network_Dump_Audit"],
            "attachment_patterns": ["*_Execution_Report.zip"],
        },
        {
            "vendor": "Ericsson",
            "subject_contains": ["TRUE | Network Cell Audit - Ericsson |"],
            "attachment_patterns": ["Network Cell Status Reports_*.zip"],
        },
        {
            "vendor": "ZTE",
            "subject_contains": ["TRUE_BO_RAN_ZTE_Enable_Daily_NE_inventory_report"],
            "attachment_patterns": ["HARDWARE_SOFTWARE.zip"],
        },
        {
            "vendor": "ZTE",
            "subject_contains": ["TRUE_BO_RAN_ZTE_Enable_Daily_Cell_report"],
            "attachment_patterns": ["CELL_DUMP.zip"],
        },
    ],
}


def default_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def config_path(base_dir: Path) -> Path:
    return base_dir / "auto_sync_config.json"


def manifest_path(base_dir: Path) -> Path:
    return base_dir / "auto_sync_manifest.json"


def load_config(base_dir: Path) -> dict:
    path = config_path(base_dir)
    if not path.exists():
        path.write_text(json.dumps(DEFAULT_CONFIG, indent=2), encoding="utf-8")
        return json.loads(json.dumps(DEFAULT_CONFIG))
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        merged = json.loads(json.dumps(DEFAULT_CONFIG))
        merged.update(data)
        if "rules" not in data:
            merged["rules"] = DEFAULT_CONFIG["rules"]
        return merged
    except Exception as exc:
        raise RuntimeError(f"Could not read {path.name}: {exc}") from exc


def load_manifest(base_dir: Path) -> dict:
    path = manifest_path(base_dir)
    if not path.exists():
        return {"processed": {}, "last_run": ""}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"processed": {}, "last_run": ""}


def save_manifest(base_dir: Path, manifest: dict) -> None:
    manifest["last_run"] = datetime.now().isoformat(timespec="seconds")
    manifest_path(base_dir).write_text(json.dumps(manifest, indent=2), encoding="utf-8")


def _text(value) -> str:
    return str(value or "").strip()


def _match_any(value: str, patterns: list[str]) -> bool:
    value = _text(value).casefold()
    return any(_text(p).casefold() in value for p in patterns if _text(p))


def _attachment_match(filename: str, patterns: list[str]) -> bool:
    name = Path(filename).name.casefold()
    return any(fnmatch.fnmatchcase(name, _text(p).casefold()) for p in patterns if _text(p))


def _message_matches(message, config: dict) -> list[dict]:
    subject = _text(getattr(message, "Subject", ""))
    sender_name = _text(getattr(message, "SenderName", ""))
    sender_email = _text(getattr(message, "SenderEmailAddress", ""))
    sender_patterns = config.get("sender_patterns", [])
    if sender_patterns and not (_match_any(sender_name, sender_patterns) or _match_any(sender_email, sender_patterns)):
        return []
    results = []
    for rule in config.get("rules", []):
        if not _match_any(subject, rule.get("subject_contains", [])):
            continue
        for i in range(1, int(getattr(message.Attachments, "Count", 0)) + 1):
            attachment = message.Attachments.Item(i)
            filename = _text(getattr(attachment, "FileName", ""))
            if _attachment_match(filename, rule.get("attachment_patterns", [])):
                results.append({"rule": rule, "attachment": attachment, "filename": filename})
    return results


def _iter_folders(folder, seen: set[str] | None = None, depth: int = 0, max_depth: int = 6):
    seen = seen or set()
    try:
        entry_id = _text(getattr(folder, "EntryID", ""))
        if entry_id and entry_id in seen:
            return
        if entry_id:
            seen.add(entry_id)
        yield folder
        if depth >= max_depth:
            return
        for child in folder.Folders:
            yield from _iter_folders(child, seen, depth + 1, max_depth)
    except Exception:
        return


def _candidate_roots(session, mailbox_name: str):
    wanted = _text(mailbox_name).casefold()
    for root in session.Folders:
        display = _text(getattr(root, "Name", ""))
        if not wanted or wanted in display.casefold():
            yield root


def _received_datetime(message):
    value = getattr(message, "ReceivedTime", None)
    if value is None:
        return None
    try:
        return value.replace(tzinfo=None)
    except Exception:
        try:
            return datetime(value.year, value.month, value.day, value.hour, value.minute, value.second)
        except Exception:
            return None


def _iter_candidate_messages(session, config: dict):
    cutoff = datetime.now() - timedelta(days=int(config.get("lookback_days", 3)))
    seen_folders = set()
    for root in _candidate_roots(session, config.get("mailbox_name", "")):
        for folder in _iter_folders(root, seen_folders):
            try:
                items = folder.Items
                items.Sort("[ReceivedTime]", True)
                count = min(int(getattr(items, "Count", 0)), int(config.get("max_items_per_folder", 500)))
                for i in range(1, count + 1):
                    item = items.Item(i)
                    if int(getattr(item, "Class", 0)) != 43:  # Outlook MailItem
                        continue
                    received = _received_datetime(item)
                    if received and received < cutoff:
                        continue
                    yield item
            except Exception:
                continue


def _message_key(message, filename: str) -> str:
    entry = _text(getattr(message, "EntryID", ""))
    subject = _text(getattr(message, "Subject", ""))
    received = _text(getattr(message, "ReceivedTime", ""))
    return "|".join((entry, received, subject, filename))


def _save_attachment(attachment, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{destination.name}.", suffix=".part", dir=str(destination.parent))
    os.close(fd)
    temp_path = Path(temp_name)
    try:
        attachment.SaveAsFile(str(temp_path))
        os.replace(temp_path, destination)
    finally:
        if temp_path.exists():
            temp_path.unlink(missing_ok=True)


def sync_once(base_dir: str | Path, progress=None, dry_run: bool = False) -> dict:
    """Download filtered Outlook attachments and import them into the local DB.

    This function is intentionally Windows/Outlook-only at execution time.  The
    module can still be imported and its configuration can be validated on other
    platforms.
    """
    base_dir = Path(base_dir)
    config = load_config(base_dir)
    input_folder = Path(os.path.expandvars(os.path.expanduser(config["input_folder"])))
    input_folder.mkdir(parents=True, exist_ok=True)
    manifest = load_manifest(base_dir)
    processed = manifest.setdefault("processed", {})

    try:
        import win32com.client  # type: ignore
    except ImportError as exc:
        raise RuntimeError("Outlook sync needs Microsoft Outlook and pywin32. Install requirements.txt on Windows.") from exc

    outlook = win32com.client.Dispatch("Outlook.Application")
    session = outlook.GetNamespace("MAPI")
    downloaded = []
    skipped = 0
    errors = []

    for message in _iter_candidate_messages(session, config):
        matches = _message_matches(message, config)
        for match in matches:
            filename = match["filename"]
            key = _message_key(message, filename)
            destination = input_folder / Path(filename).name
            if key in processed and destination.exists():
                skipped += 1
                continue
            try:
                if progress:
                    progress(f"Saving {filename}")
                if not dry_run:
                    _save_attachment(match["attachment"], destination)
                    # Import after the atomic save so the DB never sees a partial ZIP.
                    from huawei_site_search_tool import Store, import_path
                    db = Store(str(base_dir / "site_inventory.sqlite3"))
                    import_path(db, str(destination), progress=lambda ds, n: progress(f"{ds}: {n:,} rows") if progress else None)
                processed[key] = {
                    "filename": filename,
                    "destination": str(destination),
                    "vendor": match["rule"].get("vendor", ""),
                    "subject": _text(getattr(message, "Subject", "")),
                    "received": _text(getattr(message, "ReceivedTime", "")),
                }
                downloaded.append(str(destination))
            except Exception as exc:
                errors.append(f"{filename}: {exc}")

    if not dry_run:
        save_manifest(base_dir, manifest)
    return {"downloaded": downloaded, "skipped": skipped, "errors": errors, "input_folder": str(input_folder)}


def validate_config(base_dir: str | Path) -> dict:
    base_dir = Path(base_dir)
    config = load_config(base_dir)
    rules = config.get("rules", [])
    return {
        "input_folder": config.get("input_folder", ""),
        "rule_count": len(rules),
        "rules": [{"vendor": r.get("vendor"), "subject_contains": r.get("subject_contains"),
                   "attachment_patterns": r.get("attachment_patterns")} for r in rules],
    }


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Daily Outlook attachment sync for the multi-vendor site tool")
    parser.add_argument("--sync-now", action="store_true", help="download filtered attachments and import them")
    parser.add_argument("--dry-run", action="store_true", help="validate Outlook matching without saving/importing")
    parser.add_argument("--validate-config", action="store_true", help="print the current sync configuration")
    args = parser.parse_args()
    base_dir = default_base_dir()
    if args.validate_config or not (args.sync_now or args.dry_run):
        print(json.dumps(validate_config(base_dir), indent=2))
        if not (args.sync_now or args.dry_run):
            return 0
    try:
        result = sync_once(base_dir, progress=print, dry_run=args.dry_run)
        print(json.dumps(result, indent=2))
        return 0 if not result.get("errors") else 2
    except Exception as exc:
        print(f"SYNC FAILED: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
