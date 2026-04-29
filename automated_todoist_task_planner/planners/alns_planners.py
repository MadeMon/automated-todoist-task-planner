from .alns_components.destroy_operators import lowest_objective_contribution_destroy, random_destroy, short_task_clusters_destroy
from .alns_components.repair_operators import regret_repair
from .base_alns_planner import BaseALNSPlanner

from alns.select import RouletteWheel
from alns.stop import MaxIterations

DEFAULT_MAX_ITERATIONS= 100

def get_default_stop_fn():
    return MaxIterations(DEFAULT_MAX_ITERATIONS)


def get_random_dest_regret_to_repair():
    return BaseALNSPlanner(
        destroy_operators=[random_destroy],
        repair_operators=[regret_repair],
        destroy_kwargs={"all": {"destroy_fraction": 0.3}},
        stop_fn=get_default_stop_fn(),
        name="RandomDestRegretToRepair"
    )

destroys_2 = [short_task_clusters_destroy, random_destroy, lowest_objective_contribution_destroy]
repairs_2 = [regret_repair]
select_2 = RouletteWheel(scores=[33, 9, 3, 1], num_repair=len(repairs_2), num_destroy=len(destroys_2), decay=0.9)

def get_short_task_clusters_random_dest_regret_to_repair():
    return BaseALNSPlanner(
        destroy_operators=destroys_2,
        repair_operators=repairs_2,
        destroy_kwargs={"short_task_clusters": {"short_duration_threshold_factor": 0.5}, "all": {"destroy_fraction": 0.3}},
        select_fn=select_2,
        stop_fn=get_default_stop_fn(),
        name="ShortTaskClustersRandomDestRegretToRepair"
    )