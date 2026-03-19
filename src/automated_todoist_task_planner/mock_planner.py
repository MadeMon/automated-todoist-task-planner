"""Mock planner implementation used for local testing workflows."""

from __future__ import annotations

from copy import deepcopy
from datetime import date

from todoist_api_python.models import Due, Task


class MockPlanner:
    """A mock planner that schedules all input tasks to today."""

    def plan(self, tasks: list[Task]) -> list[Task]:
        """Return tasks sorted by priority and scheduled to today.

        Priority order follows Todoist semantics where 4 is highest urgency.
        """
        planned_tasks = deepcopy(tasks)
        planned_tasks.sort(key=lambda task: task.priority, reverse=True)

        today = date.today()
        for task in planned_tasks:
            task.due = Due(
                date=today,
                string="today",
                lang="en",
                is_recurring=False,
                timezone=None,
            )

        return planned_tasks
