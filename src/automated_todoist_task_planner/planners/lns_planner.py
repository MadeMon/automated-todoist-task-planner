from __future__ import annotations

from copy import copy
from datetime import datetime, timedelta
from math import e
from alns import State

from todoist_api_python.models import Task

from .heuristic_planner import MISSING_DEADLINE_URGENCY_PENALTY

from ..scheduled_task import ScheduledTask
from ..tasks_schedule import TasksSchedule
from ..todoist_helper import get_task_duration_minutes

from .base_planner import BasePlanner, PlanningResult
from alns import ALNS
from alns.accept import HillClimbing
from alns.select import RandomSelect
from alns.stop import MaxRuntime

import numpy.random as rnd


PRIORITY_URGENCY_WEIGHT = 100
TASK_WITHOUT_DEADLINE_URGENCY = 0

DESTROY_FRACTION = 0.2


def _compute_task_objective_contribution(scheduled_task: ScheduledTask) -> float:
    task = scheduled_task.task

    if task.deadline is not None:
        if task.deadline.date >= scheduled_task.end.date():
            best_case_days_to_deadline = (
                datetime.fromisoformat(task.deadline.date.isoformat())
                - scheduled_task.start
            ).total_seconds()
            scheduled_days_to_deadline = (
                datetime.fromisoformat(task.deadline.date.isoformat())
                - scheduled_task.end
            ).total_seconds()
            if best_case_days_to_deadline > 0:
                deadline_date_urgency = (
                    scheduled_days_to_deadline / best_case_days_to_deadline
                )
            else:
                deadline_date_urgency = 1
        else:
            deadline_date_urgency = -1
    else:
        deadline_date_urgency = TASK_WITHOUT_DEADLINE_URGENCY

    task_priority_urgency = task.priority * PRIORITY_URGENCY_WEIGHT
    return task_priority_urgency * deadline_date_urgency


class ProblemState(State):
    # TODO add attributes that encode a solution to the problem instance

    def __init__(
        self,
        planning_from_date: datetime,
        planning_to_date: datetime,
        result: PlanningResult,
    ):
        self.planning_from_date = planning_from_date
        self.planning_to_date = planning_to_date
        self.result = result

    def objective(self) -> float:
        objective_value = 0.0

        # Compute the objective value for all scheduled tasks.
        scheduled_tasks = self.result.schedule.get_scheduled_tasks()
        for scheduled_task in scheduled_tasks:
            objective_value += _compute_task_objective_contribution(scheduled_task)

        # Compute the objective value for all tasks that failed to schedule. We can penalize them by a fixed amount or based on their urgency.
        for task in self.result.failed_to_schedule:
            end = self.planning_to_date + timedelta(
                minutes=get_task_duration_minutes(task)
            )
            objective_value += _compute_task_objective_contribution(
                ScheduledTask(task=task, start=self.planning_to_date, end=end)
            )

        # TODO add penalty for gaps

        return -objective_value

    def get_context(self):
        # TODO implement a method returning a context vector. This is only
        #  needed for some context-aware bandit selectors from MABWiser;
        #  if you do not use those, this default is already sufficient!
        return None


def initial_state(
    planning_from_date: datetime,
    planning_to_date: datetime,
    flexible_tasks: list[Task],
    schedule: TasksSchedule,
) -> ProblemState:
    failed_to_schedule = []

    for task in flexible_tasks:
        try:
            schedule.schedule_task_to_first_available_slot_in_any_day(task)
        except ValueError:
            failed_to_schedule.append(task)
            continue

    init_result = PlanningResult(
        schedule=schedule, failed_to_schedule=failed_to_schedule
    )
    return ProblemState(
        planning_from_date=planning_from_date,
        planning_to_date=planning_to_date,
        result=init_result,
    )


def random_destroy(state: ProblemState, rng: rnd.Generator) -> ProblemState:
    destroyed_state = ProblemState(
        planning_from_date=state.planning_from_date,
        planning_to_date=state.planning_to_date,
        result=copy(state.result),
    )

    scheduled_tasks = destroyed_state.result.schedule.get_scheduled_tasks()

    destroy_indexes = rng.choice(
        len(scheduled_tasks),
        size=int(len(scheduled_tasks) * DESTROY_FRACTION),
        replace=False,
    )

    for i in sorted(destroy_indexes, reverse=True):
        destroyed_state.result.failed_to_schedule.append(scheduled_tasks[i].task)
        destroyed_state.result.schedule.delete_task(scheduled_tasks[i].task)

    return destroyed_state


def _compute_task_urgency(plan_tasks_from: datetime, task: Task) -> float:
    """Compute task urgency based on priority and due date.

    Priority order follows Todoist semantics where 4 is highest urgency.
    Due date urgency is computed as the number of days until due date, with overdue tasks having highest urgency.
    """
    if task.deadline is None:
        deadline_date_urgency = MISSING_DEADLINE_URGENCY_PENALTY
    else:
        deadline_date_urgency = (
            datetime.strptime(task.deadline.date.isoformat(), "%Y-%m-%d")
            - plan_tasks_from
        ).days
    # Weigh priority urgency more than deadline urgency to ensure that high priority tasks are scheduled first even if they are not due soon.
    return task.priority * PRIORITY_URGENCY_WEIGHT - deadline_date_urgency


def simple_heuristic_repair(state: ProblemState, rng: rnd.Generator) -> ProblemState:
    failed_tasks = state.result.failed_to_schedule
    failed_tasks.sort(
        key=lambda task: _compute_task_urgency(state.planning_from_date, task),
        reverse=True,
    )

    schedule = state.result.schedule

    for task in failed_tasks:
        try:
            schedule.schedule_task_to_first_available_slot_in_any_day(
                task, respect_deadline=True
            )
            failed_tasks.remove(task)
        except ValueError:
            continue

        print("Scheduled task", task.content, "to", schedule.days[0][-1].start)

    return state


def regret_repair(state: ProblemState, rng: rnd.Generator) -> ProblemState:
    previously_failed_tasks = state.result.failed_to_schedule
    schedule = state.result.schedule

    tasks_with_no_contribution = []

    while len(previously_failed_tasks) > 0:
        best_task: Task | None = None
        best_day: int | None = None
        best_slot: datetime | None = None
        best_regret = float("-inf")
        tasks_without_slots: list[Task] = []

        for task in previously_failed_tasks:
            available_slots = schedule.get_slot_per_every_day(
                task, return_available_days=2
            )
            if len(available_slots) == 0:
                tasks_without_slots.append(task)
                continue

            candidate_day, candidate_slot = available_slots[0]
            if len(available_slots) > 1:
                _, second_best_slot = available_slots[1]
            else:
                second_best_slot = state.planning_to_date

            best_scheduled_task = ScheduledTask(
                task=task,
                start=candidate_slot,
                end=candidate_slot + timedelta(minutes=get_task_duration_minutes(task)),
            )
            second_best_scheduled_task = ScheduledTask(
                task=task,
                start=second_best_slot,
                end=second_best_slot
                + timedelta(minutes=get_task_duration_minutes(task)),
            )
            regret = _compute_task_objective_contribution(
                best_scheduled_task
            ) - _compute_task_objective_contribution(second_best_scheduled_task)
            if regret > best_regret:
                best_task = task
                best_day = candidate_day
                best_slot = candidate_slot
                best_regret = regret

        for task in tasks_without_slots:
            previously_failed_tasks.remove(task)
            tasks_with_no_contribution.append(task)

        if best_task is None or best_day is None or best_slot is None:
            break

        print(
            f"Best task to schedule is '{best_task.content}' with regret {best_regret}."
        )
        scheduled_task = ScheduledTask(
            task=best_task,
            start=best_slot,
            end=best_slot + timedelta(minutes=get_task_duration_minutes(best_task)),
        )
        schedule.add_scheduled_task(best_day, scheduled_task)
        previously_failed_tasks.remove(best_task)

    failed_tasks = []
    for task in tasks_with_no_contribution:
        end = state.planning_to_date + timedelta(
            minutes=get_task_duration_minutes(task)
        )
        if end > task.deadline:
            failed_tasks.append(task)

    result = PlanningResult(schedule=schedule, failed_to_schedule=failed_tasks)
    state.result = result
    return state


class LNSPlanner(BasePlanner):
    """Planner that uses Large Neighborhood Search to schedule tasks."""

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

        # failed_to_schedule = []
        # planned_tasks = deepcopy(flexible_tasks)
        # planned_tasks.sort(key=lambda task: self._compute_task_urgency(task), reverse=True)

        # for task in planned_tasks:
        #     try:
        #         schedule.schedule_task_to_first_available_slot_balance_days(task)
        #     except ValueError:
        #         failed_to_schedule.append(task)
        #         continue

        #     print("Scheduled task", task.content, "to", schedule.days[0][-1].start)

        # return PlanningResult(schedule=schedule, failed_to_schedule=failed_to_schedule)

        # Create the initial solution
        init_sol = initial_state(
            planning_from_date, planning_to_date, flexible_tasks, schedule
        )
        print(f"Initial solution objective is {init_sol.objective()}.")

        # Create ALNS and add one or more destroy and repair operators
        alns = ALNS(rnd.default_rng(seed=42))
        alns.add_destroy_operator(random_destroy)
        # alns.add_repair_operator(simple_heuristic_repair)
        alns.add_repair_operator(regret_repair)

        # Configure ALNS
        select = RandomSelect(num_destroy=1, num_repair=1)  # see alns.select for others
        accept = HillClimbing()  # see alns.accept for others
        stop = MaxRuntime(60)  # 60 seconds; see alns.stop for others

        # Run the ALNS algorithm
        result = alns.iterate(init_sol, select, accept, stop)

        # Retrieve the final solution
        best = result.best_state
        print(f"Best heuristic solution objective is {best.objective()}.")

        return best.result
