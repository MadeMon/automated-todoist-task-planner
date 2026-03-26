"""Thin wrapper around the Todoist SDK for task fetch and selective updates."""

from __future__ import annotations

from datetime import datetime
import logging
from typing import Any

from todoist_api_python.api import TodoistAPI
from todoist_api_python.models import Task

from .planners.base_planner import PlanningResult


logger = logging.getLogger(__name__)

PLANNING_FAILED_LABEL = "planning_failed"


class TodoistTaskClient:
    """Adapter over Todoist SDK calls used by this project."""

    _MAX_IDS_PER_REQUEST = 200

    def __init__(self, api_token: str) -> None:
        self._api = TodoistAPI(token=api_token)

    def fetch_tasks_with_duration_due_soon_or_overdue(
        self, query: str
    ) -> list[Task]:
        """Return tasks that are overdue or due in next two weeks and have duration."""
        active_query = query
        tasks = [
            task
            for page in self._api.filter_tasks(query=active_query)
            for task in page
            if task.duration is not None
        ]
        return tasks

    def update_tasks(self, planning_result: PlanningResult) -> list[Task]:
        """Update only tasks whose due or labels changed compared to Todoist state."""

        all_task_ids = [task.id for task in [scheduled_task.task for scheduled_task in planning_result.schedule.get_scheduled_tasks()] +  planning_result.failed_to_schedule]
        current_by_id = self._fetch_current_tasks_by_id(task_ids=all_task_ids)

        # Add a "planning_failed" label to tasks that failed to schedule and remove it from tasks that were successfully scheduled.
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
                self._api.update_task(task.id, labels=labels)

        # TODO update the tasks in batch call
        updated_tasks: list[Task] = []
        for scheduled_task in planning_result.schedule.get_scheduled_tasks():
            current_task = current_by_id.get(scheduled_task.task.id)
            if current_task is None:
                logger.warning(
                    "Skipping task id=%s because it was not found in Todoist", scheduled_task.task.id
                )
                continue

            labels = None
            if current_task.labels is not None and PLANNING_FAILED_LABEL in current_task.labels:
                labels = [label for label in current_task.labels if label != PLANNING_FAILED_LABEL]
            update_payload = self._build_update_payload(current=current_task, labels=labels, scheduled_due=scheduled_task.start)
            if not update_payload:
                continue

            updated_task = self._api.update_task(scheduled_task.task.id, **update_payload)
            updated_tasks.append(updated_task)

        return updated_tasks

    def _fetch_current_tasks_by_id(self, task_ids: list[str]) -> dict[str, Task]:
        unique_ids = list(dict.fromkeys(task_ids))
        current_by_id: dict[str, Task] = {}

        for start in range(0, len(unique_ids), self._MAX_IDS_PER_REQUEST):
            ids_batch = unique_ids[start : start + self._MAX_IDS_PER_REQUEST]
            for page in self._api.get_tasks(ids=ids_batch, limit=self._MAX_IDS_PER_REQUEST):
                for task in page:
                    current_by_id[task.id] = task

        return current_by_id

    def _build_update_payload(self, current: Task, labels: list[str] | None, scheduled_due: datetime) -> dict[str, Any]:
        payload: dict[str, Any] = {}

        if scheduled_due is not None and (current.due is None or current.due.date.isoformat() != scheduled_due.isoformat()):
            payload["due_datetime"] = scheduled_due

        if labels is not None:
            payload["labels"] = labels

        return payload
