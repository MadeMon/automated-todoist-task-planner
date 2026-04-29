from datetime import datetime

from todoist_api_python.models import Task

from ..base_alns_planner import ProblemState
from ..base_planner import PlanningResult
from automated_todoist_task_planner.tasks_schedule import TasksSchedule


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