Project: Automated task scheduler as a Todoist extension.

Context:
- Triggered by Todoist webhooks when tasks are created/updated with duration.
- Maintains a global view of all tasks.
- Automatically schedules tasks based on priority, duration, and due date.
- Continuously re-evaluates schedule as tasks change (add/update/complete).
- Respects tasks with fixed schedule - labeled with “fixed” tag.
- Schedules tasks in user-defined “productivity time range”.

Framing:
- Treat as a dynamic scheduling/optimization problem, not a basic to-do list.
- Consider real-world constraints: shifting priorities, incremental updates, and scalability.
- Distinguish clearly between:
  - scheduling logic (what decisions are made)
  - optimization strategy (how decisions are derived)
  - system design (how it is implemented)

