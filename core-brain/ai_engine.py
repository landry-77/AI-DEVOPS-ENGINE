import json
import requests

API_BASE = "https://openrouter.ai/api/v1"
API_KEY = ""
MODEL = "openai/gpt-4o-mini"


def configure(model: str, api_base: str = None, api_key: str = None, extra: dict = None):
    global API_BASE, API_KEY, MODEL
    MODEL = model.replace("openrouter/", "", 1) if model else MODEL
    API_BASE = api_base or API_BASE
    API_KEY = api_key or API_KEY


def generate_autonomous_patch(buggy_code: str, bug_description: str, language: str, target_file: str = "") -> dict:
    framework = "pytest" if language == "python" else "jest"
    ext = "py" if language == "python" else "js"
    module_name = target_file.replace(f".{ext}", "").replace("/", ".").replace("\\", ".") if target_file else "app_patch"
    system_prompt = f"""You are a Principal Software Engineer. You fix bugs autonomously.
You must analyze the provided code block and the bug description, then provide a fix.
You must also generate a complete, executable unit test suite to validate your patch.

Your response must contain ONLY a single JSON object with exactly three keys.
Do NOT include multiple versions, multiple files, or any extra content.

CRITICAL: The test suite MUST import from '{module_name}' (the module name derived from the target file).
CRITICAL: Return ONLY a raw JSON object. Do not wrap it in markdown blocks or code fences.
CRITICAL: "patched_code" must be a single string containing ONLY the full corrected file — nothing else, no duplicates.

Required schema:
{{"reasoning": "Brief explanation", "patched_code": "full corrected file content as a single string", "test_suite": "complete test file using {framework}"}}"""

    user_prompt = f"Target Language: {language}\nBug Description: {bug_description}\n\nBuggy Source Code File:\n{buggy_code}"

    try:
        response = requests.post(
            f"{API_BASE}/chat/completions",
            headers={
                "Authorization": f"Bearer {API_KEY}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://ai-devops-engine.local",
                "X-Title": "AI-DevOps-Engine",
            },
            json={
                "model": MODEL,
                "max_tokens": 8192,
                "temperature": 0.1,
                "data_collection": "deny",
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            },
            timeout=120,
        )
        response.raise_for_status()
        data = response.json()
        raw_content = data["choices"][0]["message"]["content"].strip()

        print(f"[AI_RAW] Full model response ({len(raw_content)} chars):")
        print(f"[AI_RAW] ---START---")
        print(raw_content)
        print(f"[AI_RAW] ---END---")

        if raw_content.startswith("```"):
            raw_content = raw_content.split("\n", 1)[1].rsplit("\n", 1)[0]

        result = json.loads(raw_content)

        for key in ("patched_code", "test_suite", "reasoning"):
            val = result.get(key)
            if isinstance(val, list):
                result[key] = val[-1]
            elif not isinstance(val, str):
                result[key] = str(val) if val else ""

        patched = result.get("patched_code", "")
        seen_funcs = set()
        deduped_lines = []
        current_func_lines = []
        in_func = False
        for line in patched.split("\n"):
            if line.startswith("def ") or line.startswith("class "):
                func_sig = line.strip()
                if func_sig in seen_funcs:
                    break
                seen_funcs.add(func_sig)
                if current_func_lines:
                    deduped_lines.extend(current_func_lines)
                current_func_lines = [line]
                in_func = True
            elif in_func:
                if line.strip() == "" and any(l.strip() for l in current_func_lines):
                    current_func_lines.append(line)
                elif line.strip() != "":
                    current_func_lines.append(line)
                else:
                    current_func_lines.append(line)
            else:
                deduped_lines.append(line)
        if current_func_lines:
            deduped_lines.extend(current_func_lines)
        result["patched_code"] = "\n".join(deduped_lines).strip()

        return result

    except Exception as e:
        print(f"Autonomous AI generation breakdown: {e}")
        return {
            "reasoning": "AI Generation failed.",
            "patched_code": "",
            "test_suite": "",
        }
