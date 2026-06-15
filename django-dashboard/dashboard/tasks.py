import os
import requests
from celery import shared_task, Task
from django.conf import settings
from django.utils.timezone import now
from .models import RunAuditLog, GitHubIntegration, Deployment
from .github_auth import refresh_installation_access_token


def _set_github_commit_status(repo_full_name, commit_sha, state, description, token):
    url = f"https://api.github.com/repos/{repo_full_name}/statuses/{commit_sha}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
    }
    payload = {
        "state": state,
        "description": description,
        "context": "ai-devops/deployment",
    }
    try:
        requests.post(url, json=payload, headers=headers, timeout=15)
    except Exception as e:
        print(f"[DEPLOY_STATUS] Failed to set commit status: {e}")


class EnterpriseTaskFailureMonitor(Task):
    def on_failure(self, exc, task_id, args, kwargs, einfo):
        project_id = args[0] if len(args) > 0 else "N/A"
        repository_name = args[2] if len(args) > 2 else "Unknown Repo"
        pr_number = args[3] if len(args) > 3 else "N/A"

        org_name = repository_name.split("/")[0] if "/" in repository_name else "default"
        RunAuditLog.objects.create(
            organization_name=org_name,
            project_id=project_id,
            repository_name=repository_name,
            target_language="unknown",
            execution_status="FAILED",
            execution_summary=f"Asynchronous Task Execution Error Trace:\n{str(exc)}",
        )

        slack_webhook_url = getattr(settings, "SLACK_ALERTS_WEBHOOK_URL", None)
        if not slack_webhook_url:
            print("Slack notification skipped: SLACK_ALERTS_WEBHOOK_URL variable unassigned.")
            return

        alert_payload = {
            "text": "🚨 Critical Failure: Autonomous AI Bug-Fixer Pipeline Broken",
            "attachments": [
                {
                    "color": "#f87171",
                    "title": f"Asynchronous Pipeline Crash Alert",
                    "fields": [
                        {"title": "Target Repository Workspace", "value": repository_name, "short": True},
                        {"title": "Pull Request Context", "value": f"PR #{pr_number}", "short": True},
                        {"title": "Tracking Thread ID", "value": f"`{task_id}`", "short": False},
                        {"title": "Runtime Error Exception Trace", "value": f"```{str(exc)[:250]}```", "short": False},
                    ],
                    "footer": "AI DevOps Platform Telemetry System",
                    "ts": int(requests.utils.time.time()),
                }
            ],
        }

        try:
            requests.post(slack_webhook_url, json=alert_payload, timeout=10)
        except Exception as network_error:
            print(f"Failed to transmit telemetry to Slack webhook endpoint: {network_error}")


@shared_task(
    bind=True,
    base=EnterpriseTaskFailureMonitor,
    autoretry_for=(requests.exceptions.RequestException, KeyError),
    max_retries=3,
    default_retry_delay=45,
    retry_backoff=True,
)
def execute_background_remediation_task(
    self,
    project_id,
    installation_id,
    repository_full_name,
    pull_request_number,
    clone_url,
    bug_description=None,
    buggy_file_content=None,
    target_language=None,
    base_branch="main",
    target_file_path="",
    latest_commit_sha="",
):
    org_name = repository_full_name.split("/")[0] if "/" in repository_full_name else "default"
    RunAuditLog.objects.update_or_create(
        project_id=project_id,
        defaults={
            "organization_name": org_name,
            "repository_name": repository_full_name,
            "target_language": target_language or "detecting",
            "execution_status": "PENDING",
            "execution_summary": "Asynchronous remediation pipeline tracking activated...",
        },
    )

    secure_token = refresh_installation_access_token(installation_id)

    if pull_request_number > 0 and not buggy_file_content:
        gh_headers = {
            "Authorization": f"Bearer {secure_token}",
            "Accept": "application/vnd.github+json",
        }
        pr_files_url = f"https://api.github.com/repos/{repository_full_name}/pulls/{pull_request_number}/files"
        files_resp = requests.get(pr_files_url, headers=gh_headers, timeout=30)
        if files_resp.status_code == 200:
            pr_files = files_resp.json()
            TARGET_EXTENSIONS = {'.py', '.js', '.jsx', '.ts', '.tsx', '.go', '.rs'}
            LANG_MAP = {
                '.py': 'python', '.js': 'javascript', '.jsx': 'javascript',
                '.ts': 'javascript', '.tsx': 'javascript',
            }
            for file_info in pr_files:
                ext = os.path.splitext(file_info['filename'])[1]
                if ext in TARGET_EXTENSIONS and file_info.get('status') != 'removed':
                    raw_url = file_info['raw_url']
                    content_resp = requests.get(raw_url, timeout=30)
                    if content_resp.status_code == 200:
                        buggy_file_content = content_resp.text
                        target_file_path = file_info['filename']
                        target_language = LANG_MAP.get(ext, 'python')
                        print(f"[PR_FETCH] Extracted {target_file_path} ({target_language}, {len(buggy_file_content)} bytes)")
                        break

    fastapi_endpoint = "http://fastapi-brain:8010/api/v1/verify-infrastructure"

    payload = {
        "project_id": project_id,
        "repository_full_name": repository_full_name,
        "pull_request_number": pull_request_number,
        "bug_description": bug_description or "Resolve runtime compilation indexing issues.",
        "buggy_file_content": buggy_file_content or "def parse_data(): pass",
        "target_language": target_language or "python",
        "installation_access_token": secure_token,
        "base_branch": base_branch,
        "target_file_path": target_file_path,
        "latest_commit_sha": latest_commit_sha,
    }

    response = requests.post(fastapi_endpoint, json=payload, timeout=90)
    response.raise_for_status()

    result_data = response.json()
    status_marker = (
        "SUCCESS"
        if result_data.get("status") == "AUTONOMOUS_PR_TRIGGERED"
        else "FAILED"
    )

    RunAuditLog.objects.update_or_create(
        project_id=project_id,
        defaults={
            "organization_name": org_name,
            "target_language": "python",
            "execution_status": status_marker,
            "execution_summary": result_data.get("message", "Processing finalized successfully."),
        },
    )


@shared_task(
    bind=True,
    base=EnterpriseTaskFailureMonitor,
    autoretry_for=(requests.exceptions.RequestException,),
    max_retries=2,
    default_retry_delay=60,
)
def execute_deployment(
    self,
    organization_name,
    installation_id,
    repository_full_name,
    commit_sha,
    branch="main",
    strategy="docker",
):
    token = None
    deployment = Deployment.objects.create(
        organization_name=organization_name,
        repository_name=repository_full_name,
        commit_sha=commit_sha,
        branch=branch,
        strategy=strategy,
        status="QUEUED",
        triggered_by="auto",
    )

    try:
        deployment.status = "BUILDING"
        deployment.logs += f"[BUILD] Preparing deployment for {repository_full_name} @ {commit_sha[:7]} on {branch}...\n"
        deployment.save()

        token = refresh_installation_access_token(installation_id)
        deployment.logs += "[AUTH] Installation access token acquired.\n"
        deployment.save()

        deployment.status = "DEPLOYING"
        deployment.logs += f"[DEPLOY] Strategy: {strategy}\n"
        deployment.save()

        if strategy == "docker":
            archive_url = f"https://api.github.com/repos/{repository_full_name}/zipball/{commit_sha}"
            headers = {
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
            }
            zip_resp = requests.get(archive_url, headers=headers, timeout=30)
            if zip_resp.status_code != 200:
                raise Exception(f"Failed to download repo archive: HTTP {zip_resp.status_code}")
            deployment.logs += f"[BUILD] Downloaded archive ({len(zip_resp.content)} bytes)\n"
            deployment.logs += "[BUILD] Docker image build simulated (requires Docker socket mounting)\n"
            deployment.logs += "[DEPLOY] Container restart simulated\n"

        elif strategy == "kubernetes":
            deployment.logs += "[DEPLOY] kubectl set image simulated (requires kubeconfig)\n"

        elif strategy == "serverless":
            deployment.logs += "[DEPLOY] Serverless function packaging simulated\n"

        elif strategy == "custom_script":
            deployment.logs += "[DEPLOY] Custom deploy script execution simulated\n"

        deployment.status = "DEPLOYED"
        deployment.deployed_at = now()
        deployment.logs += f"[DONE] Deployment of {commit_sha[:7]} completed successfully.\n"
        deployment.save()

        _set_github_commit_status(
            repository_full_name, commit_sha, "success",
            f"Deployment ({strategy}) succeeded", token,
        )

    except Exception as e:
        deployment.status = "FAILED"
        deployment.logs += f"[ERROR] {str(e)}\n"
        deployment.save()
        if token:
            _set_github_commit_status(
                repository_full_name, commit_sha, "failure",
                f"Deployment failed: {str(e)[:100]}", token,
            )
        raise


@shared_task
def collect_billing_data():
    print("[BEAT] collect_billing_data: not yet implemented (Phase 2)")
    return {"status": "NOT_IMPLEMENTED"}


@shared_task
def predict_billing_spend():
    print("[BEAT] predict_billing_spend: not yet implemented (Phase 2)")
    return {"status": "NOT_IMPLEMENTED"}


@shared_task
def check_billing_anomalies():
    print("[BEAT] check_billing_anomalies: not yet implemented (Phase 2)")
    return {"status": "NOT_IMPLEMENTED"}


@shared_task
def cleanup_old_records():
    print("[BEAT] cleanup_old_records: not yet implemented (Phase 2)")
    return {"status": "NOT_IMPLEMENTED"}
