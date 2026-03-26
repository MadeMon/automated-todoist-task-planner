"""Mock planner implementation used for local testing workflows."""

from __future__ import annotations

from copy import deepcopy
from datetime import time

from todoist_api_python.models import Task

from ..tasks_schedule import TasksSchedule

from .base_planner import BasePlanner, PlanningResult


class MockPlanner(BasePlanner):
    """A mock planner that schedules all input tasks to today."""

    def _plan(
        self, flexible_tasks: list[Task], fixed_tasks: list[Task]
    ) -> PlanningResult:
        """Return tasks sorted by priority and scheduled to today.

        Priority order follows Todoist semantics where 4 is highest urgency.
        """

        schedule = TasksSchedule(
            start_time=time(9, 0), end_time=time(18, 0), fixed_tasks=fixed_tasks
        )

        failed_to_schedule = []
        planned_tasks = deepcopy(flexible_tasks)
        planned_tasks.sort(key=lambda task: task.priority, reverse=True)

        for task in planned_tasks:
            try:
                schedule.schedule_task_to_first_available_slot_in_any_day(task)
            except ValueError:
                failed_to_schedule.append(task)
                continue
        
            print("Scheduled task", task.content, "to", schedule.days[0][-1].start)

        return PlanningResult(schedule=schedule, failed_to_schedule=failed_to_schedule)
