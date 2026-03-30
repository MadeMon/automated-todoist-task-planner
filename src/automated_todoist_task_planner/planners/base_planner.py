"""Planner abstraction used by concrete planning strategies."""

from __future__ import annotations

from abc import ABC, abstractmethod
from copy import copy
from dataclasses import dataclass
from datetime import datetime, time, timedelta

from todoist_api_python.models import Task

from ..tasks_schedule import TasksSchedule


@dataclass(frozen=True)
class PlanningResult:
    """Result of a planning attempt split by scheduling outcome."""

    schedule: "TasksSchedule"
    failed_to_schedule: list[Task]

    def __copy__(self):
        schedule = copy(self.schedule)
        failed_to_schedule = copy(self.failed_to_schedule)
        return PlanningResult(schedule=schedule, failed_to_schedule=failed_to_schedule)


class BasePlanner(ABC):
    """Abstract interface for components that schedule Todoist tasks."""

    def __init__(self):
        self._plan_tasks_from = datetime.now().date() + timedelta(
            days=1
        )  # Plan tasks starting from tomorrow to avoid scheduling tasks into already started day.

    def plan(
        self,
        planning_from_date: datetime,
        start_time: time,
        end_time: time,
        plan_days: int,
        flexible_tasks: list[Task],
        fixed_tasks: list[Task],
    ) -> PlanningResult:
        """Return scheduled tasks and tasks that could not be scheduled."""
        schedule = TasksSchedule(
            plan_tasks_from=planning_from_date,
            start_time=start_time,
            end_time=end_time,
            fixed_tasks=fixed_tasks,
            num_days=plan_days,
        )
        planning_to_date = planning_from_date + timedelta(days=plan_days)
        return self._plan(planning_from_date, planning_to_date, schedule, flexible_tasks, fixed_tasks)

    @abstractmethod
    def _plan(
        self,
        planning_from_date: datetime,
        planning_to_date: datetime,
        schedule: TasksSchedule,
        flexible_tasks: list[Task],
        fixed_tasks: list[Task],
    ) -> PlanningResult:
        """Schedule tasks and return the result."""
        pass
