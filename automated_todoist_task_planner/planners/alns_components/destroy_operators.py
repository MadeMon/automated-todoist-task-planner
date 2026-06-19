from automated_todoist_task_planner.planners.base_alns_planner import ProblemState
from copy import copy
from datetime import datetime, timedelta
from numpy import random as rnd

from automated_todoist_task_planner.todoist_helper import is_task_fixed
from automated_todoist_task_planner.planners.objective import (
    compute_task_objective_contribution,
)

def _get_task_duration(task):
    return (task.end - task.start).total_seconds()


def _settle_schedule(schedule) -> None:
    """Pull flexible tasks forward within each day to close gaps."""
    for day_index, day_tasks in enumerate(schedule.days):
        if not day_tasks:
            continue

        day_date = schedule.start_date + timedelta(days=day_index)
        current_start = datetime.combine(day_date, schedule.start_time)
        sorted_tasks = sorted(day_tasks, key=lambda t: t.start)

        for scheduled_task in sorted_tasks:
            if not is_task_fixed(scheduled_task.task) and scheduled_task.start > current_start:
                duration = scheduled_task.end - scheduled_task.start
                scheduled_task.start = current_start
                scheduled_task.end = current_start + duration
            current_start = scheduled_task.end



def _finalize_destroy(state: ProblemState, kwargs) -> ProblemState:
    """Finalize destroy step: optionally settle schedule based on kwargs.

    Reads destroy_kwargs.all.settle_after_destroy from the ALNS kwargs dict.
    """
    settle_after_destroy = False
    try:
        settle_after_destroy = (
            kwargs.get("destroy_kwargs", {}).get("all", {}).get(
                "settle_after_destroy", False
            )
        )
    except Exception:
        settle_after_destroy = False

    if settle_after_destroy:
        _settle_schedule(state.result.schedule)

    return state


def random_destroy(
    state: ProblemState,
    rng: rnd.Generator,
    **kwargs,
) -> ProblemState:
    destroyed_state = copy(state)

    scheduled_tasks = destroyed_state.result.schedule.get_scheduled_tasks(
        include_fixed=False
    )

    destroy_indexes = rng.choice(
        len(scheduled_tasks),
        size=int(len(scheduled_tasks) * kwargs["destroy_kwargs"]["all"]["destroy_fraction"]),
        replace=False,
    )

    for i in sorted(destroy_indexes, reverse=True):
        destroyed_state.result.failed_to_schedule.append(scheduled_tasks[i].task)
        destroyed_state.result.schedule.delete_task(scheduled_tasks[i].task)

    return _finalize_destroy(destroyed_state, kwargs)


def random_duration_destroy(
    state: ProblemState,
    rng: rnd.Generator,
    **kwargs,
) -> ProblemState:
    destroyed_state = copy(state)

    scheduled_tasks = destroyed_state.result.schedule.get_scheduled_tasks(
        include_fixed=False
    )
    if not scheduled_tasks:
        return _finalize_destroy(destroyed_state, kwargs)

    destroy_fraction = kwargs["destroy_kwargs"]["all"]["destroy_fraction"]
    total_duration = sum(_get_task_duration(task) for task in scheduled_tasks)
    target_duration = total_duration * destroy_fraction
    if target_duration <= 0:
        return _finalize_destroy(destroyed_state, kwargs)

    destroyed_duration = 0.0
    for i in rng.permutation(len(scheduled_tasks)):
        task = scheduled_tasks[i]
        destroyed_state.result.failed_to_schedule.append(task.task)
        destroyed_state.result.schedule.delete_task(task.task)
        destroyed_duration += _get_task_duration(task)
        if destroyed_duration > target_duration:
            break

    return _finalize_destroy(destroyed_state, kwargs)

def short_task_clusters_destroy(
    state: ProblemState,
    rng: rnd.Generator,
    **kwargs,
) -> ProblemState:
    destroyed_state = copy(state)
    
    tasks_by_duration = sorted(
        state.result.schedule.get_scheduled_tasks(include_fixed=False),
        key=lambda t: _get_task_duration(t),
    )

    task_duration_median = tasks_by_duration[len(tasks_by_duration) // 2]
    short_duration_threshold = _get_task_duration(task_duration_median) * kwargs["destroy_kwargs"]["short_task_clusters"]["short_duration_threshold_factor"]

    tasks_to_destroy = []

    for tasks in state.result.schedule.days:
        sorted_tasks = sorted(tasks, key=lambda t: (t.start))
        cluster = []
        for task in sorted_tasks:
            if _get_task_duration(task) <= short_duration_threshold and not is_task_fixed(task.task):
                cluster.append(task)
            else:
                if len(cluster) >= 2:
                    tasks_to_destroy.extend(cluster)
                    # TODO consider also removing tasks if short and followed by short gap
                cluster = []
        if len(cluster) >= 2:
            tasks_to_destroy.extend(cluster)


    for task in tasks_to_destroy:
        destroyed_state.result.failed_to_schedule.append(task.task)
        destroyed_state.result.schedule.delete_task(task.task)
    
    return _finalize_destroy(destroyed_state, kwargs)


def lowest_objective_contribution_destroy(
    state: ProblemState,
    rng: rnd.Generator,
    **kwargs,
) -> ProblemState:
    destroyed_state = copy(state)

    scheduled_tasks = destroyed_state.result.schedule.get_scheduled_tasks(
        include_fixed=False
    )
    if not scheduled_tasks:
        return _finalize_destroy(destroyed_state, kwargs)

    destroy_fraction = kwargs["destroy_kwargs"]["all"][ "destroy_fraction" ]
    destroy_count = int(len(scheduled_tasks) * destroy_fraction)
    if destroy_count <= 0:
        return _finalize_destroy(destroyed_state, kwargs)

    tasks_by_contribution = sorted(
        scheduled_tasks,
        key=lambda scheduled_task: compute_task_objective_contribution(
            scheduled_task,
            destroyed_state.result.schedule,
            ignore_other_scheduled_tasks=False,
        ),
    )
    tasks_to_destroy = tasks_by_contribution[:destroy_count]

    for task in tasks_to_destroy:
        destroyed_state.result.failed_to_schedule.append(task.task)
        destroyed_state.result.schedule.delete_task(task.task)

    return _finalize_destroy(destroyed_state, kwargs)
