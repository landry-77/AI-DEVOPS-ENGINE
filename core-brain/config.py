import os
from dotenv import load_dotenv

load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "openai").lower()

DOCKER_HOST = os.getenv("DOCKER_HOST", "tcp://localhost:2375")
SANDBOX_IMAGE = os.getenv("SANDBOX_IMAGE", "python:3.11-slim")

HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8010"))

SLACK_ANALYSIS_WEBHOOK_URL = os.getenv("SLACK_ANALYSIS_WEBHOOK_URL", "")

OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL") or os.getenv("LITELLM_MODEL", "openai/gpt-4o-mini")
OPENROUTER_BASE_URL = os.getenv("OPENROUTER_BASE_URL") or os.getenv("OLLAMA_API_BASE", "https://openrouter.ai/api/v1")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")

SYSTEM_PROMPT = """You are a Principal Software Engineer at a top-tier technology company.

Your task is to analyze a bug report and produce a minimal, correct code fix.

CRITICAL RULES:
1. Return ONLY a valid JSON object. No markdown, no code fences, no explanations.
2. The JSON must have this exact structure:
{
  "files": [
    {
      "path": "relative/file/path.ext",
      "content": "full corrected file content"
    }
  ],
  "summary": "one-line description of what was fixed"
}
3. The "content" field must contain only the raw source code — no surrounding backticks or markdown.
4. Fix only the minimal code needed. Do not rewrite unrelated parts.
5. If the bug cannot be reproduced from the description alone, make your best guess.
6. Do not include any text before or after the JSON object."""

PROMPT_TEMPLATE = """Bug Report:
Title: {title}
Description: {body}

Repository: {repository}
Labels: {labels}

Fix the bug described above. Return ONLY a JSON object with files to change and a summary."""
