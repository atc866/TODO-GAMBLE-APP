# =============================
# File: app/app_state.py
# =============================
from __future__ import annotations
from typing import List, Tuple
from datetime import datetime, time, timedelta

from .models import Task
from . import storage


class AppState:
    def __init__(self) -> None:
        self.settings = storage.load_settings()
        self.tasks: List[Task] = storage.load_tasks()
        self.balance: float = storage.compute_balance()
        self._retro_process_overdue()
        storage.purge_history_if_monday()

    # ---------- Settings ----------
    def set_window_times(self, start_hhmm: str, end_hhmm: str) -> None:
        self.settings["creation_window"] = {"start": start_hhmm, "end": end_hhmm}
        storage.save_settings(self.settings)

    # ---------- Window helpers ----------
    def _parse_hhmm(self, s: str) -> time:
        hh, mm = map(int, s.split(":"))
        return time(hour=hh, minute=mm)

    def window_today(self) -> Tuple[datetime, datetime]:
        now = datetime.now()
        start_t = self._parse_hhmm(self.settings["creation_window"]["start"])
        end_t = self._parse_hhmm(self.settings["creation_window"]["end"])
        start_dt = now.replace(hour=start_t.hour, minute=start_t.minute, second=0, microsecond=0)
        end_dt = now.replace(hour=end_t.hour, minute=end_t.minute, second=0, microsecond=0)
        # If end before start, assume crosses midnight — push end to next day
        if end_dt <= start_dt:
            end_dt = end_dt + timedelta(days=1)
        return start_dt, end_dt

    def in_creation_window(self, at: datetime | None = None) -> bool:
        at = at or datetime.now()
        start_dt, end_dt = self.window_today()
        # If at < start but yesterday's window crosses midnight, adjust
        if at < start_dt and (end_dt - start_dt) > timedelta(hours=12):
            # Recompute using yesterday's start
            y = at - timedelta(days=1)
            start_dt = y.replace(hour=start_dt.hour, minute=start_dt.minute, second=0, microsecond=0)
            end_dt = start_dt + (end_dt - (datetime.now().replace(hour=start_dt.hour, minute=start_dt.minute, second=0, microsecond=0)))
        return start_dt <= at <= end_dt

    # ---------- Task lifecycle ----------
    def add_task(self, description: str, buy_in: float, payout: float) -> Task:
        if not description.strip():
            raise ValueError("Description is required")
        if not self.in_creation_window():
            raise PermissionError("Task creation is only allowed during the creation window.")
        _, end_dt = self.window_today()
        t = Task.new(description, buy_in, payout, due_at=end_dt.isoformat())
        self.tasks.append(t)
        storage.save_tasks(self.tasks)
        return t

    def complete_task(self, task_id: str) -> None:
        for i, t in enumerate(self.tasks):
            if t.id == task_id:
                t.status = "completed"
                self.balance = storage.append_ledger_entry({
                    "type": "payout",
                    "task_id": t.id,
                    "description": t.description,
                    "amount": float(t.payout),
                })
                storage.append_history({
                    "event": "completed",
                    "task_id": t.id,
                    "description": t.description,
                    "buy_in": t.buy_in,
                    "payout": t.payout,
                })
                self.tasks.pop(i)
                storage.save_tasks(self.tasks)
                return
        raise KeyError(f"Task not found: {task_id}")

    def forfeit_overdue(self) -> int:
        """Forfeit tasks whose due_at <= now. Returns count forfeited."""
        now = datetime.now().isoformat()
        keep: List[Task] = []
        forfeited = 0
        for t in self.tasks:
            if t.status == "pending" and t.due_at and t.due_at <= now:
                forfeited += 1
                self.balance = storage.append_ledger_entry({
                    "type": "forfeit",
                    "task_id": t.id,
                    "description": t.description,
                    "amount": -float(t.buy_in),
                })
                storage.append_history({
                    "event": "forfeited",
                    "task_id": t.id,
                    "description": t.description,
                    "buy_in": t.buy_in,
                    "payout": t.payout,
                })
            else:
                keep.append(t)
        if forfeited:
            self.tasks = keep
            storage.save_tasks(self.tasks)
        return forfeited

    def _retro_process_overdue(self) -> None:
        # Called on startup to catch any tasks that missed their window while app was closed
        self.forfeit_overdue()
    
    def record_purchase(self, description: str, amount: float) -> None:
        """Subtracts from balance and logs to history as a 'purchase' event."""
        if not description.strip():
            raise ValueError("Description is required")
        try:
            amt = float(amount)
        except Exception:
            raise ValueError("Amount must be a number")
        if amt <= 0:
            raise ValueError("Purchase amount must be positive")

        # Ledger: negative amount
        self.balance = storage.append_ledger_entry({
            "type": "purchase",
            "description": description.strip(),
            "amount": -amt,
        })
        # History: keep schema compatible with table (buy_in/payout columns)
        storage.append_history({
            "event": "purchase",
            "description": description.strip(),
            "buy_in": 0.0,
            "payout": -amt,
        })
