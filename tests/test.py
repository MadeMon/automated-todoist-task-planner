from __future__ import annotations
import os
from pathlib import Path
import sys

from datetime import datetime, time, timedelta
import json
from typing import Callable

import mlflow
from todoist_api_python.models import Task




sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from automated_todoist_task_planner.planners import BasePlanner, HeuristicPlanner
from automated_todoist_task_planner.schedule_plotter import plot_schedule_to_file
from automated_todoist_task_planner.planners.alns_planners import get_random_dest_regret_to_repair, get_short_task_clusters_random_dest_regret_to_repair
from automated_todoist_task_planner.planners.base_planner import PlanningResult
from automated_todoist_task_planner.scheduled_task import ScheduledTask

from test_helpers import (
    assert_all_tasks_scheduled_or_failed,
    assert_no_overlapping_tasks,
    assert_no_tasks_missing,
    assert_task_properties_preserved,
    build_task_snapshot,
    compute_objective,
    print_search_statistics,
)

from test_cases import Tasks, json_to_tasks

SCHEDULE_PLOT_OUTPUT_DIR = Path("test_schedules")
SCHEDULE_PLOT_OUTPUT_DIR.mkdir(exist_ok=True)

SCHEDULE_JSON_OUTPUT_DIR = SCHEDULE_PLOT_OUTPUT_DIR

PLANNING_FROM_DATE = datetime(2024, 1, 1)
PLANNING_START_TIME = datetime.strptime("08:00", "%H:%M").time()
PLANNING_END_TIME = datetime.strptime("16:00", "%H:%M").time()
PLANNING_DAYS = 14  # Plan tasks due in next two weeks by default, but this can be customized via environment variables.

TASK_SEEDS_DIR = Path(os.path.dirname(__file__)) / ".." / "task_seeds"

DEFAULT_SAMPLE_TASK_LISTS_PATHS: list[Path] = [
    # TASK_SEEDS_DIR / "seed_deadlines_priority_fixed.json",
    # TASK_SEEDS_DIR / "seed_deadlines_priority.json",
    # TASK_SEEDS_DIR / "seed_deadlines_priority_fixed_gaps.json",
    # TASK_SEEDS_DIR / "seed_deadlines_priority_fixed_varied_gaps.json"
    # TASK_SEEDS_DIR / "seed_deadlines_priority_fixed_gaps_fract.json"
    TASK_SEEDS_DIR / "seed_deadlines_priority_fixed_gaps_fract_arbitrary.json"
]

DEFAULT_PLANNERS: list[Callable[[], BasePlanner]] = [
    # get_random_dest_regret_to_repair,
    # get_short_task_clusters_random_dest_regret_to_repair,
    lambda: HeuristicPlanner()
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
        / f"{planner.name}_{seed_name}_schedule_plot.png",
    )

    save_schedule_to_json(
        result,
        SCHEDULE_JSON_OUTPUT_DIR / f"{planner.name}_{seed_name}_schedule.json",
        planning_from_date,
        planning_to_date,
        start_time,
        end_time,
        plan_days,
        seed_name,
        planner.name,
    )

    snapshot = build_task_snapshot(
        [*sample_tasks.flexible_tasks, *sample_tasks.fixed_tasks]
    )

    try:
        assert_no_tasks_missing(result, snapshot)
        assert_all_tasks_scheduled_or_failed(result)
        assert_no_overlapping_tasks(result.schedule)
        assert_task_properties_preserved(result, snapshot)
        objective = compute_objective(result, planning_to_date)
        assert isinstance(objective, float)
        if result.search_statistics is not None:
            assert result.search_statistics.best_solution_iteration >= 0
    finally:
        print_search_statistics(result, "test_lns_planner_validates_schedule")


def run_test(planners: list[Callable[[], BasePlanner]], sample_task_lists_paths: list[Path]) -> None:
    planning_to_date = PLANNING_FROM_DATE + timedelta(days=PLANNING_DAYS)

    for path in sample_task_lists_paths:
        sample_tasks = json_to_tasks(path, PLANNING_FROM_DATE)
        mlflow.set_experiment(path.stem)

        with mlflow.start_run():
            for create_planner in planners:
                planner = create_planner()
                with mlflow.start_run(run_name=f"{planner.name}_{datetime.now().isoformat()}", nested=True):
                    test_planner(
                        planner,
                        sample_tasks,
                        PLANNING_FROM_DATE,
                        planning_to_date,
                        PLANNING_START_TIME,
                        PLANNING_END_TIME,
                        PLANNING_DAYS,
                        seed_name=path.stem,
                    )


def _task_to_json(task: Task) -> dict[str, object]:
    return {
        "content": task.content
    }


def _scheduled_task_to_json(scheduled: ScheduledTask) -> dict[str, object]:
    return {
        "start": scheduled.start.isoformat(),
        "end": scheduled.end.isoformat(),
        "task": _task_to_json(scheduled.task)
    }


def save_schedule_to_json(
    result: PlanningResult,
    output_path: Path,
    planning_from_date: datetime,
    planning_to_date: datetime,
    start_time: time,
    end_time: time,
    plan_days: int,
    seed_name: str,
    planner_name: str,
) -> None:
    schedule = result.schedule
    days_payload = []
    for day_index, day_tasks in enumerate(schedule.days):
        day_date = (schedule.start_date + timedelta(days=day_index)).isoformat()
        days_payload.append(
            {
                "day_index": day_index,
                "date": day_date,
                "tasks": [_scheduled_task_to_json(task) for task in day_tasks],
            }
        )

    payload = {
        "planner": planner_name,
        "seed": seed_name,
        "planning_from": planning_from_date.isoformat(),
        "planning_to": planning_to_date.isoformat(),
        "start_time": start_time.isoformat(),
        "end_time": end_time.isoformat(),
        "plan_days": plan_days,
        "schedule": {
            "start_date": schedule.start_date.isoformat(),
            "num_days": schedule.num_days,
            "total_minutes_per_day": schedule.total_minutes_per_day,
            "days": days_payload,
        },
        "failed_to_schedule": [
            _task_to_json(task) for task in result.failed_to_schedule
        ],
    }

    output_path.write_text(json.dumps(payload, indent=2))


if __name__ == "__main__":
    run_test(DEFAULT_PLANNERS, DEFAULT_SAMPLE_TASK_LISTS_PATHS)
