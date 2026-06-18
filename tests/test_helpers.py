from __future__ import annotations

from datetime import datetime
from typing import Iterable

from automated_todoist_task_planner.planners import (
    PlanningResult,
    compute_task_objective_contribution,
)
from automated_todoist_task_planner.planners.objective import (
    FAILED_TASK_PENALTY_MULTIPLIER,
    PRIORITY_BASE,
)
from automated_todoist_task_planner.tasks_schedule import TasksSchedule


def build_task_snapshot(tasks: Iterable[object]) -> dict[int, dict[str, object]]:
    snapshot: dict[int, dict[str, object]] = {}
    for task in tasks:
        deadline_date = None
        if getattr(task, "deadline", None) is not None:
            deadline_date = task.deadline.date
        snapshot[task.id] = {
            "content": task.content,
            "description": task.description,
            "priority": task.priority,
            "deadline": deadline_date,
        }
    return snapshot


def assert_no_overlapping_tasks(schedule: TasksSchedule) -> None:
    for day_index, day_tasks in enumerate(schedule.days):
        sorted_tasks = sorted(day_tasks, key=lambda scheduled: scheduled.start)
        for left, right in zip(sorted_tasks, sorted_tasks[1:]):
            if left.end > right.start:
                raise AssertionError(
                    "Overlapping tasks detected in day "
                    f"{day_index}: {left.task.content} overlaps {right.task.content}"
                )


def assert_task_properties_preserved(
    result: PlanningResult, snapshot: dict[int, dict[str, object]]
) -> None:
    scheduled_tasks = result.schedule.get_scheduled_tasks(include_fixed=True)
    for scheduled in scheduled_tasks:
        _assert_task_matches_snapshot(scheduled.task, snapshot)

    for task in result.failed_to_schedule:
        _assert_task_matches_snapshot(task, snapshot)


def _assert_task_matches_snapshot(
    task: object, snapshot: dict[int, dict[str, object]]
) -> None:
    if task.id not in snapshot:
        raise AssertionError(f"Task {task.id} missing from snapshot")

    expected = snapshot[task.id]
    deadline_date = None
    if getattr(task, "deadline", None) is not None:
        deadline_date = task.deadline.date

    if task.content != expected["content"]:
        raise AssertionError("Task content changed")
    if task.description != expected["description"]:
        raise AssertionError("Task description changed")
    if task.priority != expected["priority"]:
        raise AssertionError("Task priority changed")
    if deadline_date != expected["deadline"]:
        raise AssertionError("Task deadline changed")

def assert_all_tasks_scheduled_or_failed(result: PlanningResult) -> None:
    scheduled_tasks = result.schedule.get_scheduled_tasks(include_fixed=True)
    scheduled_task_ids = {scheduled.task.id for scheduled in scheduled_tasks}
    failed_task_ids = {task.id for task in result.failed_to_schedule}

    if len(scheduled_task_ids.intersection(failed_task_ids)) > 0:
        raise AssertionError("Some tasks are both scheduled and failed to schedule")

def assert_no_tasks_missing(result: PlanningResult, snapshot: dict[int, dict[str, object]]) -> None:
    scheduled_tasks = result.schedule.get_scheduled_tasks(include_fixed=True)
    scheduled_task_ids = {scheduled.task.id for scheduled in scheduled_tasks}
    failed_task_ids = {task.id for task in result.failed_to_schedule}
    all_result_task_ids = scheduled_task_ids.union(failed_task_ids)
    snapshot_task_ids = set(snapshot.keys())

    if all_result_task_ids != snapshot_task_ids:
        missing_in_result = snapshot_task_ids - all_result_task_ids
        extra_in_result = all_result_task_ids - snapshot_task_ids
        raise AssertionError(
            f"Tasks missing from result: {missing_in_result}, "
            f"unexpected tasks in result: {extra_in_result}"
        )


# TODO ideally remove
def compute_objective(result: PlanningResult, planning_to_date: datetime) -> float:
    objective_value = 0.0

    schedule = result.schedule
    for scheduled_task in schedule.get_scheduled_tasks(include_fixed=True):
        objective_value += compute_task_objective_contribution(
            scheduled_task,
            schedule,
            ignore_other_scheduled_tasks=True,
        )

    for task in result.failed_to_schedule:
        objective_value += FAILED_TASK_PENALTY_MULTIPLIER * (
            PRIORITY_BASE**task.priority
        )

    return -objective_value


def print_search_statistics(result: PlanningResult, test_name: str) -> str:
    stats = result.search_statistics
    if stats is None:
        message = f"[STATS] {test_name} search_statistics=None"
        print(message)
        return message

    message = (
        f"[STATS] {test_name} best_iter={stats.best_solution_iteration} "
        f"final_obj={stats.final_solution_objective:.4f} "
        f"time_to_best={stats.time_to_best_solution_seconds:.4f}s "
        f"accepted={len(stats.accepted_solutions)}"
    )
    print(message)
    return message
