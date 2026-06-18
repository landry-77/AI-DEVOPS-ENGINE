#!/bin/bash
set -e

INSTALL_PATH="/usr/local/bin/patch-bot"
SESSION_FILE="$HOME/.config/patchbot/session"
CONFIG_SEARCH_PATHS=(".patchbot.env" "$HOME/.config/patchbot/env" "$HOME/.patchbot.env")
API_GATEWAY_URL="${PATCHBOT_API_URL:-http://localhost}"
COLOR_CYAN='\033[0;36m'
COLOR_GREEN='\033[0;32m'
COLOR_YELLOW='\033[0;33m'
COLOR_RED='\033[0;31m'
COLOR_RESET='\033[0m'

usage() {
    echo -e "${COLOR_YELLOW}Usage:${COLOR_RESET}"
    echo -e "  patch-bot <target_file> \"<bug_description>\""
    echo -e "  patch-bot --auth           Authenticate via GitHub App"
    echo -e "  patch-bot --set-token <t>  Store a CLI session token"
    echo -e "  patch-bot --install        Install globally to ${INSTALL_PATH}"
    echo -e ""
    echo -e "${COLOR_YELLOW}How authentication works:${COLOR_RESET}"
    echo -e "  1. Run ${COLOR_CYAN}patch-bot --auth${COLOR_RESET} to get started"
    echo -e "  2. Install the GitHub App on your organization (org admin approval)"
    echo -e "  3. Copy the session token from the success page"
    echo -e "  4. Run ${COLOR_CYAN}patch-bot --set-token <token>${COLOR_RESET}"
    echo -e ""
    echo -e "${COLOR_YELLOW}Environment:${COLOR_RESET}"
    echo -e "  PATCHBOT_API_URL   Server URL (default: http://localhost)"
    exit 0
}

if [ "$1" = "--help" ] || [ "$1" = "-h" ]; then usage; fi

if [ "$1" = "--install" ]; then
    SCRIPT_PATH="$(cd "$(dirname "$0")" && pwd)/$(basename "$0")"
    if [ ! -f "$SCRIPT_PATH" ]; then SCRIPT_PATH="$0"; fi
    cp "$SCRIPT_PATH" "$INSTALL_PATH" 2>/dev/null || sudo cp "$SCRIPT_PATH" "$INSTALL_PATH" 2>/dev/null
    chmod +x "$INSTALL_PATH"
    echo -e "${COLOR_GREEN}Installed to ${INSTALL_PATH}${COLOR_RESET}"
    echo -e "Run: ${COLOR_CYAN}patch-bot myfile.py \"describe the bug\"${COLOR_RESET}"
    exit 0
fi

if [ "$1" = "--auth" ]; then
    echo -e "${COLOR_CYAN}GitHub App Authentication${COLOR_RESET}"
    echo ""
    echo -e "To use patch-bot, your organization admin must install the GitHub App:"
    echo ""
    echo -e "  ${COLOR_GREEN}1. Visit:${COLOR_RESET}"
    echo -e "     ${COLOR_CYAN}${API_GATEWAY_URL}/dashboard/github/${COLOR_RESET}"
    echo -e "     Sign in and click 'Install GitHub App'"
    echo ""
    echo -e "  ${COLOR_GREEN}2. After installation:${COLOR_RESET}"
    echo -e "     A session token will be displayed on the success page"
    echo ""
    echo -e "  ${COLOR_GREEN}3. Save the token:${COLOR_RESET}"
    echo -e "     ${COLOR_CYAN}patch-bot --set-token YOUR_TOKEN${COLOR_RESET}"
    echo ""
    echo -e "${COLOR_YELLOW}Why this matters:${COLOR_RESET}"
    echo -e "  - No personal access tokens (PATs) required"
    echo -e "  - Organization admin controls installation and permissions"
    echo -e "  - Token is scoped to the GitHub App installation"
    echo -e "  - Revoke anytime by uninstalling the app from GitHub settings"
    exit 0
fi

if [ "$1" = "--set-token" ]; then
    if [ -z "$2" ]; then
        echo -e "${COLOR_RED}Usage: patch-bot --set-token <session_token>${COLOR_RESET}"
        exit 1
    fi
    mkdir -p "$(dirname "$SESSION_FILE")" 2>/dev/null
    echo "$2" > "$SESSION_FILE"
    chmod 600 "$SESSION_FILE" 2>/dev/null
    echo -e "${COLOR_GREEN}Session token saved to ${SESSION_FILE}${COLOR_RESET}"
    exit 0
fi

echo -e "${COLOR_CYAN}Initializing Autonomous AI Patch-Bot Engine client...${COLOR_RESET}"

# Resolve auth: session token > API key > error
AUTH_TOKEN=""
if [ -f "$SESSION_FILE" ]; then
    AUTH_TOKEN=$(cat "$SESSION_FILE" | tr -d '[:space:]')
fi

if [ -z "$AUTH_TOKEN" ]; then
    for cfg in "${CONFIG_SEARCH_PATHS[@]}"; do
        if [ -f "$cfg" ]; then source "$cfg"; break; fi
    done
    if [ -n "$PATCHBOT_API_KEY" ]; then
        AUTH_TOKEN="$PATCHBOT_API_KEY"
    fi
fi

if [ -z "$AUTH_TOKEN" ]; then
    echo -e "${COLOR_RED}Authentication required.${COLOR_RESET}"
    echo -e "Run ${COLOR_CYAN}patch-bot --auth${COLOR_RESET} to set up GitHub App authentication."
    echo -e "Or set PATCHBOT_API_KEY in .patchbot.env (legacy)."
    exit 1
fi

TARGET_FILE=$1
BUG_DESCRIPTION=$2

if [ -z "$TARGET_FILE" ] || [ -z "$BUG_DESCRIPTION" ]; then
    echo -e "${COLOR_YELLOW}Usage: patch-bot <target_file> \"<bug_description>\"${COLOR_RESET}"
    echo -e "       patch-bot --auth"
    echo -e "       patch-bot --set-token <token>"
    exit 1
fi

if [ ! -f "$TARGET_FILE" ]; then
    echo -e "${COLOR_RED}File not found: $TARGET_FILE${COLOR_RESET}"
    exit 1
fi

FILE_EXTENSION="${TARGET_FILE##*.}"
case "$FILE_EXTENSION" in
    py) TARGET_LANGUAGE="python" ;;
    js|jsx|ts|tsx) TARGET_LANGUAGE="javascript" ;;
    *)
        echo -e "${COLOR_RED}Unsupported file type: .${FILE_EXTENSION}. Only .py/.js/.jsx/.ts/.tsx${COLOR_RESET}"
        exit 1
        ;;
esac

echo -e "Targeting File: ${COLOR_YELLOW}$TARGET_FILE${COLOR_RESET} [Language: ${COLOR_GREEN}$TARGET_LANGUAGE${COLOR_RESET}]"
echo -e "Bug Matrix: \"$BUG_DESCRIPTION\""

BUGGY_FILE_CONTENT=$(cat "$TARGET_FILE")
PROJECT_ID="cli_run_$(date +%s)_$((RANDOM % 1000))"

echo -e "${COLOR_CYAN}Dispatching code to cloud parsing nodes...${COLOR_RESET}"

if command -v jq &>/dev/null; then
    PAYLOAD=$(jq -n --arg pid "$PROJECT_ID" --arg lang "$TARGET_LANGUAGE" \
        --arg desc "$BUG_DESCRIPTION" --arg content "$BUGGY_FILE_CONTENT" \
        '{project_id: $pid, target_language: $lang, bug_description: $desc, buggy_file_content: $content}')
elif command -v python3 &>/dev/null; then
    PAYLOAD=$(python3 -c "
import json,sys
d={'project_id':'$PROJECT_ID','target_language':'$TARGET_LANGUAGE',
   'bug_description':'''$BUG_DESCRIPTION''','buggy_file_content':'''$BUGGY_FILE_CONTENT'''}
print(json.dumps(d))
")
else
    echo -e "${COLOR_RED}Error: Requires jq or python3 for JSON encoding.${COLOR_RESET}"
    echo -e "Install jq: apt install jq  |  brew install jq  |  choco install jq"
    exit 1
fi

RESPONSE=$(curl -s -w "\n%{http_code}" -X POST "$API_GATEWAY_URL/api/v1/cli/trigger-fix" \
    -H "Authorization: Bearer ${AUTH_TOKEN}" \
    -H "Content-Type: application/json" \
    -d "$PAYLOAD")

HTTP_BODY=$(echo "$RESPONSE" | sed '$d')
HTTP_STATUS=$(echo "$RESPONSE" | tail -n1)

if [ "$HTTP_STATUS" -eq 200 ] || [ "$HTTP_STATUS" -eq 202 ]; then
    echo -e "${COLOR_GREEN}Success! Execution tasks assigned smoothly to backend processing pools.${COLOR_RESET}"
    echo "--------------------------------------------------------"
    echo "$HTTP_BODY" | sed 's/.*"message":"\([^"]*\)".*/\1/' 2>/dev/null || echo "$HTTP_BODY"
    echo "--------------------------------------------------------"
    echo -e "View live telemetry at: ${COLOR_CYAN}${API_GATEWAY_URL}/dashboard/${COLOR_RESET}"
    exit 0
else
    echo -e "${COLOR_RED}Pipeline Error (Status: $HTTP_STATUS)${COLOR_RESET}"
    echo "$HTTP_BODY" | sed 's/.*"error":"\([^"]*\)".*/\1/' 2>/dev/null || echo "$HTTP_BODY"
    exit 1
fi
