import os
import shutil
import docker
import requests
import psutil
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Literal

from ai_engine import generate_autonomous_patch, configure as configure_ai
from config import HOST, PORT, LITELLM_MODEL, OLLAMA_API_BASE, OPENROUTER_API_KEY
from git_handler import EnterpriseGitHandler
from scrubber import sanitize_source_code
from github_status import GitHubStatusCheckManager


def _build_pr_comment(reasoning: str, language: str, patched_code: str, target_file: str, test_logs: str) -> str:
    return f"""
## 🤖 AI DevOps — Fix Ready

> Stop reading 1,000-line deployment logs. Get the exact line of code to fix, right in your PR.

### What went wrong
{reasoning}

### The fix — `{target_file}`
```suggestion
{patched_code}
```

### Test results
```
{test_logs}
```

---

_🤖 AI-generated fix validated in isolated sandbox container. Review the suggested change above and commit if it looks good._
"""


def _build_failure_comment(reasoning: str, language: str, patched_code: str, target_file: str, test_logs: str) -> str:
    return f"""
## 🤖 AI DevOps — Fix Attempted (Tests Failed)

> Stop reading 1,000-line deployment logs. Get the exact line of code to fix, right in your PR.

### What went wrong
{reasoning}

### Proposed fix — `{target_file}` (may need adjustments)
```{language}
{patched_code}
```

### Test output
```
{test_logs}
```

---

_🤖 AI-generated fix failed sandbox validation. The code above is a starting point — manual adjustments may be needed._
"""


def record_billing_consumption(project_id: str, org_name: str):
    django_meter_url = "http://django-dashboard:8000/api/v1/meter-event/"
    headers = {
        "Authorization": "Bearer LocalSecretInternalTokenBetweenServices",
        "Content-Type": "application/json",
    }
    payload = {
        "project_id": project_id,
        "organization_name": org_name,
        "event_type": "successful_bug_remediation",
    }
    try:
        requests.post(django_meter_url, json=payload, headers=headers, timeout=5)
    except requests.exceptions.RequestException as e:
        print(f"[Meter] Failed to sync usage event: {e}")

app = FastAPI(title="Enterprise Autonomous DevOps Pipeline")


@app.on_event("startup")
def startup():
    configure_ai(
        model=LITELLM_MODEL,
        api_base=OLLAMA_API_BASE,
        api_key=OPENROUTER_API_KEY,
        extra={"data_collection": "deny"} if "openrouter" in LITELLM_MODEL else None,
    )

try:
    docker_client = docker.from_env()
except Exception as e:
    print(f"Docker subsystem link failure: {e}")
    docker_client = None

LANGUAGE_STRATEGIES = {
    "python": {
        "image": "local-pytest-sandbox",
        "app_file": "app_patch.py",
        "test_file": "test_patch.py",
        "command": "pytest /workspace/test_patch.py",
    },
    "javascript": {
        "image": "local-jest-sandbox",
        "app_file": "app_patch.js",
        "test_file": "test_patch.test.js",
        "command": "jest /workspace/test_patch.test.js --no-cache --runInBand",
    },
}


class IngestionPayload(BaseModel):
    project_id: str
    repository_full_name: str
    pull_request_number: int
    bug_description: str
    buggy_file_content: str
    target_language: Literal["python", "javascript"]
    installation_access_token: str = ""
    base_branch: str = "main"
    target_file_path: str = ""
    latest_commit_sha: str = ""


@app.post("/api/v1/verify-infrastructure")
async def process_autonomous_remediation(payload: IngestionPayload):
    if not docker_client:
        raise HTTPException(status_code=500, detail="Sandbox execution system offline.")

    clean_code, leaked_signatures = sanitize_source_code(payload.buggy_file_content)
    if leaked_signatures:
        print(f"Compliance Alert: Intercepted and scrubbed {leaked_signatures} out of payload.")

    payload.buggy_file_content = clean_code

    config = LANGUAGE_STRATEGIES[payload.target_language]
    sandbox_filename = os.path.basename(payload.target_file_path) if payload.target_file_path else config["app_file"]

    ai_solution = generate_autonomous_patch(
        buggy_code=payload.buggy_file_content,
        bug_description=payload.bug_description,
        language=payload.target_language,
        target_file=sandbox_filename,
    )

    if not ai_solution["patched_code"] or not ai_solution["test_suite"]:
        raise HTTPException(status_code=422, detail="AI failed to generate structural patches.")

    workspace_dir = f"/tmp/{payload.project_id}"
    os.makedirs(workspace_dir, exist_ok=True)

    try:
        app_path = os.path.join(workspace_dir, sandbox_filename)
        test_path = os.path.join(workspace_dir, config["test_file"])
        with open(app_path, "w") as f:
            f.write(ai_solution["patched_code"])
        with open(test_path, "w") as f:
            f.write(ai_solution["test_suite"])
        print(f"Sandbox files written: app={os.path.getsize(app_path)}B, test={os.path.getsize(test_path)}B")
    except IOError as e:
        if os.path.exists(workspace_dir):
            shutil.rmtree(workspace_dir)
        raise HTTPException(status_code=500, detail=f"Filesystem error: {e}")

    status_manager = None
    if payload.installation_access_token and payload.latest_commit_sha:
        status_manager = GitHubStatusCheckManager(
            repository_full_name=payload.repository_full_name,
            short_lived_access_token=payload.installation_access_token,
        )
        status_manager.update_commit_status(
            commit_sha=payload.latest_commit_sha,
            state="pending",
            target_url=f"https://mardi-cattle-charbroil.ngrok-free.dev/logs/{payload.project_id}",
            description="🔍 AI analyzing the issue — fix comment incoming...",
        )

    container = None
    try:
        container = docker_client.containers.run(
            image=config["image"],
            command="tail -f /dev/null",
            working_dir="/workspace",
            detach=True,
            stdout=True,
            stderr=True,
            mem_limit="512m",
            nano_cpus=2000000000,
        )

        import tarfile, io
        def put_file(container_obj, src_path, dest_dir):
            tar_stream = io.BytesIO()
            with tarfile.open(fileobj=tar_stream, mode='w') as tar:
                tar.add(src_path, arcname=os.path.basename(src_path))
            tar_stream.seek(0)
            container_obj.put_archive(dest_dir, tar_stream)

        put_file(container, app_path, "/workspace")
        put_file(container, test_path, "/workspace")

        exit_code, execution_logs = container.exec_run(
            config["command"],
            workdir="/workspace",
            stdout=True,
            stderr=True,
            demux=False,
        )
        execution_logs = (execution_logs or b"").decode("utf-8")
        exit_code = exit_code or 0
        container.stop()
        container.remove()

        if exit_code == 0:
            org_name = payload.repository_full_name.split("/")[0]
            record_billing_consumption(payload.project_id, org_name)

            handler = None
            if payload.installation_access_token:
                handler = EnterpriseGitHandler(
                    repo_full_name=payload.repository_full_name,
                    short_lived_token=payload.installation_access_token,
                )

            if payload.pull_request_number > 0:
                comment = _build_pr_comment(
                    reasoning=ai_solution["reasoning"],
                    language=payload.target_language,
                    patched_code=ai_solution["patched_code"],
                    target_file=payload.target_file_path or sandbox_filename,
                    test_logs=execution_logs,
                )
                comment_result = handler.post_pr_comment(payload.pull_request_number, comment) if handler else "No token provided — skipping comment."

                if status_manager:
                    status_manager.update_commit_status(
                        commit_sha=payload.latest_commit_sha,
                        state="success",
                        target_url=f"https://mardi-cattle-charbroil.ngrok-free.dev/logs/{payload.project_id}",
                        description="✅ Fix posted as PR comment — check the conversation tab.",
                    )

                return {
                    "status": "AUTONOMOUS_FIX_COMMENTED",
                    "message": "Fix posted as comment on the PR.",
                    "reasoning": ai_solution["reasoning"],
                    "comment_result": comment_result,
                    "logs": execution_logs,
                }
            else:
                pr_result = "No token provided — skipping PR creation."
                if handler:
                    pr_result = handler.execute_autonomous_pull_request(
                        base_branch=payload.base_branch,
                        target_file_path=payload.target_file_path or config["app_file"],
                        patched_code_content=ai_solution["patched_code"],
                        pr_title=ai_solution["reasoning"][:80],
                        verification_logs=execution_logs,
                    )

                if status_manager:
                    status_manager.update_commit_status(
                        commit_sha=payload.latest_commit_sha,
                        state="success",
                        target_url=f"https://mardi-cattle-charbroil.ngrok-free.dev/logs/{payload.project_id}",
                        description="✅ Fix PR created — review and merge.",
                    )

                return {
                    "status": "AUTONOMOUS_PR_TRIGGERED",
                    "message": "Bug fixed and verified successfully.",
                    "reasoning": ai_solution["reasoning"],
                    "pr_result": pr_result,
                    "logs": execution_logs,
                }
        else:
            if payload.pull_request_number > 0 and payload.installation_access_token:
                handler = EnterpriseGitHandler(
                    repo_full_name=payload.repository_full_name,
                    short_lived_token=payload.installation_access_token,
                )
                fail_comment = _build_failure_comment(
                    reasoning=ai_solution["reasoning"],
                    language=payload.target_language,
                    patched_code=ai_solution["patched_code"],
                    target_file=payload.target_file_path or sandbox_filename,
                    test_logs=execution_logs,
                )
                handler.post_pr_comment(payload.pull_request_number, fail_comment)

            if status_manager:
                status_manager.update_commit_status(
                    commit_sha=payload.latest_commit_sha,
                    state="failure",
                    target_url=f"https://mardi-cattle-charbroil.ngrok-free.dev/logs/{payload.project_id}",
                    description=f"❌ Sandbox tests failed (exit code {exit_code}) — comment posted on PR.",
                )

            return {
                "status": "SANDBOX_VALIDATION_FAILED",
                "message": "AI generated a fix but it failed safety validation tests.",
                "reasoning": ai_solution["reasoning"],
                "logs": execution_logs,
            }

    except Exception as exc:
        if container:
            container.remove()
        if payload.pull_request_number > 0 and payload.installation_access_token:
            try:
                handler = EnterpriseGitHandler(
                    repo_full_name=payload.repository_full_name,
                    short_lived_token=payload.installation_access_token,
                )
                error_comment = f"""
## 🤖 AI DevOps — Error

> Stop reading 1,000-line deployment logs. Get the exact line of code to fix, right in your PR.

### Runtime error
```
{str(exc)[:500]}
```

_🤖 The AI sandbox encountered an error while processing this PR._
"""
                handler.post_pr_comment(payload.pull_request_number, error_comment)
            except Exception:
                pass
        if status_manager:
            status_manager.update_commit_status(
                commit_sha=payload.latest_commit_sha,
                state="error",
                target_url=f"https://mardi-cattle-charbroil.ngrok-free.dev/logs/{payload.project_id}",
                description=f"⚠️ Sandbox error: {str(exc)[:120]}",
            )
        raise HTTPException(status_code=500, detail=str(exc))
    finally:
        if os.path.exists(workspace_dir):
            shutil.rmtree(workspace_dir)


@app.get("/health")
def health():
    return {
        "status": "healthy",
        "service": "core-brain",
        "docker_ready": docker_client is not None,
    }


@app.get("/api/v1/telemetry/server-health")
async def get_server_health_metrics():
    try:
        cpu_utilization = psutil.cpu_percent(interval=None)
        cpu_cores_logical = psutil.cpu_count(logical=True)

        hardware_temperatures = {}
        if hasattr(psutil, "sensors_temperatures"):
            temperatures = psutil.sensors_temperatures()
            if "coretemp" in temperatures:
                hardware_temperatures["cpu_current_celsius"] = temperatures["coretemp"][0].current
                hardware_temperatures["cpu_critical_ceiling"] = temperatures["coretemp"][0].critical
            else:
                hardware_temperatures["cpu_current_celsius"] = "N/A"

        virtual_mem = psutil.virtual_memory()

        active_sandboxes = 0
        if docker_client:
            running_containers = docker_client.containers.list(filters={"status": "running"})
            active_sandboxes = len([
                c for c in running_containers
                if any("local-pytest" in tag or "local-jest" in tag for tag in c.image.tags)
            ])

        return {
            "status": "HEALTHY",
            "host_hardware": {
                "cpu_load_percent": cpu_utilization,
                "logical_cores_count": cpu_cores_logical,
                "thermal_sensors": hardware_temperatures,
            },
            "memory_pools": {
                "total_ram_gb": round(virtual_mem.total / (1024**3), 2),
                "allocated_ram_gb": round(virtual_mem.used / (1024**3), 2),
                "available_ram_percent": round((virtual_mem.available / virtual_mem.total) * 100, 1),
            },
            "container_subsystem": {
                "active_isolated_sandboxes": active_sandboxes,
                "system_capacity_limit": 2,
            },
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to assemble hardware metrics: {str(e)}")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=HOST, port=PORT)
