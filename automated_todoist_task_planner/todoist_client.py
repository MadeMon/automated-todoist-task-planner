"""Thin wrapper around the Todoist SDK for task fetch and selective updates."""

from __future__ import annotations

import asyncio
from datetime import datetime
import logging
from typing import Any

from todoist_api_python.api_async import TodoistAPIAsync
from todoist_api_python.models import Task

from .planners.base_planner import PlanningResult


logger = logging.getLogger(__name__)

PLANNING_FAILED_LABEL = "planning_failed"


class TodoistTaskClient:
    """Adapter over Todoist SDK calls used by this project."""

    _MAX_IDS_PER_REQUEST = 200
    _MAX_CONCURRENT_UPDATES = 20

    def __init__(self, api_token: str) -> None:
        self._api = TodoistAPIAsync(token=api_token)

    async def fetch_tasks_with_duration_due_soon_or_overdue(
        self, query: str
    ) -> list[Task]:
        """Return tasks that are overdue or due in next two weeks and have duration."""
        active_query = query
        tasks_pages = await self._api.filter_tasks(query=active_query)
        tasks: list[Task] = []
        async for page in tasks_pages:
            for task in page:
                if task.duration is not None:
                    tasks.append(task)
        return tasks

    async def update_tasks(self, planning_result: PlanningResult) -> list[Task]:
        """Update only tasks whose due or labels changed compared to Todoist state."""

        all_task_ids = [
            task.id
            for task in [
                scheduled_task.task
                for scheduled_task in planning_result.schedule.get_scheduled_tasks()
            ]
            + planning_result.failed_to_schedule
        ]
        current_by_id = await self._fetch_current_tasks_by_id(task_ids=all_task_ids)
        semaphore = asyncio.Semaphore(self._MAX_CONCURRENT_UPDATES)

        # Add a "planning_failed" label to tasks that failed to schedule and remove it from tasks that were successfully scheduled.
        failed_label_update_coroutines: list[asyncio.Future[Any] | Any] = []
        for task in planning_result.failed_to_schedule:
            logger.warning(f"Failed to schedule task {task.content} (id={task.id})")
            current_task = current_by_id.get(task.id)
            if current_task is None:
                logger.warning(
                    "Skipping task id=%s because it was not found in Todoist", task.id
                )
                continue

            labels = current_task.labels or []
            if PLANNING_FAILED_LABEL not in labels:
                labels.append(PLANNING_FAILED_LABEL)

                async def _update_failed_task(
                    task_id: str, task_labels: list[str]
                ) -> None:
                    async with semaphore:
                        await self._api.update_task(task_id, labels=task_labels)

                failed_label_update_coroutines.append(
                    _update_failed_task(task_id=task.id, task_labels=labels)
                )

        if failed_label_update_coroutines:
            await asyncio.gather(*failed_label_update_coroutines)

        # TODO update the tasks in batch call
        update_coroutines: list[asyncio.Future[Any] | Any] = []
        updated_tasks: list[Task] = []
        for scheduled_task in planning_result.schedule.get_scheduled_tasks():
            current_task = current_by_id.get(scheduled_task.task.id)
            if current_task is None:
                logger.warning(
                    "Skipping task id=%s because it was not found in Todoist",
                    scheduled_task.task.id,
                )
                continue

            labels = None
            if (
                current_task.labels is not None
                and PLANNING_FAILED_LABEL in current_task.labels
            ):
                labels = [
                    label
                    for label in current_task.labels
                    if label != PLANNING_FAILED_LABEL
                ]
            update_payload = self._build_update_payload(
                current=current_task, labels=labels, scheduled_due=scheduled_task.start
            )
            if not update_payload:
                continue

            async def _update_scheduled_task(
                task_id: str, payload: dict[str, Any]
            ) -> Task:
                async with semaphore:
                    return await self._api.update_task(task_id, **payload)

            update_coroutines.append(
                _update_scheduled_task(
                    task_id=scheduled_task.task.id,
                    payload=update_payload,
                )
            )

        if update_coroutines:
            updated_tasks = list(await asyncio.gather(*update_coroutines))

        return updated_tasks

    async def _fetch_current_tasks_by_id(self, task_ids: list[str]) -> dict[str, Task]:
        unique_ids = list(dict.fromkeys(task_ids))
        current_by_id: dict[str, Task] = {}

        for start in range(0, len(unique_ids), self._MAX_IDS_PER_REQUEST):
            ids_batch = unique_ids[start : start + self._MAX_IDS_PER_REQUEST]
            tasks_pages = await self._api.get_tasks(
                ids=ids_batch, limit=self._MAX_IDS_PER_REQUEST
            )
            async for page in tasks_pages:
                for task in page:
                    current_by_id[task.id] = task

        return current_by_id

    def _build_update_payload(
        self, current: Task, labels: list[str] | None, scheduled_due: datetime
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {}

        if scheduled_due is not None and (
            current.due is None
            or current.due.date.isoformat() != scheduled_due.isoformat()
        ):
            payload["due_datetime"] = scheduled_due

        if labels is not None:
            payload["labels"] = labels

        return payload
