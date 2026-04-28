from dataclasses import dataclass
from datetime import date, datetime, timedelta, time
from pathlib import Path
import random

from todoist_api_python.models import Task


@dataclass
class Tasks:
    fixed_tasks: list[Task]
    flexible_tasks: list[Task]


def _parse_time(value: str) -> time:
    return datetime.strptime(value, "%H:%M").time()


def _minutes_between(start: time, end: time) -> int:
    start_minutes = start.hour * 60 + start.minute
    end_minutes = end.hour * 60 + end.minute
    minutes = end_minutes - start_minutes
    if minutes <= 0:
        raise ValueError("due.end_time must be later than due.start_time")
    return minutes


def json_to_tasks(json_path: Path, today: date) -> Tasks:
    import json

    with open(json_path, "r") as f:
        data = json.load(f)

    tasks = []

    for task_data in data["tasks"]:
        for _ in range(task_data.get("copies", 1)):
            deadline_date = None
            if "deadline" in task_data:
                deadline_offset = int(task_data["deadline"]["offset_days"])
                deadline_date = today + timedelta(days=deadline_offset)

            due_datetime = None
            if "due" in task_data:
                due = task_data["due"]
                due_offset = int(due["offset_days"])
                start_time = _parse_time(str(due["start_time"]))
                end_time = _parse_time(str(due["end_time"]))

                due_date = today + timedelta(days=due_offset)
                due_datetime = datetime.combine(due_date, start_time)
                duration_minutes = _minutes_between(start_time, end_time)

            task_spec = {
                "content": task_data["content"],
                "description": task_data.get("description", ""),
                "priority": task_data.get("priority", 1),
                "deadline": deadline_date,
                "labels": task_data.get("labels", []),
                "due_date": due_datetime,
                "duration_min": duration_minutes if due_datetime else None,
            }

            task = _create_mocked_task(**task_spec)

            tasks.append(task)

    fixed_tasks = [task for task in tasks if "fixed" in task.labels]
    flexible_tasks = [task for task in tasks if "fixed" not in task.labels]

    return Tasks(fixed_tasks=fixed_tasks, flexible_tasks=flexible_tasks)


def _create_mocked_task(
    priority: int,
    due_date: datetime,
    deadline: date | None,
    duration_min: int,
    labels: list[str] = [],
    content: str = "",
    description: str = "",
) -> Task:
    deadline_val = (
        None
        if deadline is None
        else {"date": deadline.isoformat().split("T")[0], "lang": "en"}
    )
    due = (
        {
            "date": due_date.isoformat(),
            "timezone": "Europe/Moscow",
            "string": "",
            "lang": "en",
            "is_recurring": True,
        }
        if due_date is not None
        else None
    )

    task_dict = {
        "id": random.randint(1, 1000000),
        "content": content,
        "description": description,
        "labels": labels,
        "priority": priority,
        "due": due,
        "deadline": deadline_val,
        "duration": {
            "amount": duration_min,
            "unit": "minute",
        },
        "project_id": "6Jf8VQXxpwv56VQ7",
        "section_id": "3Ty8VQXxpwv28PK3",
        "parent_id": "6X7rf9x6pv2FGghW",
        "is_collapsed": False,
        "child_order": 3,
        "day_order": -1,
        "responsible_uid": "2423523",
        "assigned_by_uid": "2971358",
        "completed_at": None,
        "added_by_uid": "34567",
        "added_at": "2014-09-26T08:25:05.000000Z",
        "updated_at": "2016-01-02T21:00:30.000000Z",
    }

    return Task.from_dict(task_dict)
