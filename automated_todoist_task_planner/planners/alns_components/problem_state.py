from copy import copy
from datetime import datetime

from alns import State

from automated_todoist_task_planner.planners import objective
from automated_todoist_task_planner.planners.base_planner import PlanningResult


class ProblemState(State):
    def __init__(
        self,
        planning_from_date: datetime,
        planning_to_date: datetime,
        result: PlanningResult,
        iteration: int = 0,
        last_objective: float | None = None,
    ):
        self.planning_from_date = planning_from_date
        self.planning_to_date = planning_to_date
        self.result = result
        self.iteration = iteration
        self.last_objective = last_objective

    def objective(self) -> float:
        obj = objective(
            scheduled_tasks=self.result.schedule.get_scheduled_tasks(),
            failed_to_schedule=self.result.failed_to_schedule,
            planning_to_date=self.planning_to_date,
            iteration=self.iteration,
        )

        self.last_objective = obj
        self.iteration += 1

        return obj

    def __copy__(self):
        return ProblemState(
            planning_from_date=self.planning_from_date,
            planning_to_date=self.planning_to_date,
            result=copy(self.result),
            iteration=self.iteration,
            last_objective=self.last_objective,
        )

    def get_context(self):
        # TODO implement a method returning a context vector. This is only
        #  needed for some context-aware bandit selectors from MABWiser;
        #  if you do not use those, this default is already sufficient!
        return None