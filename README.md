# automated-todoist-task-planner

## Project structure

- `src/automated_todoist_task_planner/`: Main Python package.
- `tests/`: Test suite.
- `docs/`: Documentation and notes.
- `scripts/`: Utility scripts.
- `todoist_webhook_server.py`: Existing entry script (legacy/compat).

## Quick start

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m src.automated_todoist_task_planner.main \
  --api-token "$TODOIST_API_TOKEN" \
  --client-secret "$TODOIST_CLIENT_SECRET" \
--integration-user-id "$TODOIST_INTEGRATION_USER_ID"
```
