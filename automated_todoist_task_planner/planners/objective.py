from datetime import datetime, timedelta, time

import mlflow
from todoist_api_python.models import Task

from tests.config import LOG_TO_MLFLOW

from ..scheduled_task import ScheduledTask
from ..tasks_schedule import TasksSchedule
from ..todoist_helper import get_task_duration_minutes

PRIORITY_URGENCY_WEIGHT = 100
PRIORITY_BASE = 4
NO_DEADLINE_PRIORITY_BASE = 2
FAILED_TASK_PENALTY_MULTIPLIER = -10
DEADLINE_END_TIME = time(23, 59, 59)


def _priority_reward(task: Task) -> float:
    return float(PRIORITY_BASE**task.priority)


def _no_deadline_priority_reward(task: Task) -> float:
    return float(NO_DEADLINE_PRIORITY_BASE**task.priority)


def _deadline_timestamp(deadline_date) -> datetime:
    return datetime.combine(deadline_date, DEADLINE_END_TIME)


def compute_task_objective_contribution(
    scheduled_task: ScheduledTask,
    schedule: TasksSchedule,
    ignore_other_scheduled_tasks: bool = False,
) -> float:
    task = scheduled_task.task
    base_reward = _priority_reward(task)

    if task.deadline is None:
        return _no_deadline_priority_reward(task)

    if scheduled_task.end.date() > task.deadline.date:
        return FAILED_TASK_PENALTY_MULTIPLIER * base_reward

    deadline_dt = _deadline_timestamp(task.deadline.date)
    try:
        best_start = schedule.get_slot_per_days(
            task,
            ignore_scheduled_tasks=ignore_other_scheduled_tasks,
            ignore_task=task,
        )[0][1]
    except Exception:
        return FAILED_TASK_PENALTY_MULTIPLIER * base_reward

    best_end = best_start + timedelta(minutes=get_task_duration_minutes(task))
    if best_end > deadline_dt:
        return FAILED_TASK_PENALTY_MULTIPLIER * base_reward

    denominator = (deadline_dt - best_end).total_seconds()
    if denominator == 0:
        best_ratio = 1.0
    elif denominator < 0:
        return FAILED_TASK_PENALTY_MULTIPLIER * base_reward
    else:
        best_ratio = (deadline_dt - scheduled_task.end).total_seconds() / denominator

    return base_reward * (1 + best_ratio)


def objective(
    schedule: TasksSchedule,
    failed_to_schedule: list[Task],
    planning_to_date: datetime,
    iteration: int | None = None,
) -> float:
    objective_value = 0.0

    # Compute the objective value for all scheduled tasks.
    for scheduled_task in schedule.get_scheduled_tasks():
        objective_value += compute_task_objective_contribution(
            scheduled_task,
            schedule,
            ignore_other_scheduled_tasks=True,
        )

    # Apply penalty for tasks that failed to schedule.
    for task in failed_to_schedule:
        objective_value += FAILED_TASK_PENALTY_MULTIPLIER * _priority_reward(task)

    # Convert maximizing objective to minimizing
    obj = -objective_value

    if LOG_TO_MLFLOW and iteration is not None:
        mlflow.log_metric("objective", obj, step=iteration)

    return obj
