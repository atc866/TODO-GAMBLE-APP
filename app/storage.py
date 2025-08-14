from __future__ import annotations
import json
from pathlib import Path
from typing import List, Tuple, Dict, Any
from datetime import datetime, timezone
import os

from .models import Task

APP_DIR = Path.home() / ".todo_gamble_app"
TASKS_PATH = APP_DIR / "tasks.json"
LEDGER_PATH = APP_DIR / "ledger.txt"  # JSONL lines
HISTORY_PATH = APP_DIR / "history.jsonl"  # JSONL lines
SETTINGS_PATH = APP_DIR / "settings.json"


def ensure_dirs() -> None:
    APP_DIR.mkdir(parents=True, exist_ok=True)


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()

# -------- Settings --------
DEFAULT_SETTINGS = {
    "creation_window": {"start": "11:00", "end": "12:00"},  # local time HH:MM
}

def load_settings() -> Dict[str, Any]:
    ensure_dirs()
    if not SETTINGS_PATH.exists():
        save_settings(DEFAULT_SETTINGS)
        return DEFAULT_SETTINGS.copy()
    try:
        data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
        # Merge defaults
        merged = DEFAULT_SETTINGS.copy()
        merged.update(data)
        return merged
    except Exception:
        return DEFAULT_SETTINGS.copy()


def save_settings(settings: Dict[str, Any]) -> None:
    ensure_dirs()
    tmp = SETTINGS_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(settings, indent=2), encoding="utf-8")
    tmp.replace(SETTINGS_PATH)

# -------- Tasks --------

def load_tasks() -> List[Task]:
    ensure_dirs()
    if not TASKS_PATH.exists():
        return []
    try:
        data = json.loads(TASKS_PATH.read_text(encoding="utf-8"))
        return [Task.from_dict(x) for x in data]
    except Exception:
        return []


def save_tasks(tasks: List[Task]) -> None:
    ensure_dirs()
    tmp = TASKS_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps([t.to_dict() for t in tasks], indent=2), encoding="utf-8")
    tmp.replace(TASKS_PATH)

# -------- Ledger & History --------

def append_ledger_entry(entry: dict) -> float:
    ensure_dirs()
    balance = compute_balance()
    amount = float(entry.get("amount", 0.0))
    entry = {**entry, "ts": now_iso()}
    new_balance = balance + amount
    entry["balance"] = round(new_balance, 2)
    with LEDGER_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")
    return new_balance


def append_history(entry: dict) -> None:
    ensure_dirs()
    entry = {**entry, "ts": now_iso()}
    with HISTORY_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


def read_history(max_lines: int = 500) -> List[dict]:
    if not HISTORY_PATH.exists():
        return []
    lines = HISTORY_PATH.read_text(encoding="utf-8").splitlines()[-max_lines:]
    out = []
    for ln in lines:
        try:
            out.append(json.loads(ln))
        except Exception:
            continue
    return out


def purge_history_if_monday() -> bool:
    # Purge when today is Monday (0 = Monday)
    if datetime.now().weekday() == 0 and HISTORY_PATH.exists():
        try:
            HISTORY_PATH.unlink()
            return True
        except Exception:
            return False
    return False


def compute_balance() -> float:
    if not LEDGER_PATH.exists():
        return 0.0
    try:
        *_, last = LEDGER_PATH.read_text(encoding="utf-8").splitlines()
        if last.strip():
            import json as _json
            bal = float(_json.loads(last).get("balance", 0.0))
            return bal
    except Exception:
        pass
    total = 0.0
    try:
        with LEDGER_PATH.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    total += float(obj.get("amount", 0.0))
                except Exception:
                    continue
    except Exception:
        return 0.0
    return round(total, 2)


    from datetime import datetime, timezone, timedelta

def _parse_ts(iso: str) -> datetime | None:
    try:
        return datetime.fromisoformat(iso)
    except Exception:
        try:
            # fallback: strip Z if present
            return datetime.fromisoformat(iso.replace("Z",""))
        except Exception:
            return None

def compact_ledger(retain_days: int = 30) -> int:
    """
    Keep only the last `retain_days` of entries. If older entries exist,
    we write a single 'snapshot' line that preserves the balance up to the
    cutoff, then append all lines newer than cutoff.
    Returns number of lines written after compaction.
    """
    ensure_dirs()
    if not LEDGER_PATH.exists():
        return 0

    now = datetime.now(timezone.utc).astimezone()
    cutoff = now - timedelta(days=retain_days)

    lines = LEDGER_PATH.read_text(encoding="utf-8").splitlines()
    if not lines:
        return 0

    # Partition entries by ts
    older_total = 0.0
    newer_lines: list[str] = []
    for ln in lines:
        ln = ln.strip()
        if not ln:
            continue
        try:
            obj = json.loads(ln)
        except Exception:
            continue
        ts = _parse_ts(obj.get("ts", "")) or now
        amt = float(obj.get("amount", 0.0))
        if ts < cutoff:
            older_total += amt
        else:
            newer_lines.append(json.dumps(obj))

    # If nothing to compact, bail
    if not newer_lines and older_total == 0.0:
        return len(lines)

    # Build snapshot + rewrite file atomically
    tmp = LEDGER_PATH.with_suffix(".tmp")
    balance_before = 0.0
    # Compute the balance at cutoff = sum(older_total)
    balance_before = round(older_total, 2)

    # Write a snapshot that encodes the carry-forward balance
    snapshot = {
        "ts": now_iso(),
        "type": "snapshot",
        "description": f"Carry-forward balance after compacting to last {retain_days} days",
        "amount": 0.0,
        "balance": balance_before
    }
    out_lines = [json.dumps(snapshot)] + newer_lines

    tmp.write_text("\n".join(out_lines) + "\n", encoding="utf-8")
    tmp.replace(LEDGER_PATH)
    return len(out_lines)

def purge_data(save_balance: bool = True) -> None:
    """
    Purge storage files to save space.
    - Always deletes history.jsonl and tasks.json (pending tasks).
    - Ledger:
        * If save_balance=True, replace ledger.txt with a single 'snapshot' line preserving current balance.
        * If save_balance=False, delete ledger.txt (balance resets to $0).
    Settings are untouched.
    """
    ensure_dirs()

    # Delete history and tasks
    try:
        HISTORY_PATH.unlink(missing_ok=True)
    except Exception:
        pass
    try:
        TASKS_PATH.unlink(missing_ok=True)
    except Exception:
        pass

    if save_balance:
        bal = compute_balance()
        snapshot = {
            "ts": now_iso(),
            "type": "snapshot",
            "description": "Snapshot after purge",
            "amount": 0.0,
            "balance": round(bal, 2),
        }
        tmp = LEDGER_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(snapshot) + "\n", encoding="utf-8")
        tmp.replace(LEDGER_PATH)
    else:
        try:
            LEDGER_PATH.unlink(missing_ok=True)
        except Exception:
            pass
