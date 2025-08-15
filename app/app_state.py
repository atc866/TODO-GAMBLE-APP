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
    def window_for(self, base_date: datetime) -> Tuple[datetime, datetime]:
        """Creation window for a specific calendar day (local time)."""
        start_t = self._parse_hhmm(self.settings["creation_window"]["start"])
        end_t = self._parse_hhmm(self.settings["creation_window"]["end"])
        start_dt = base_date.replace(hour=start_t.hour, minute=start_t.minute, second=0, microsecond=0)
        end_dt = base_date.replace(hour=end_t.hour, minute=end_t.minute, second=0, microsecond=0)
        if end_dt <= start_dt:
            end_dt = end_dt + timedelta(days=1)
        return start_dt, end_dt

    # ---------- Task lifecycle ----------
    def add_task(self, description: str, buy_in: float, payout: float) -> Task:
        if not description.strip():
            raise ValueError("Description is required")
        if not self.in_creation_window():
            raise PermissionError("Task creation is only allowed during the creation window.")

        now = datetime.now()
        # compute NEXT day's window end
        next_day = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        _, next_end = self.window_for(next_day)

        t = Task.new(description, buy_in, payout,
                    due_at=next_end.isoformat(),
                    created_at=now.isoformat())
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

    def delete_task(self, task_id: str) -> dict:
        """
        Delete a pending task.
        - Free if deleted before the next day's creation window starts.
        - Penalize (-0.5 * buy_in) if deleted during/after the next day's creation window.
        Returns: {'penalized': bool, 'penalty': float}
        """
        now = datetime.now()
        for i, t in enumerate(self.tasks):
            if t.id != task_id or t.status != "pending":
                continue

            # Infer the 'creation day' from due_at (the window end of creation day)
            # due_at exists for pending tasks created via add_task
            if not t.due_at:
                # fallback: if missing, treat as free before today’s window start, penalize otherwise
                start_today, _ = self.window_today()
                penalize = start_next <= now <= end_next
            else:
                try:
                    due = datetime.fromisoformat(t.due_at)
                except Exception:
                    due = now
                # Next day's window start
                next_day = (due + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
                start_next, end_next = self.window_for(next_day)
                # Penalize iff within or after that next-day window (you can narrow to only within by using start_next <= now <= end_next)
                penalize = start_next <= now

            if penalize:
                penalty = round(-0.5 * float(t.buy_in), 2)
                # ledger
                self.balance = storage.append_ledger_entry({
                    "type": "delete_penalty",
                    "task_id": t.id,
                    "description": t.description,
                    "amount": penalty,
                })
                # history
                storage.append_history({
                    "event": "deleted_penalty",
                    "task_id": t.id,
                    "description": t.description,
                    "buy_in": t.buy_in,
                    "payout": penalty,  # store penalty as negative payout for table display
                })
                result = {"penalized": True, "penalty": penalty}
            else:
                storage.append_history({
                    "event": "deleted_free",
                    "task_id": t.id,
                    "description": t.description,
                    "buy_in": t.buy_in,
                    "payout": 0.0,
                })
                result = {"penalized": False, "penalty": 0.0}

            # remove from active
            self.tasks.pop(i)
            storage.save_tasks(self.tasks)
            return result

        raise KeyError(f"Task not found or not pending: {task_id}")

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
    
        # ---------- Reverts / refunds ----------
    def record_purchase(self, description: str, amount: float) -> None:
        """(already added earlier)"""
        amt = float(amount)
        if amt <= 0:
            raise ValueError("Purchase amount must be positive.")
        self.balance = storage.append_ledger_entry({
            "type": "purchase",
            "description": description.strip(),
            "amount": -amt,
        })
        storage.append_history({
            "event": "purchase",
            "description": description.strip(),
            "buy_in": 0.0,
            "payout": -amt,
        })

    def revert_purchase(self, description: str, amount: float) -> None:
        """Refund a prior purchase by adding a positive ledger entry and history row."""
        amt = float(amount)
        if amt <= 0:
            raise ValueError("Amount must be positive.")
        self.balance = storage.append_ledger_entry({
            "type": "refund",
            "description": description.strip(),
            "amount": +amt,
        })
        storage.append_history({
            "event": "refund",
            "description": description.strip(),
            "buy_in": 0.0,
            "payout": +amt,
        })

    def _restore_task(self, snapshot: dict) -> None:
        """Restore a task to 'pending' with a fresh due_at (end of today's window)."""
        from .models import Task
        # Compute a new due_at: end of today’s creation window
        _, end_dt = self.window_today()
        due = end_dt.isoformat()
        # Try to reuse original id if it doesn't collide; else create a new one
        orig_id = snapshot.get("id") or snapshot.get("task_id")
        existing_ids = {t.id for t in self.tasks}
        if not orig_id or orig_id in existing_ids:
            # new task with new id
            t = Task.new(snapshot["description"], float(snapshot["buy_in"]), float(snapshot["payout"]), due_at=due)
        else:
            # reuse original id
            t = Task(
                id=orig_id,
                description=snapshot["description"],
                buy_in=float(snapshot["buy_in"]),
                payout=float(snapshot["payout"]),
                status="pending",
                due_at=due,
            )
        self.tasks.append(t)
        storage.save_tasks(self.tasks)

    def revert_completion(self, task_snapshot: dict, restore: bool = True) -> None:
        """Reverse a completed task's payout; optionally restore the task."""
        payout = float(task_snapshot["payout"])
        self.balance = storage.append_ledger_entry({
            "type": "revert_payout",
            "task_id": task_snapshot.get("id") or task_snapshot.get("task_id"),
            "description": task_snapshot["description"],
            "amount": -payout,
        })
        storage.append_history({
            "event": "reverted_completion",
            "task_id": task_snapshot.get("id") or task_snapshot.get("task_id"),
            "description": task_snapshot["description"],
            "buy_in": float(task_snapshot["buy_in"]),
            "payout": float(task_snapshot["payout"]),
        })
        if restore:
            self._restore_task(task_snapshot)

    def revert_forfeit(self, task_snapshot: dict, restore: bool = True) -> None:
        """Reverse a forfeit (give the buy-in back); optionally restore the task."""
        buy_in = float(task_snapshot["buy_in"])
        self.balance = storage.append_ledger_entry({
            "type": "revert_forfeit",
            "task_id": task_snapshot.get("id") or task_snapshot.get("task_id"),
            "description": task_snapshot["description"],
            "amount": +buy_in,
        })
        storage.append_history({
            "event": "reverted_forfeit",
            "task_id": task_snapshot.get("id") or task_snapshot.get("task_id"),
            "description": task_snapshot["description"],
            "buy_in": float(task_snapshot["buy_in"]),
            "payout": float(task_snapshot["payout"]),
        })
        if restore:
            self._restore_task(task_snapshot)

    
   