"""Thin wrapper around the Todoist SDK for task fetch and selective updates."""

from __future__ import annotations

from datetime import date, datetime
import logging
from typing import Any

from todoist_api_python.api import TodoistAPI
from todoist_api_python.models import Due, Task


logger = logging.getLogger(__name__)


class TodoistTaskClient:
    """Adapter over Todoist SDK calls used by this project."""

    _FETCH_QUERY = "(overdue | 14 days)"
    _MAX_IDS_PER_REQUEST = 200

    def __init__(self, api_token: str) -> None:
        self._api = TodoistAPI(token=api_token)

    def fetch_tasks_with_duration_due_soon_or_overdue(
        self, query: str | None = None
    ) -> list[Task]:
        """Return tasks that are overdue or due in next two weeks and have duration."""
        active_query = query or self._FETCH_QUERY
        tasks = [
            task
            for page in self._api.filter_tasks(query=active_query)
            for task in page
            if task.duration is not None
        ]
        return tasks

    def update_tasks(self, tasks: list[Task]) -> list[Task]:
        """Update only tasks whose due or labels changed compared to Todoist state."""
        if not tasks:
            return []

        current_by_id = self._fetch_current_tasks_by_id(task_ids=[task.id for task in tasks])

        # TODO update the tasks in batch call
        updated_tasks: list[Task] = []
        for candidate in tasks:
            current_task = current_by_id.get(candidate.id)
            if current_task is None:
                logger.warning(
                    "Skipping task id=%s because it was not found in Todoist", candidate.id
                )
                continue

            update_payload = self._build_update_payload(current=current_task, desired=candidate)
            if not update_payload:
                continue

            updated_task = self._api.update_task(candidate.id, **update_payload)
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

    def _build_update_payload(self, current: Task, desired: Task) -> dict[str, Any]:
        payload: dict[str, Any] = {}

        if self._labels_changed(current.labels, desired.labels):
            payload["labels"] = desired.labels or []

        if self._due_changed(current.due, desired.due):
            payload.update(self._due_update_fields(desired.due))

        return payload

    @staticmethod
    def _labels_changed(current: list[str] | None, desired: list[str] | None) -> bool:
        return sorted(current or []) != sorted(desired or [])

    @staticmethod
    def _due_changed(current: Due | None, desired: Due | None) -> bool:
        return TodoistTaskClient._normalize_due(current) != TodoistTaskClient._normalize_due(
            desired
        )

    @staticmethod
    def _normalize_due(due: Due | None) -> tuple[str | None, str | None, str | None, bool | None, str | None] | None:
        if due is None:
            return None

        due_date = due.date
        if hasattr(due_date, "isoformat"):
            due_date_text = due_date.isoformat()
        else:
            due_date_text = str(due_date)

        return (due_date_text, due.string, due.lang, due.is_recurring, due.timezone)

    @staticmethod
    def _due_update_fields(due: Due | None) -> dict[str, Any]:
        if due is None:
            return {"due_string": "no date"}

        # Recurring due dates are best represented by Todoist's natural language string.
        if due.is_recurring and due.string:
            return {"due_string": due.string}

        due_value = due.date
        if isinstance(due_value, datetime):
            return {"due_datetime": due_value}
        if isinstance(due_value, date):
            return {"due_date": due_value}

        return {"due_string": due.string}
