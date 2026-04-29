from datetime import datetime, timedelta
from typing import cast

from alns import State
from todoist_api_python.models import Task

from automated_todoist_task_planner.planners.base_alns_planner import ProblemState
from automated_todoist_task_planner.planners.base_planner import PlanningResult

from numpy import random as rnd

from automated_todoist_task_planner.planners.heuristic_planner import MISSING_DEADLINE_URGENCY_PENALTY
from automated_todoist_task_planner.planners.objective import PRIORITY_URGENCY_WEIGHT, compute_task_objective_contribution
from automated_todoist_task_planner.scheduled_task import ScheduledTask
from automated_todoist_task_planner.todoist_helper import get_task_duration_minutes

def _compute_task_urgency(plan_tasks_from: datetime, task: Task) -> float:
    """Compute task urgency based on priority and due date.

    Priority order follows Todoist semantics where 4 is highest urgency.
    Due date urgency is computed as the number of days until due date, with overdue tasks having highest urgency.
    """
    if task.deadline is None:
        deadline_date_urgency = MISSING_DEADLINE_URGENCY_PENALTY
    else:
        deadline_date_urgency = (
            datetime.strptime(task.deadline.date.isoformat(), "%Y-%m-%d")
            - plan_tasks_from
        ).days
    # Weigh priority urgency more than deadline urgency to ensure that high priority tasks are scheduled first even if they are not due soon.
    return task.priority * PRIORITY_URGENCY_WEIGHT - deadline_date_urgency


def simple_heuristic_repair(state: State, rng: rnd.Generator, **kwargs) -> State:
    state = cast(ProblemState, state)
    failed_tasks = state.result.failed_to_schedule
    failed_tasks.sort(
        key=lambda task: _compute_task_urgency(state.planning_from_date, task),
        reverse=True,
    )

    schedule = state.result.schedule

    for task in failed_tasks:
        try:
            schedule.schedule_task_to_first_available_slot_in_any_day(
                task, respect_deadline=True
            )
            failed_tasks.remove(task)
        except ValueError:
            continue

    return state


def regret_repair(state: State, rng: rnd.Generator, **kwargs) -> State:
    state = cast(ProblemState, state)
    previously_failed_tasks = state.result.failed_to_schedule
    schedule = state.result.schedule

    tasks_with_no_contribution: list[Task] = []

    while len(previously_failed_tasks) > 0:
        best_task: Task | None = None
        best_day: int | None = None
        best_slot: datetime | None = None
        best_regret = float("-inf")
        tasks_without_slots: list[Task] = []

        for task in previously_failed_tasks:
            available_slots = schedule.get_slot_per_every_day(
                task, return_available_days=2, respect_deadline=True
            )
            if len(available_slots) == 0:
                tasks_without_slots.append(task)
                continue

            candidate_day, candidate_slot = available_slots[0]
            if len(available_slots) > 1:
                _, second_best_slot = available_slots[1]
            else:
                second_best_slot = state.planning_to_date

            best_scheduled_task = ScheduledTask(
                task=task,
                start=candidate_slot,
                end=candidate_slot + timedelta(minutes=get_task_duration_minutes(task)),
            )
            second_best_scheduled_task = ScheduledTask(
                task=task,
                start=second_best_slot,
                end=second_best_slot
                + timedelta(minutes=get_task_duration_minutes(task)),
            )
            regret = compute_task_objective_contribution(
                best_scheduled_task
            ) - compute_task_objective_contribution(second_best_scheduled_task)
            if regret > best_regret:
                best_task = task
                best_day = candidate_day
                best_slot = candidate_slot
                best_regret = regret

        for task in tasks_without_slots:
            previously_failed_tasks.remove(task)
            tasks_with_no_contribution.append(task)

        if best_task is None or best_day is None or best_slot is None:
            break

        scheduled_task = ScheduledTask(
            task=best_task,
            start=best_slot,
            end=best_slot + timedelta(minutes=get_task_duration_minutes(best_task)),
        )
        schedule.add_scheduled_task(best_day, scheduled_task)
        previously_failed_tasks.remove(best_task)

    failed_tasks = []
    for task in tasks_with_no_contribution:
        end = state.planning_to_date + timedelta(
            minutes=get_task_duration_minutes(task)
        )
        if task.deadline and end.date() > task.deadline.date:
            failed_tasks.append(task)

    result = PlanningResult(schedule=schedule, failed_to_schedule=failed_tasks)
    state.result = result
    return state