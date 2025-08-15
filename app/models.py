from __future__ import annotations
from dataclasses import dataclass, asdict
from typing import Dict, Any, Optional
import uuid

@dataclass
class Task:
    id: str
    description: str
    buy_in: float
    payout: float
    status: str  # "pending" | "completed" | "forfeited"
    due_at: Optional[str] = None  # ISO string (local tz)
    created_at: Optional[str] = None  # <-- NEW

    @staticmethod
    def new(description: str, buy_in: float, payout: float, due_at: Optional[str],created_at: Optional[str] = None) -> "Task":
        return Task(
            id=str(uuid.uuid4()),
            description=description.strip(),
            buy_in=float(buy_in),
            payout=float(payout),
            status="pending",
            due_at=due_at,
            created_at=created_at,
        )

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "Task":
        return Task(
            id=d["id"],
            description=d["description"],
            buy_in=float(d["buy_in"]),
            payout=float(d["payout"]),
            status=d.get("status", "pending"),
            due_at=d.get("due_at"),
            created_at=d.get("created_at"),
        )
