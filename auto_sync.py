import fnmatch, json, os, sys
from pathlib import Path
from datetime import datetime


def base_dir():
    return Path(sys.executable).resolve().parent if getattr(sys, 'frozen', False) else Path(__file__).resolve().parent


def load_config():
    p = base_dir() / 'auto_sync_config.json'
    return json.loads(p.read_text(encoding='utf-8')) if p.exists() else {}


def _folders(folder):
    yield folder
    try:
        for child in folder.Folders:
            yield from _folders(child)
    except Exception:
        return


def _matches(msg, rule, sender_contains):
    sender = str(getattr(msg, 'SenderName', '') or '')
    address = str(getattr(msg, 'SenderEmailAddress', '') or '')
    subject = str(getattr(msg, 'Subject', '') or '')
    if sender_contains and sender_contains.lower() not in (sender + ' ' + address).lower():
        return False
    if rule.get('subject_contains', '').lower() not in subject.lower():
        return False
    return True


def sync_once(config=None):
    config = config or load_config()
    folder = config.get('input_folder', '').strip()
    if not folder:
        raise RuntimeError('Set input_folder in auto_sync_config.json or choose Input Folder in the app.')
    out = Path(folder); out.mkdir(parents=True, exist_ok=True)
    manifest_path = base_dir() / 'auto_sync_manifest.json'
    try: manifest = json.loads(manifest_path.read_text(encoding='utf-8')) if manifest_path.exists() else {}
    except Exception: manifest = {}
    try:
        import win32com.client
    except ImportError:
        raise RuntimeError('Outlook sync requires pywin32 and Outlook desktop configured on this laptop.')
    outlook = win32com.client.Dispatch('Outlook.Application')
    ns = outlook.GetNamespace('MAPI')
    rules = config.get('rules', [])
    sender = config.get('sender_contains', 'ENABLE-NOREPLY')
    saved = []
    for root in ns.Folders:
        for fld in _folders(root):
            try: items = fld.Items
            except Exception: continue
            for i in range(1, items.Count + 1):
                try: msg = items.Item(i)
                except Exception: continue
                if getattr(msg, 'Class', None) != 43: continue
                for rule in rules:
                    if not _matches(msg, rule, sender): continue
                    for j in range(1, msg.Attachments.Count + 1):
                        att = msg.Attachments.Item(j); name = str(att.FileName)
                        pattern = rule.get('attachment_contains', '')
                        if pattern and pattern.lower() not in name.lower() and not fnmatch.fnmatch(name.lower(), pattern.lower()):
                            continue
                        key = str(getattr(msg, 'EntryID', '')) + '|' + name
                        target = out / name
                        if manifest.get(key) == name and target.exists(): continue
                        tmp = target.with_suffix(target.suffix + '.tmp')
                        att.SaveAsFile(str(tmp)); os.replace(tmp, target)
                        manifest[key] = name; saved.append(str(target))
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    return saved


if __name__ == '__main__':
    result = sync_once()
    print('Saved %d attachment(s)' % len(result))
