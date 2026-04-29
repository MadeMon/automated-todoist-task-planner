from datetime import datetime
import os
import time
from typing import cast

import mlflow
from todoist_api_python.models import Task
from alns import ALNS, State
from alns.accept import HillClimbing, SimulatedAnnealing, RecordToRecordTravel
from alns.select import RandomSelect
from alns.stop import MaxRuntime, NoImprovement, MaxIterations
import numpy.random as rnd


from automated_todoist_task_planner.planners.alns_components.problem_state import ProblemState
from automated_todoist_task_planner.planners.base_planner import BasePlanner, PlanningResult, PlanningSearchStatistics
from .alns_components.state_initializers import initial_state
from automated_todoist_task_planner.tasks_schedule import TasksSchedule


DEFAULT_STOP_NOT_IMPROVING_ITERATIONS = 50


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

    print(
        f"New best solution found at iteration {problem_state.iteration} with objective {problem_state.last_objective}."
    )
    if os.getenv("LOG_TO_MLFLOW") == "1" and problem_state.iteration > 0:
        mlflow.log_metrics(
            {"best_objective": problem_state.last_objective},
            step=problem_state.iteration,
        )



class BaseALNSPlanner(BasePlanner):
    """Planner that uses Large Neighborhood Search to schedule tasks."""

    def __init__(self,destroy_operators, repair_operators, create_initial_state_fn = initial_state,  select_fn = None, accept_fn = None, stop_fn = None, destroy_kwargs = None, repair_kwargs = None, name: str = ""):
        super().__init__(name)

        self.create_initial_state_fn = create_initial_state_fn
        self.destroy_operators = destroy_operators
        self.repair_operators = repair_operators
        self.select_fn = select_fn or RandomSelect(num_destroy=len(destroy_operators), num_repair=len(repair_operators))
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

        for i, destroy_op in enumerate(self.destroy_operators):
            alns.add_destroy_operator(destroy_op)
        
        for repair_op in self.repair_operators:
            alns.add_repair_operator(repair_op)

        if os.getenv("LOG_TO_MLFLOW") == "1":
            mlflow.log_params({
                "destroy_operators": [op.__name__ for op in self.destroy_operators],
                "repair_operators": [op.__name__ for op in self.repair_operators],
                "select_fn": self.select_fn.__class__.__name__,
                "accept_fn": self.accept_fn.__class__.__name__,
                "stop_fn": self.stop_fn.__class__.__name__,
                "destroy_kwargs": self.destroy_kwargs,
                "repair_kwargs": self.repair_kwargs,
            })

        result = alns.iterate(init_sol, self.select_fn, self.accept_fn, self.stop_fn, destroy_kwargs=self.destroy_kwargs, repair_kwargs=self.repair_kwargs)

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