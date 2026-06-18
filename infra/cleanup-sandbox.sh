#!/bin/bash

MAX_ALLOWED_AGE_SECONDS=60
WORKSPACE_BASE_DIR="/tmp"

COLOR_CYAN='\033[0;36m'
COLOR_GREEN='\033[0;32m'
COLOR_YELLOW='\033[0;33m'
COLOR_RED='\033[0;31m'
COLOR_RESET='\033[0m'

echo -e "${COLOR_CYAN}Initializing server-side sandbox resource scan...${COLOR_RESET}"

ACTIVE_SANDBOXES=$(docker ps --filter "ancestor=local-pytest-sandbox" --filter "ancestor=local-jest-sandbox" --format "{{.ID}}")

if [ -z "$ACTIVE_SANDBOXES" ]; then
    echo -e "${COLOR_GREEN}Clean Scan: No active or leaked sandbox containers detected.${COLOR_RESET}"
else
    CURRENT_TIME=$(date +%s)

    for CONTAINER_ID in $ACTIVE_SANDBOXES; do
        CREATED_AT_RAW=$(docker inspect --format='{{.State.StartedAt}}' "$CONTAINER_ID")

        if date -d "@0" >/dev/null 2>&1; then
            START_TIMESTAMP=$(date -d "$CREATED_AT_RAW" +%s)
        else
            START_TIMESTAMP=$(date -j -f "%Y-%m-%dT%H:%M:%S" "${CREATED_AT_RAW:0:19}" +%s 2>/dev/null || echo "${CREATED_AT_RAW:0:4}${CREATED_AT_RAW:5:2}${CREATED_AT_RAW:8:2}${CREATED_AT_RAW:11:2}${CREATED_AT_RAW:14:2}${CREATED_AT_RAW:17:2}")
        fi

        ELAPSED_AGE=$((CURRENT_TIME - START_TIMESTAMP))

        if [ "$ELAPSED_AGE" -gt "$MAX_ALLOWED_AGE_SECONDS" ]; then
            echo -e "${COLOR_RED}Leak Warning: Sandbox Container [ID: $CONTAINER_ID] is hanging active for $ELAPSED_AGE seconds!${COLOR_RESET}"

            CONTAINER_NAME=$(docker inspect --format='{{.Name}}' "$CONTAINER_ID" | sed 's/\///')

            echo -e "Forcing kernel termination sequence on container: $CONTAINER_ID..."
            docker kill "$CONTAINER_ID" > /dev/null 2>&1
            docker rm "$CONTAINER_ID" > /dev/null 2>&1

            PROJECT_WORKSPACE_PATH="${WORKSPACE_BASE_DIR}/sandbox_runtime_${CONTAINER_NAME}"
            if [ -d "$PROJECT_WORKSPACE_PATH" ]; then
                echo -e "Clearing leaky filesystem mount footprint: $PROJECT_WORKSPACE_PATH"
                rm -rf "$PROJECT_WORKSPACE_PATH"
            fi

            echo -e "${COLOR_GREEN}Resource successfully reclaimed from frozen run.${COLOR_RESET}"
        else
            echo -e "Sandbox Container [ID: $CONTAINER_ID] verified stable. (Age: ${ELAPSED_AGE}s / Limit: ${MAX_ALLOWED_AGE_SECONDS}s)"
        fi
    done
fi

echo -e "${COLOR_CYAN}System prune initiated to clean unlinked storage fragments...${COLOR_RESET}"
docker volume prune -f > /dev/null 2>&1

echo -e "${COLOR_GREEN}Infrastructure sweep process completed successfully.${COLOR_RESET}"
