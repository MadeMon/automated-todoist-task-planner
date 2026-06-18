from automated_todoist_task_planner.planners.base_alns_planner import ProblemState
from copy import copy
from numpy import random as rnd

from automated_todoist_task_planner.todoist_helper import is_task_fixed
from automated_todoist_task_planner.planners.objective import (
    compute_task_objective_contribution,
)

def _get_task_duration(task):
    return (task.end - task.start).total_seconds()


def random_destroy(state: ProblemState, rng: rnd.Generator, **kwargs) -> ProblemState:
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

    return destroyed_state

def short_task_clusters_destroy(state: ProblemState, rng: rnd.Generator, **kwargs) -> ProblemState:
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
    
    return destroyed_state


def lowest_objective_contribution_destroy(
    state: ProblemState, rng: rnd.Generator, **kwargs
) -> ProblemState:
    destroyed_state = copy(state)

    scheduled_tasks = destroyed_state.result.schedule.get_scheduled_tasks(
        include_fixed=False
    )
    if not scheduled_tasks:
        return destroyed_state

    destroy_fraction = kwargs["destroy_kwargs"]["all"][ "destroy_fraction" ]
    destroy_count = int(len(scheduled_tasks) * destroy_fraction)
    if destroy_count <= 0:
        return destroyed_state

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

    return destroyed_state
