"""Mock planner implementation used for local testing workflows."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from typing import TYPE_CHECKING

from todoist_api_python.models import Task

from .base_planner import BasePlanner, PlanningResult

if TYPE_CHECKING:
    from ..tasks_schedule import TasksSchedule


class MockPlanner(BasePlanner):
    """A mock planner that schedules all input tasks to today."""

    def _plan(
        self,
        planning_from_date: datetime,
        planning_to_date: datetime,
        schedule: TasksSchedule,
        flexible_tasks: list[Task],
        fixed_tasks: list[Task],
    ) -> PlanningResult:
        """Return tasks sorted by priority and scheduled to today.

        Priority order follows Todoist semantics where 4 is highest urgency.
        """

        failed_to_schedule = []
        planned_tasks = deepcopy(flexible_tasks)
        planned_tasks.sort(key=lambda task: task.priority, reverse=True)

        for task in planned_tasks:
            try:
                schedule.schedule_task_to_first_available_slot_balance_days(task)
            except ValueError:
                failed_to_schedule.append(task)
                continue

            print("Scheduled task", task.content, "to", schedule.days[0][-1].start)

        return PlanningResult(schedule=schedule, failed_to_schedule=failed_to_schedule)
