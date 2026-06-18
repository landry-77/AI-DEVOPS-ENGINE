#!/bin/bash
set -e

REPO_BASE="https://raw.githubusercontent.com/your-org/ai-devops-engine/main"
SCRIPT_URL="$REPO_BASE/infra/patch-bot.sh"
INSTALL_PATH="/usr/local/bin/patch-bot"

echo "Installing AI Patch-Bot..."
curl -fsSL "$SCRIPT_URL" -o "$INSTALL_PATH" 2>/dev/null || {
    echo "Trying sudo..."
    curl -fsSL "$SCRIPT_URL" | sudo tee "$INSTALL_PATH" >/dev/null
}
chmod +x "$INSTALL_PATH"

echo "Done. Authenticate with GitHub App (no PAT required):"
echo "  patch-bot --auth"
echo ""
echo "Then run:"
echo "  patch-bot myfile.py \"describe the bug\""
