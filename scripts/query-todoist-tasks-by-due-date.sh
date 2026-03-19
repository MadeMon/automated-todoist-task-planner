#!/bin/bash

# Todoist API configuration
# To use this script, export TODOIST_API_TOKEN in your environment:
#   export TODOIST_API_TOKEN="<your-todoist-token>"
#
# Example:
#   TODOIST_API_TOKEN="..." ./scripts/query-todoist-tasks-by-due-date.sh

TODOIST_API_TOKEN="${TODOIST_API_TOKEN:-}"
TODOIST_API_URL="https://api.todoist.com/api/v1/tasks/filter"

# Check if token is set
if [ -z "$TODOIST_API_TOKEN" ]; then
    echo "Error: TODOIST_API_TOKEN environment variable is not set"
    exit 1
fi

# Build filter for Todoist API
# Tasks due within next 14 days
FILTER="14 days"

# Call Todoist API
RESPONSE=$(curl -s -X GET "${TODOIST_API_URL}" \
    -H "Authorization: Bearer ${TODOIST_API_TOKEN}" \
    -G \
    --data-urlencode "query=${FILTER}")

# Check if request was successful
if [ $? -eq 0 ]; then
    echo "$RESPONSE" | jq '.'
else
    echo "Error: Failed to fetch tasks from Todoist API"
    exit 1
fi