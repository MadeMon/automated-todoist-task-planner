"""Planner abstraction used by concrete planning strategies."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING

from todoist_api_python.models import Task

if TYPE_CHECKING:
    from ..tasks_schedule import TasksSchedule


@dataclass(frozen=True)
class PlanningResult:
    """Result of a planning attempt split by scheduling outcome."""

    schedule: "TasksSchedule"
    failed_to_schedule: list[Task]


class BasePlanner(ABC):
    """Abstract interface for components that schedule Todoist tasks."""

    def plan(
        self, flexible_tasks: list[Task], fixed_tasks: list[Task]
    ) -> PlanningResult:
        """Return scheduled tasks and tasks that could not be scheduled."""
        return self._plan(flexible_tasks, fixed_tasks)

    @abstractmethod
    def _plan(
        self, flexible_tasks: list[Task], fixed_tasks: list[Task]
    ) -> PlanningResult:
        """Schedule tasks and return the result."""
        pass
