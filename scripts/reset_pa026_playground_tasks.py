#!/usr/bin/env python3
"""Delete all tasks in a Todoist project and recreate them from a JSON seed file."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
import json
import os
from pathlib import Path
from typing import Any

from todoist_api_python.api import TodoistAPI


DEFAULT_SEED_FILE = Path(__file__).with_name("pa026_playground_tasks.json")


@dataclass(frozen=True)
class TaskSpec:
    content: str
    labels: list[str]
    priority: int
    due_datetime: datetime
    duration_minutes: int
    deadline_date: date | None


def _parse_time(value: str) -> time:
    return datetime.strptime(value, "%H:%M").time()


def _minutes_between(start: time, end: time) -> int:
    start_minutes = start.hour * 60 + start.minute
    end_minutes = end.hour * 60 + end.minute
    minutes = end_minutes - start_minutes
    if minutes <= 0:
        raise ValueError("schedule.end_time must be later than schedule.start_time")
    return minutes


def _resolve_priority(value: str | int | None) -> int:
    if value is None:
        return 1
    if isinstance(value, int):
        if value in (1, 2, 3, 4):
            return value
        raise ValueError("priority integer must be one of: 1, 2, 3, 4")
    normalized = value.strip().lower()
    mapping = {
        "p1": 4,
        "p2": 3,
        "p3": 2,
        "p4": 1,
    }
    if normalized not in mapping:
        raise ValueError("priority must be p1/p2/p3/p4 or integer 1-4")
    return mapping[normalized]


def _build_task_specs(tasks_raw: list[dict[str, Any]], today: date) -> list[TaskSpec]:
    specs: list[TaskSpec] = []
    for item in tasks_raw:
        content = str(item["content"])
        labels = [str(label) for label in item.get("labels", [])]
        priority = _resolve_priority(item.get("priority"))

        schedule = item["schedule"]
        schedule_offset = int(schedule["offset_days"])
        start_time = _parse_time(str(schedule["start_time"]))
        end_time = _parse_time(str(schedule["end_time"]))

        due_date = today + timedelta(days=schedule_offset)
        due_datetime = datetime.combine(due_date, start_time)
        duration_minutes = _minutes_between(start_time, end_time)

        deadline = item.get("deadline")
        deadline_date = None
        if deadline is not None:
            deadline_offset = int(deadline["offset_days"])
            deadline_date = today + timedelta(days=deadline_offset)

        specs.append(
            TaskSpec(
                content=content,
                labels=labels,
                priority=priority,
                due_datetime=due_datetime,
                duration_minutes=duration_minutes,
                deadline_date=deadline_date,
            )
        )

    return specs


def _find_project_id(api: TodoistAPI, project_name: str) -> str:
    pages = api.search_projects(query=project_name, limit=1)
    for page in pages:
        for project in page:
            if project.name == project_name:
                return str(project.id)
    raise RuntimeError(f"Project '{project_name}' not found")


def _delete_all_project_tasks(api: TodoistAPI, project_id: str) -> int:
    deleted = 0
    tasks = api.get_tasks(project_id=project_id, limit=200)

    for page in tasks:
        for task in page:
            api.delete_task(task_id=str(task.id))
            deleted += 1

    return deleted


def _create_tasks(api: TodoistAPI, project_id: str, specs: list[TaskSpec]) -> int:
    created = 0
    for spec in specs:
        kwargs: dict[str, Any] = {
            "project_id": project_id,
            "content": spec.content,
            "labels": spec.labels,
            "priority": spec.priority,
            "due_datetime": spec.due_datetime,
            "duration": spec.duration_minutes,
            "duration_unit": "minute",
            "deadline_date": spec.deadline_date,
        }

        api.add_task(
            **kwargs,
        )
        created += 1
    return created


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Delete all tasks in a Todoist project and recreate them from JSON with relative dates."
        )
    )
    parser.add_argument(
        "--seed-file",
        type=Path,
        default=DEFAULT_SEED_FILE,
        help=f"Path to the JSON seed file (default: {DEFAULT_SEED_FILE.name})",
    )
    args = parser.parse_args()

    token = os.getenv("TODOIST_API_TOKEN")
    if not token:
        raise EnvironmentError("Missing TODOIST_API_TOKEN environment variable")

    seed_file = args.seed_file.resolve()
    if not seed_file.exists():
        raise FileNotFoundError(f"Seed file not found: {seed_file}")

    with seed_file.open("r", encoding="utf-8") as f:
        seed_data = json.load(f)

    project_name = str(seed_data["project_name"])
    tasks_raw = list(seed_data["tasks"])

    today = datetime.now().date()
    specs = _build_task_specs(tasks_raw=tasks_raw, today=today)

    api = TodoistAPI(token=token)
    project_id = _find_project_id(api=api, project_name=project_name)
    deleted = _delete_all_project_tasks(api=api, project_id=project_id)
    created = _create_tasks(api=api, project_id=project_id, specs=specs)

    print(f"Project: {project_name}")
    print(f"Deleted tasks: {deleted}")
    print(f"Created tasks: {created}")


if __name__ == "__main__":
    main()
