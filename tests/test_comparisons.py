from __future__ import annotations
import csv
import math
import os
from pathlib import Path
import sys

from datetime import datetime, time, timedelta
import json
import textwrap
from typing import Callable, Iterable

import matplotlib.pyplot as plt
import mlflow
from todoist_api_python.models import Task

from dotenv import load_dotenv

load_dotenv()




sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from automated_todoist_task_planner.planners import BasePlanner, objective
from automated_todoist_task_planner.planners.base_alns_planner import (
    BaseALNSPlanner,
    DEFAULT_DESTROY_FRACTION_MAX,
    DEFAULT_DESTROY_FRACTION_MIN,
    DEFAULT_STOP_NOT_IMPROVING_ITERATIONS,
    _compute_destroy_fraction,
)
from automated_todoist_task_planner.schedule_plotter import plot_schedule_to_file
from automated_todoist_task_planner.planners.alns_planners import get_default_stop_fn
from automated_todoist_task_planner.planners.base_planner import PlanningResult
from automated_todoist_task_planner.scheduled_task import ScheduledTask
from automated_todoist_task_planner.planners.alns_components.destroy_operators import (
    lowest_objective_contribution_destroy,
    random_destroy,
    random_duration_destroy,
    short_task_clusters_destroy,
)
from automated_todoist_task_planner.planners.alns_components.repair_operators import (
    regret_repair,
    simple_heuristic_repair,
)

from alns.select import RouletteWheel, RandomSelect

from test_helpers import (
    assert_all_tasks_scheduled_or_failed,
    assert_no_overlapping_tasks,
    assert_no_tasks_missing,
    assert_task_properties_preserved,
    build_task_snapshot,
    print_search_statistics,
)

from test_cases import Tasks, json_to_tasks

SCHEDULE_PLOT_OUTPUT_DIR = Path("test_schedules")
SCHEDULE_PLOT_OUTPUT_DIR.mkdir(exist_ok=True)

SCHEDULE_JSON_OUTPUT_DIR = SCHEDULE_PLOT_OUTPUT_DIR
SUMMARY_PLOT_OUTPUT_PATH = SCHEDULE_PLOT_OUTPUT_DIR / "comparisons_summary_bar.png"
CSV_OUTPUT_PATH = Path("test_comparisons.csv")

PLANNING_FROM_DATE = datetime(2024, 1, 1)
PLANNING_START_TIME = datetime.strptime("08:00", "%H:%M").time()
PLANNING_END_TIME = datetime.strptime("16:00", "%H:%M").time()
PLANNING_DAYS = 14  # Plan tasks due in next two weeks by default, but this can be customized via environment variables.

TASK_SEEDS_DIR = Path(os.path.dirname(__file__)) / ".." / "task_seeds"

DEFAULT_SAMPLE_TASK_LISTS_PATHS: list[Path] = [
    TASK_SEEDS_DIR / "seed_deadlines_priority_fixed_gaps_fract_arbitrary.json",
    TASK_SEEDS_DIR / "kinda-good1.json",
    TASK_SEEDS_DIR / "kinda-good2.json",
    TASK_SEEDS_DIR / "kinda-good3.json",
    TASK_SEEDS_DIR / "kinda-good4.json",
    TASK_SEEDS_DIR / "kinda-good5.json",
]

# Explicitly list operator combinations to test.
PLANNER_OPERATOR_COMBINATIONS: list[dict[str, list[Callable]]] = [
    # {
    #     "destroy": [lowest_objective_contribution_destroy],
    #     "repair": [simple_heuristic_repair],
    # },
    {
        "destroy": [lowest_objective_contribution_destroy],
        "repair": [regret_repair],
    },
    {
        "destroy": [lowest_objective_contribution_destroy, short_task_clusters_destroy],
        "repair": [regret_repair],
    },
    # {
    #     "destroy": [random_destroy],
    #     "repair": [regret_repair],
    # },
    {
        "destroy": [random_duration_destroy],
        "repair": [regret_repair],
    },
    {
        "destroy": [random_duration_destroy, lowest_objective_contribution_destroy],
        "repair": [regret_repair],
    },
    {
        "destroy": [random_duration_destroy, short_task_clusters_destroy],
        "repair": [regret_repair],
    },
    {
        "destroy": [random_duration_destroy, short_task_clusters_destroy, lowest_objective_contribution_destroy],
        "repair": [regret_repair],
    },
]


def _join_operator_names(operators: Iterable[Callable]) -> str:
    return "+".join(op.__name__ for op in operators)


def _compose_planner_name(destroys: Iterable[Callable], repairs: Iterable[Callable]) -> str:
    return f"{_join_operator_names(destroys)}__{_join_operator_names(repairs)}"


ROULETTE_WHEEL_SCORES = [33.0, 9.0, 3.0, 1.0]
BASELINE_PLANNER_NAME = "lowest_objective_contribution_destroy__regret_repair"


def _create_select_fn(num_destroy: int, num_repair: int) -> RouletteWheel:
    return RouletteWheel(
        scores=ROULETTE_WHEEL_SCORES,
        num_repair=num_repair,
        num_destroy=num_destroy,
        decay=0.9,
    )
    # return RandomSelect(num_destroy=num_destroy, num_repair=num_repair)


def _build_destroy_kwargs() -> dict[str, dict[str, object]]:
    return {
        "all": {
            "destroy_fraction": DEFAULT_DESTROY_FRACTION_MIN,
            "settle_after_destroy": True,
        },
        "short_task_clusters": {
            "short_duration_threshold_factor": 0.5,
        },
    }


def build_planner_factories() -> tuple[list[Callable[[], BasePlanner]], dict[str, dict[str, str]]]:
    planner_factories: list[Callable[[], BasePlanner]] = []
    planner_metadata: dict[str, dict[str, str]] = {}

    for combo in PLANNER_OPERATOR_COMBINATIONS:
        destroy_ops = combo["destroy"]
        repair_ops = combo["repair"]
        name = _compose_planner_name(destroy_ops, repair_ops)
        destroy_names = _join_operator_names(destroy_ops)
        repair_names = _join_operator_names(repair_ops)

        def _factory(
            destroy_ops=tuple(destroy_ops),
            repair_ops=tuple(repair_ops),
            planner_name=name,
        ) -> BasePlanner:
            return BaseALNSPlanner(
                destroy_operators=list(destroy_ops),
                repair_operators=list(repair_ops),
                destroy_kwargs=_build_destroy_kwargs(),
                select_fn=_create_select_fn(len(destroy_ops), len(repair_ops)),
                stop_fn=get_default_stop_fn(),
                name=planner_name,
            )

        planner_factories.append(_factory)
        planner_metadata[name] = {
            "destroy_operators": destroy_names,
            "repair_operators": repair_names,
        }

    return planner_factories, planner_metadata


def test_destroy_fraction_schedule_defaults() -> None:
    ramp_iterations = DEFAULT_STOP_NOT_IMPROVING_ITERATIONS
    min_fraction = DEFAULT_DESTROY_FRACTION_MIN
    max_fraction = DEFAULT_DESTROY_FRACTION_MAX

    start_fraction = _compute_destroy_fraction(0)
    mid_fraction = _compute_destroy_fraction(ramp_iterations // 2)
    end_fraction = _compute_destroy_fraction(ramp_iterations)
    beyond_fraction = _compute_destroy_fraction(ramp_iterations * 2)

    assert math.isclose(start_fraction, min_fraction, rel_tol=1e-6, abs_tol=1e-6)
    assert mid_fraction > start_fraction
    assert math.isclose(end_fraction, max_fraction, rel_tol=1e-6, abs_tol=1e-6)
    assert math.isclose(beyond_fraction, max_fraction, rel_tol=1e-6, abs_tol=1e-6)


def test_planner(
    planner: BasePlanner,
    sample_tasks: Tasks,
    planning_from_date: datetime,
    planning_to_date: datetime,
    start_time: time,
    end_time: time,
    plan_days: int,
    seed_name: str,
) -> float:
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
        # assert_no_tasks_missing(result, snapshot)
        assert_all_tasks_scheduled_or_failed(result)
        assert_no_overlapping_tasks(result.schedule)
        assert_task_properties_preserved(result, snapshot)
        # objective = compute_objective(result, planning_to_date)
        objective_val = objective(
            schedule=result.schedule,
            failed_to_schedule=result.failed_to_schedule,
            planning_to_date=planning_to_date,
        )

        assert isinstance(objective_val, float)
        if result.search_statistics is not None:
            assert result.search_statistics.best_solution_iteration >= 0

        from config import LOG_TO_MLFLOW
        if LOG_TO_MLFLOW:
            mlflow.log_metric("planner_objective", objective_val)
    finally:
        print_search_statistics(result, "test_lns_planner_validates_schedule")

    return objective_val


def _percent_improvement_vs_baseline(value: float, baseline: float) -> float:
    if math.isclose(baseline, 0.0, abs_tol=1e-9):
        return 0.0
    return (baseline - value) / abs(baseline) * 100.0


def _build_summary_rows(
    results: dict[str, dict[str, float]],
    planner_metadata: dict[str, dict[str, str]],
    seed_names: list[str],
) -> list[dict[str, object]]:
    baseline_results = results.get(BASELINE_PLANNER_NAME)
    if not baseline_results:
        raise ValueError(
            f"Baseline planner '{BASELINE_PLANNER_NAME}' missing from results."
        )

    missing_seeds = [
        seed_name for seed_name in seed_names if seed_name not in baseline_results
    ]
    if missing_seeds:
        missing = ", ".join(missing_seeds)
        raise ValueError(
            f"Baseline planner '{BASELINE_PLANNER_NAME}' missing results for seeds: {missing}"
        )

    summary_rows: list[dict[str, object]] = []
    for combo_name, combo_results in results.items():
        improvements: list[float] = []
        for seed_name in seed_names:
            if seed_name not in combo_results:
                continue
            baseline = baseline_results[seed_name]
            improvements.append(
                _percent_improvement_vs_baseline(combo_results[seed_name], baseline)
            )

        avg_improvement = sum(improvements) / len(improvements) if improvements else 0.0
        summary_rows.append(
            {
                "name": combo_name,
                "destroy_operators": planner_metadata[combo_name]["destroy_operators"],
                "repair_operators": planner_metadata[combo_name]["repair_operators"],
                "avg_percent_improvement_vs_baseline": avg_improvement,
            }
        )

    summary_rows.sort(
        key=lambda row: row["avg_percent_improvement_vs_baseline"], reverse=True
    )
    return summary_rows


def _print_summary_table(rows: list[dict[str, object]]) -> None:
    print("\nSummary: avg percent improvement vs baseline (positive is better)")
    print(
        "name\tdestroy_operators\trepair_operators\tavg_percent_improvement_vs_baseline"
    )
    for row in rows:
        avg_improvement = row["avg_percent_improvement_vs_baseline"]
        print(
            f"{row['name']}\t{row['destroy_operators']}\t"
            f"{row['repair_operators']}\t{avg_improvement:.2f}"
        )


def _write_summary_csv(rows: list[dict[str, object]], output_path: Path) -> None:
    with output_path.open("w", newline="") as file_handle:
        writer = csv.DictWriter(
            file_handle,
            fieldnames=[
                "name",
                "destroy_operators",
                "repair_operators",
                "avg_percent_improvement_vs_baseline",
            ],
        )
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _plot_summary_bar_chart(rows: list[dict[str, object]], output_path: Path) -> Path:
    if not rows:
        return output_path

    names = [str(row["name"]).replace("_", " ") for row in rows]
    values = [float(row["avg_percent_improvement_vs_baseline"]) for row in rows]
    wrap_width = 60
    wrapped_names = [textwrap.fill(name, width=wrap_width) for name in names]

    fig, ax = plt.subplots(figsize=(16.0, 7.0))

    bar_colors = ["#4c9f70" if value >= 0 else "#d95c5c" for value in values]
    ax.barh(range(len(values)), values, color=bar_colors)
    ax.axvline(0.0, color="black", linewidth=0.8)

    ax.set_yticks(range(len(names)))
    ax.set_yticklabels(wrapped_names, fontsize=18)
    ax.set_xlabel("Avg percent improvement vs baseline", fontsize=18)
    ax.grid(axis="x", linestyle="--", alpha=0.3)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(output_path)
    plt.close(fig)
    return output_path


def _log_summary_to_mlflow(rows: list[dict[str, object]]) -> None:
    from config import LOG_TO_MLFLOW
    if not LOG_TO_MLFLOW:
        return

    mlflow.set_experiment("alns_comparisons_summary")
    for row in rows:
        mlflow.start_run(run_name=row["name"])
        mlflow.log_params(
            {
                "destroy_operators": row["destroy_operators"],
                "repair_operators": row["repair_operators"],
            }
        )
        mlflow.log_metric(
            "avg_percent_improvement_vs_baseline",
            float(row["avg_percent_improvement_vs_baseline"]),
        )
        mlflow.end_run()


def run_test(
    planners: list[Callable[[], BasePlanner]],
    planner_metadata: dict[str, dict[str, str]],
    sample_task_lists_paths: list[Path],
) -> None:
    from config import LOG_TO_MLFLOW
    print("MLFLOW logging enabled:", LOG_TO_MLFLOW)

    planning_to_date = PLANNING_FROM_DATE + timedelta(days=PLANNING_DAYS)
    seed_names = [path.stem for path in sample_task_lists_paths]
    results: dict[str, dict[str, float]] = {name: {} for name in planner_metadata}

    for path in sample_task_lists_paths:
        seed_name = path.stem
        sample_tasks = json_to_tasks(path, PLANNING_FROM_DATE)
        if LOG_TO_MLFLOW:
            mlflow.set_experiment(seed_name)
            mlflow.start_run()
        for create_planner in planners:
            planner = create_planner()
            if LOG_TO_MLFLOW:
                mlflow.start_run(run_name=f"{planner.name}", nested=True)
            objective_val = test_planner(
                planner,
                sample_tasks,
                PLANNING_FROM_DATE,
                planning_to_date,
                PLANNING_START_TIME,
                PLANNING_END_TIME,
                PLANNING_DAYS,
                seed_name=seed_name,
            )
            results[planner.name][seed_name] = objective_val
            if LOG_TO_MLFLOW:
                mlflow.end_run()

        if LOG_TO_MLFLOW:
            mlflow.end_run()

    summary_rows = _build_summary_rows(results, planner_metadata, seed_names)
    _print_summary_table(summary_rows)
    _write_summary_csv(summary_rows, CSV_OUTPUT_PATH)
    _plot_summary_bar_chart(summary_rows, SUMMARY_PLOT_OUTPUT_PATH)
    _log_summary_to_mlflow(summary_rows)


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
    test_destroy_fraction_schedule_defaults()
    planner_factories, planner_metadata = build_planner_factories()
    run_test(planner_factories, planner_metadata, DEFAULT_SAMPLE_TASK_LISTS_PATHS)
