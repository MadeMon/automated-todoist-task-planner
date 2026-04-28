from __future__ import annotations
import os
from pathlib import Path
import sys

from datetime import datetime, time, timedelta

import mlflow


sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from automated_todoist_task_planner.planners import BasePlanner, LNSPlanner
from automated_todoist_task_planner.schedule_plotter import plot_schedule_to_file

from test_helpers import (
    assert_no_overlapping_tasks,
    assert_task_properties_preserved,
    build_task_snapshot,
    compute_objective,
    print_search_statistics,
)

from test_cases import Tasks, json_to_tasks

SCHEDULE_PLOT_OUTPUT_DIR = Path("test_schedules")
SCHEDULE_PLOT_OUTPUT_DIR.mkdir(exist_ok=True)

PLANNING_FROM_DATE = datetime(2024, 1, 1)
PLANNING_START_TIME = datetime.strptime("08:00", "%H:%M").time()
PLANNING_END_TIME = datetime.strptime("16:00", "%H:%M").time()
PLANNING_DAYS = 14  # Plan tasks due in next two weeks by default, but this can be customized via environment variables.

TASK_SEEDS_DIR = Path(os.path.dirname(__file__)) / ".." / "task_seeds"

DEFAULT_SAMPLE_TASK_LISTS_PATHS: list[Path] = [
    TASK_SEEDS_DIR / "seed_deadlines_priority_fixed.json",
    TASK_SEEDS_DIR / "seed_deadlines_priority.json",
    TASK_SEEDS_DIR / "seed_deadlines_priority_fixed_gaps.json",
]

DEFAULT_PLANNERS: list[BasePlanner] = [
    LNSPlanner(),
]


def test_planner(
    planner: BasePlanner,
    sample_tasks: Tasks,
    planning_from_date: datetime,
    planning_to_date: datetime,
    start_time: time,
    end_time: time,
    plan_days: int,
    seed_name: str,
) -> None:
    result = planner.plan(
        planning_from_date=planning_from_date,
        start_time=start_time,
        end_time=end_time,
        plan_days=plan_days,
        flexible_tasks=sample_tasks.flexible_tasks,
        fixed_tasks=sample_tasks.fixed_tasks,
    )

    plot_schedule_to_file(
        result,
        SCHEDULE_PLOT_OUTPUT_DIR
        / f"{planner.__class__.__name__}_{seed_name}_schedule_plot.png",
    )

    snapshot = build_task_snapshot(
        [*sample_tasks.flexible_tasks, *sample_tasks.fixed_tasks]
    )

    try:
        assert_no_overlapping_tasks(result.schedule)
        assert_task_properties_preserved(result, snapshot)
        objective = compute_objective(result, planning_to_date)
        assert isinstance(objective, float)
        assert result.search_statistics is not None
        assert result.search_statistics.best_solution_iteration >= 0
    finally:
        print_search_statistics(result, "test_lns_planner_validates_schedule")


def run_test(planners: list[BasePlanner], sample_task_lists_paths: list[Path]) -> None:
    tasks_lists = []
    for path in sample_task_lists_paths:
        sample_tasks = json_to_tasks(path, PLANNING_FROM_DATE)
        tasks_lists.append(sample_tasks)

    planning_to_date = PLANNING_FROM_DATE + timedelta(days=PLANNING_DAYS)

    for task_list, path in zip(tasks_lists, sample_task_lists_paths):
        for planner in planners:
            test_planner(
                planner,
                task_list,
                PLANNING_FROM_DATE,
                planning_to_date,
                PLANNING_START_TIME,
                PLANNING_END_TIME,
                PLANNING_DAYS,
                seed_name=path.stem,
            )


if __name__ == "__main__":
    mlflow.set_experiment("tests")

    run_test(DEFAULT_PLANNERS, DEFAULT_SAMPLE_TASK_LISTS_PATHS)
