from __future__ import annotations

from copy import deepcopy
import datetime

from todoist_api_python.models import Task

from ..tasks_schedule import TasksSchedule

from .base_planner import BasePlanner, PlanningResult


PRIORITY_URGENCY_WEIGHT = 100
MISSING_DEADLINE_URGENCY_PENALTY = 120


class HeuristicPlanner(BasePlanner):
    """Planner that uses greedy heuristics to schedule tasks."""

    """Mock planner implementation used for local testing workflows."""

    def _compute_task_urgency(self, task: Task) -> float:
        """Compute task urgency based on priority and due date.

        Priority order follows Todoist semantics where 4 is highest urgency.
        Due date urgency is computed as the number of days until due date, with overdue tasks having highest urgency.
        """
        if task.deadline is None:
            deadline_date_urgency = MISSING_DEADLINE_URGENCY_PENALTY
        else:
            deadline_date_urgency = (
                datetime.datetime.strptime(
                    task.deadline.date.isoformat(), "%Y-%m-%d"
                ).date()
                - self._plan_tasks_from
            ).days
        # Weigh priority urgency more than deadline urgency to ensure that high priority tasks are scheduled first even if they are not due soon.
        return task.priority * PRIORITY_URGENCY_WEIGHT - deadline_date_urgency

    def _plan(
        self,
        schedule: TasksSchedule,
        flexible_tasks: list[Task],
        fixed_tasks: list[Task],
    ) -> PlanningResult:
        """Return tasks sorted by priority and scheduled to today.

        Priority order follows Todoist semantics where 4 is highest urgency.
        """

        failed_to_schedule = []
        planned_tasks = deepcopy(flexible_tasks)
        planned_tasks.sort(
            key=lambda task: self._compute_task_urgency(task), reverse=True
        )

        for task in planned_tasks:
            try:
                schedule.schedule_task_to_first_available_slot_balance_days(task)
            except ValueError:
                failed_to_schedule.append(task)
                continue

            print("Scheduled task", task.content, "to", schedule.days[0][-1].start)

        return PlanningResult(schedule=schedule, failed_to_schedule=failed_to_schedule)
