from __future__ import annotations

from copy import copy
from datetime import datetime, timedelta
import time
from typing import cast
from alns import State

from todoist_api_python.models import Task

from .objective import (
    PRIORITY_URGENCY_WEIGHT,
    compute_task_objective_contribution,
    objective,
)

from .heuristic_planner import MISSING_DEADLINE_URGENCY_PENALTY

from ..scheduled_task import ScheduledTask
from ..tasks_schedule import TasksSchedule
from ..todoist_helper import get_task_duration_minutes

from .base_planner import BasePlanner, PlanningResult, PlanningSearchStatistics
from alns import ALNS
from alns.accept import HillClimbing, SimulatedAnnealing, RecordToRecordTravel
from alns.select import RandomSelect
from alns.stop import MaxRuntime, NoImprovement

import numpy.random as rnd
import mlflow


DESTROY_FRACTION = 0.3

STOP_NOT_IMPROVING_ITERATIONS = 1000  # TEMP increase


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
    destroyed_state = copy(state)

    scheduled_tasks = destroyed_state.result.schedule.get_scheduled_tasks(
        include_fixed=False
    )

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


def _append_accepted_solution(
    accepted_solutions: list[tuple[int, float]], state: ProblemState
) -> None:
    if state.last_objective is None:
        return

    accepted_solutions.append((state.iteration, state.last_objective))


def _record_accepted_solution(
    accepted_solutions: list[tuple[int, float]],
    state: State,
    rng: rnd.Generator,
    **kwargs,
) -> None:
    _append_accepted_solution(accepted_solutions, cast(ProblemState, state))


def _record_best_solution(
    accepted_solutions: list[tuple[int, float]],
    best_solution_iteration: list[int],
    time_to_best_solution_seconds: list[float],
    search_start: float,
    state: State,
    rng: rnd.Generator,
    **kwargs,
) -> None:
    problem_state = cast(ProblemState, state)
    _append_accepted_solution(accepted_solutions, problem_state)
    best_solution_iteration[0] = problem_state.iteration
    time_to_best_solution_seconds[0] = time.perf_counter() - search_start

    try:
        print(
            f"New best solution found at iteration {problem_state.iteration} with objective {problem_state.last_objective}."
        )
        mlflow.log_metrics(
            {"best_objective": problem_state.last_objective},
            synchronous=False,
            step=problem_state.iteration,
        )
    except Exception:
        pass


def simple_heuristic_repair(state: State, rng: rnd.Generator, **kwargs) -> State:
    state = cast(ProblemState, state)
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

    return state


def regret_repair(state: State, rng: rnd.Generator, **kwargs) -> State:
    state = cast(ProblemState, state)
    previously_failed_tasks = state.result.failed_to_schedule
    schedule = state.result.schedule

    tasks_with_no_contribution: list[Task] = []

    while len(previously_failed_tasks) > 0:
        best_task: Task | None = None
        best_day: int | None = None
        best_slot: datetime | None = None
        best_regret = float("-inf")
        tasks_without_slots: list[Task] = []

        for task in previously_failed_tasks:
            available_slots = schedule.get_slot_per_every_day(
                task, return_available_days=2, respect_deadline=True
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
            regret = compute_task_objective_contribution(
                best_scheduled_task
            ) - compute_task_objective_contribution(second_best_scheduled_task)
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
        if task.deadline and end.date() > task.deadline.date:
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

        # Create the initial solution
        init_sol = initial_state(
            planning_from_date, planning_to_date, flexible_tasks, schedule
        )
        print(f"Initial solution objective is {init_sol.objective()}.")

        search_start = time.perf_counter()
        accepted_solutions: list[tuple[int, float]] = []
        best_solution_iteration = [0]
        time_to_best_solution_seconds = [0.0]

        # Create ALNS and add one or more destroy and repair operators
        alns = ALNS(rnd.default_rng(seed=42))
        alns.on_accept(
            lambda state, rng, **kwargs: _record_accepted_solution(
                accepted_solutions, state, rng, **kwargs
            )
        )
        alns.on_better(
            lambda state, rng, **kwargs: _record_accepted_solution(
                accepted_solutions, state, rng, **kwargs
            )
        )
        alns.on_best(
            lambda state, rng, **kwargs: _record_best_solution(
                accepted_solutions,
                best_solution_iteration,
                time_to_best_solution_seconds,
                search_start,
                state,
                rng,
                **kwargs,
            )
        )
        alns.add_destroy_operator(random_destroy)
        # alns.add_repair_operator(simple_heuristic_repair)
        alns.add_repair_operator(regret_repair)

        # Configure ALNS
        select = RandomSelect(num_destroy=1, num_repair=1)  # see alns.select for others
        # accept = SimulatedAnnealing(
        #         start_temperature=1_000,
        #         end_temperature=1,
        #         step=1 - 1e-3,
        #         method="exponential",
        #     )
        accept = RecordToRecordTravel(
            start_threshold=2000,
            end_threshold=500,
            step=10,
        )
        stop = NoImprovement(STOP_NOT_IMPROVING_ITERATIONS)

        try:
            mlflow.log_param("destroy_fraction", DESTROY_FRACTION)
            mlflow.log_param(
                "stop_not_improving_iterations", STOP_NOT_IMPROVING_ITERATIONS
            )
        except Exception:
            pass

        result = alns.iterate(init_sol, select, accept, stop)

        best_state = cast(ProblemState, result.best_state)

        # Log best solution objective when available
        try:
            best_tmp = result.best_state
            if best_tmp is not None:
                mlflow.log_metric("best_objective", best_tmp.objective())
        except Exception:
            pass

        accepted_solutions.sort(key=lambda item: item[0])
        final_objective = float(result.statistics.objectives[-1])

        planning_result = PlanningResult(
            schedule=best_state.result.schedule,
            failed_to_schedule=best_state.result.failed_to_schedule,
            search_statistics=PlanningSearchStatistics(
                best_solution_iteration=best_solution_iteration[0],
                accepted_solutions=accepted_solutions,
                final_solution_objective=final_objective,
                time_to_best_solution_seconds=time_to_best_solution_seconds[0],
            ),
        )

        print(f"Best heuristic solution objective is {best_state.last_objective}.")

        return planning_result
