---
description: "Use when working on planner implementations, ALNS or bandit LNS search, mlflow experiment logging, or planner tests."
applyTo: "src/automated_todoist_task_planner/planners/**/*.py,tests/**/*.py"
---
# Planner Implementation Guidelines

- Treat planning as an optimization problem, not webhook plumbing. Keep scheduler decision logic inside planner code and keep Todoist webhook, client, and server layers thin.
- All new planners must extend `BasePlanner` and implement `_plan(...)` with clear input and output contracts.
- Separate the scheduling logic from the optimization strategy. Heuristics, ALNS, and bandit LNS should be swappable implementations, not mixed into the same control flow.
- Use `mlflow` for planner experiments and logging when comparing search strategies, objective values, or hyperparameters.
- Every planner implementation must be tested.
- Planner tests should pass in a list of Todoist tasks, run the planner, capture the returned `PlanningResult`, and evaluate it with the objective function defined in `lns_planner.py`.
- Prefer focused tests for objective behavior, deadline handling, fixed-task handling, and regressions in destroy/repair operators.
- Do not depend on live Todoist API calls in planner tests.
