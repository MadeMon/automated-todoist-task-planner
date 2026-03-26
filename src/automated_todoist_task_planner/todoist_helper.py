from datetime import datetime
from typing import cast
from todoist_api_python.models import Task


def is_task_fixed(task: Task) -> bool:
    """Determine if the task is fixed (has a specific due date and "fixed" label) or flexible."""
    return "fixed" in (task.labels or [])

def get_task_duration_minutes(task: Task) -> int:
    """Return the duration of the task in minutes, or None if no duration is set."""
    if task.duration is None:
        return 0

    amount = getattr(task.duration, "amount", None)
    unit = str(getattr(task.duration, "unit", "minute") or "minute").lower()
    
    if amount is None:
        return 0
    
    if unit in ["minute", "minutes"]:
        return amount
    elif unit in ["hour", "hours"]:
        return amount * 60
    else:
        raise ValueError(f"Unsupported duration unit '{unit}' for task '{task.content}'")

def get_task_due_date(task: Task) -> datetime | None:
    """Return the due date of the task as a datetime.date object, or None if no due date is set."""
    if task.due is None:
        return None
    
    try:
        return cast(datetime, task.due.date)
    except ValueError:
        raise ValueError(f"Invalid due date format '{task.due.date}' for task '{task.content}'")