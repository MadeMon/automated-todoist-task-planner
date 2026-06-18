#!/usr/bin/env python3
"""Delete all tasks in a Todoist project and recreate them from a JSON seed file."""

from __future__ import annotations

import asyncio
import argparse
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
import json
import os
from pathlib import Path
from typing import Any

from todoist_api_python.models import Task
from todoist_api_python.api_async import TodoistAPIAsync


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
        raise ValueError("due.end_time must be later than due.start_time")
    return minutes


def _build_task_specs(tasks_raw: list[dict[str, Any]], today: date) -> list[TaskSpec]:
    specs: list[TaskSpec] = []
    for item in tasks_raw:
        content = str(item["content"])
        labels = [str(label) for label in item.get("labels", [])]
        priority = item.get("priority", 1)
        copies = item.get("copies", 1)

        due = item["due"]
        due_offset = int(due["offset_days"])
        start_time = _parse_time(str(due["start_time"]))
        end_time = _parse_time(str(due["end_time"]))

        due_date = today + timedelta(days=due_offset)
        due_datetime = datetime.combine(due_date, start_time)
        duration_minutes = _minutes_between(start_time, end_time)

        deadline = item.get("deadline")
        deadline_date = None
        if deadline is not None:
            deadline_offset = int(deadline["offset_days"])
            deadline_date = today + timedelta(days=deadline_offset)

        for _ in range(copies):
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


async def _find_project_id(api: TodoistAPIAsync, project_name: str) -> str:
    pages = await api.search_projects(query=project_name, limit=1)
    async for page in pages:
        for project in page:
            if project.name == project_name:
                return str(project.id)
    raise RuntimeError(f"Project '{project_name}' not found")


async def _get_all_project_tasks(api: TodoistAPIAsync, project_id: str) -> list[Task]:
    tasks_pages = await api.get_tasks(project_id=project_id, limit=200)
    tasks: list[Task] = []

    async for page in tasks_pages:
        for task in page:
            tasks.append(task)

    return tasks


async def _delete_tasks(api: TodoistAPIAsync, tasks: list[Task]) -> int:
    task_ids = [str(task.id) for task in tasks]

    if not task_ids:
        return 0

    await asyncio.gather(*(api.delete_task(task_id=task_id) for task_id in task_ids))
    return len(task_ids)


async def _create_tasks(
    api: TodoistAPIAsync, project_id: str, specs: list[TaskSpec]
) -> int:
    semaphore = asyncio.Semaphore(20)

    async def _create_one(spec: TaskSpec) -> None:
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

        async with semaphore:
            await api.add_task(
                **kwargs,
            )

    await asyncio.gather(*(_create_one(spec) for spec in specs))
    return len(specs)


async def async_main() -> None:
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

    api = TodoistAPIAsync(token=token)
    project_id = await _find_project_id(api=api, project_name=project_name)
    existing_tasks = await _get_all_project_tasks(api=api, project_id=project_id)
    deleted, created = await asyncio.gather(
        _delete_tasks(api=api, tasks=existing_tasks),
        _create_tasks(api=api, project_id=project_id, specs=specs),
    )

    print(f"Project: {project_name}")
    print(f"Deleted tasks: {deleted}")
    print(f"Created tasks: {created}")


def main() -> None:
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
