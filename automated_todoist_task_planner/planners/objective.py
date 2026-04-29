from datetime import datetime, timedelta
import os

import mlflow
from todoist_api_python.models import Task

from ..scheduled_task import ScheduledTask
from ..todoist_helper import get_task_duration_minutes

TASK_WITHOUT_DEADLINE_URGENCY = 0
PRIORITY_URGENCY_WEIGHT = 100


def compute_task_objective_contribution(scheduled_task: ScheduledTask) -> float:
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


def objective(
    scheduled_tasks: list[ScheduledTask],
    failed_to_schedule: list[Task],
    planning_to_date: datetime,
    iteration: int,
) -> float:
    objective_value = 0.0

    # Compute the objective value for all scheduled tasks.
    for scheduled_task in scheduled_tasks:
        objective_value += compute_task_objective_contribution(scheduled_task)

    # Compute the objective value for all tasks that failed to schedule. We can penalize them by a fixed amount or based on their urgency.
    for task in failed_to_schedule:
        end = planning_to_date + timedelta(minutes=get_task_duration_minutes(task))
        objective_value += compute_task_objective_contribution(
            ScheduledTask(task=task, start=planning_to_date, end=end)
        )

    # Convert maximizing objective to minimizing
    obj = -objective_value

    if os.getenv("LOG_TO_MLFLOW") == "1":
        mlflow.log_metric("objective", obj, step=iteration)

    return obj
