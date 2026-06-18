from datetime import datetime
import math
import time
from typing import cast

import mlflow
from todoist_api_python.models import Task
from alns import ALNS, State
from alns.accept import RecordToRecordTravel
from alns.select import RandomSelect
from alns.stop import NoImprovement
import numpy.random as rnd


from automated_todoist_task_planner.planners.alns_components.problem_state import (
    ProblemState,
)
from automated_todoist_task_planner.planners.base_planner import (
    BasePlanner,
    PlanningResult,
    PlanningSearchStatistics,
)
from tests.config import LOG_TO_MLFLOW
from .alns_components.state_initializers import initial_state
from automated_todoist_task_planner.tasks_schedule import TasksSchedule

DEFAULT_STOP_NOT_IMPROVING_ITERATIONS = 50
DEFAULT_DESTROY_FRACTION_MIN = 0.2
DEFAULT_DESTROY_FRACTION_MAX = 0.6
DEFAULT_DESTROY_FRACTION_LOGISTIC_K = 0.1


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

    if LOG_TO_MLFLOW and problem_state.iteration > 0:
        mlflow.log_metrics(
            {"best_objective": problem_state.last_objective},
            step=problem_state.iteration,
        )


def _sigmoid(value: float) -> float:
    return 1.0 / (1.0 + math.exp(-value))


def _normalized_logistic(
    progress: int,
    ramp_iterations: int,
    logistic_k: float,
) -> float:
    if ramp_iterations <= 0:
        return 0.0

    if logistic_k <= 0:
        return progress / float(ramp_iterations)

    midpoint = ramp_iterations / 2.0
    min_raw = _sigmoid(-logistic_k * midpoint)
    max_raw = _sigmoid(logistic_k * midpoint)
    denom = max_raw - min_raw
    if denom <= 0:
        return progress / float(ramp_iterations)

    raw = _sigmoid(logistic_k * (progress - midpoint))
    normalized = (raw - min_raw) / denom
    return max(0.0, min(1.0, normalized))


def _compute_destroy_fraction(
    iterations_since_last_improvement: int,
) -> float:
    min_fraction = DEFAULT_DESTROY_FRACTION_MIN
    max_fraction = DEFAULT_DESTROY_FRACTION_MAX
    ramp_iterations = DEFAULT_STOP_NOT_IMPROVING_ITERATIONS
    logistic_k = DEFAULT_DESTROY_FRACTION_LOGISTIC_K

    if ramp_iterations <= 0 or max_fraction <= min_fraction:
        return min_fraction

    progress = max(0, min(iterations_since_last_improvement, ramp_iterations))
    ratio = _normalized_logistic(progress, ramp_iterations, logistic_k)

    fraction = min_fraction + (max_fraction - min_fraction) * ratio
    return max(min_fraction, min(max_fraction, fraction))


class BaseALNSPlanner(BasePlanner):
    """Planner that uses Large Neighborhood Search to schedule tasks."""

    def __init__(
        self,
        destroy_operators,
        repair_operators,
        create_initial_state_fn=initial_state,
        select_fn=None,
        accept_fn=None,
        stop_fn=None,
        destroy_kwargs=None,
        repair_kwargs=None,
        name: str = "",
    ):
        super().__init__(name)

        self.create_initial_state_fn = create_initial_state_fn
        self.destroy_operators = destroy_operators
        self.repair_operators = repair_operators
        self.select_fn = select_fn or RandomSelect(
            num_destroy=len(destroy_operators), num_repair=len(repair_operators)
        )
        self.accept_fn = accept_fn or RecordToRecordTravel(
            start_threshold=2000,
            end_threshold=500,
            step=10,
        )
        self.stop_fn = stop_fn or NoImprovement(DEFAULT_STOP_NOT_IMPROVING_ITERATIONS)

        self.destroy_kwargs = destroy_kwargs or {}
        self.repair_kwargs = repair_kwargs or {}

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
        last_logged_destroy_fraction_iteration = [-1]

        def _set_destroy_fraction(value: float) -> None:
            all_kwargs = self.destroy_kwargs.setdefault("all", {})
            all_kwargs["destroy_fraction"] = value

        def _maybe_update_destroy_fraction(
            state: ProblemState,
            is_improvement: bool,
        ) -> None:
            iterations_since_last_improvement = (
                0 if is_improvement else state.iteration_since_last_improvement
            )
            fraction = _compute_destroy_fraction(
                iterations_since_last_improvement,
            )
            _set_destroy_fraction(fraction)

            if LOG_TO_MLFLOW and is_improvement:
                iteration = state.iteration
                if last_logged_destroy_fraction_iteration[0] != iteration:
                    mlflow.log_metrics({"destroy_fraction": fraction}, step=iteration)
                    last_logged_destroy_fraction_iteration[0] = iteration

        _set_destroy_fraction(_compute_destroy_fraction(0))

        def _increment_iterations(state):
            state.iteration += 1

        def _on_better(state, rng, **kwargs):
            _record_accepted_solution(accepted_solutions, state, rng, **kwargs)
            state.iteration_since_last_improvement = 0
            _maybe_update_destroy_fraction(cast(ProblemState, state), True)
            _increment_iterations(state)

        def _on_reject(state, rng, **kwargs):
            state.iteration_since_last_improvement += 1
            _maybe_update_destroy_fraction(cast(ProblemState, state), False)
            _increment_iterations(state)

        def _on_accept(state, rng, **kwargs):
            _record_accepted_solution(accepted_solutions, state, rng, **kwargs)
            state.iteration_since_last_improvement += 1
            _maybe_update_destroy_fraction(cast(ProblemState, state), False)
            _increment_iterations(state)

        def _on_best(state, rng, **kwargs):
            _record_best_solution(
                accepted_solutions,
                best_solution_iteration,
                time_to_best_solution_seconds,
                search_start,
                state,
                rng,
                **kwargs,
            )
            state.iteration_since_last_improvement = 0
            _maybe_update_destroy_fraction(cast(ProblemState, state), True)
            _increment_iterations(state)

        # Create ALNS and add one or more destroy and repair operators
        alns = ALNS(rnd.default_rng(seed=42))
        alns.on_reject(_on_reject)
        alns.on_accept(_on_accept)
        alns.on_better(_on_better)
        alns.on_best(_on_best)

        for i, destroy_op in enumerate(self.destroy_operators):
            alns.add_destroy_operator(destroy_op)

        for repair_op in self.repair_operators:
            alns.add_repair_operator(repair_op)

        if LOG_TO_MLFLOW:
            mlflow.log_params(
                {
                    "destroy_operators": [op.__name__ for op in self.destroy_operators],
                    "repair_operators": [op.__name__ for op in self.repair_operators],
                    "select_fn": self.select_fn.__class__.__name__,
                    "accept_fn": self.accept_fn.__class__.__name__,
                    "stop_fn": self.stop_fn.__class__.__name__,
                    "destroy_kwargs": self.destroy_kwargs,
                    "repair_kwargs": self.repair_kwargs,
                    "destroy_fraction_min": DEFAULT_DESTROY_FRACTION_MIN,
                    "destroy_fraction_max": DEFAULT_DESTROY_FRACTION_MAX,
                    "destroy_fraction_logistic_k": DEFAULT_DESTROY_FRACTION_LOGISTIC_K,
                }
            )

        result = alns.iterate(
            init_sol,
            op_select=self.select_fn,
            accept=self.accept_fn,
            stop=self.stop_fn,
            destroy_kwargs=self.destroy_kwargs,
            repair_kwargs=self.repair_kwargs,
        )

        best_state = cast(ProblemState, result.best_state)

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
