"""Bar タスク管理のタスク記録の読み出し。"""

import datetime
import json
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Task:
    name: str
    assignee: str
    completed_on: datetime.date | None


def load_tasks(path: Path) -> list[Task]:
    """タスク記録（JSON）を読み、タスクの一覧を返す。"""
    records = json.loads(path.read_text(encoding="utf-8"))
    tasks = []
    for record in records:
        completed = record.get("completed_on")
        tasks.append(
            Task(
                name=record["name"],
                assignee=record["assignee"],
                completed_on=datetime.date.fromisoformat(completed) if completed else None,
            )
        )
    return tasks
