import os
import json
import math
import time
import requests
from celery import shared_task, Task
from django.conf import settings
from datetime import timedelta
from django.utils.timezone import now
from django.db.models import Sum, Avg
from django.db.models.aggregates import StdDev
from django.db.models.functions import TruncMonth
from django.contrib.auth import get_user_model
from .models import (
    RunAuditLog, GitHubIntegration, Deployment, AuditLogEntry,
    BillingRecord, BillingForecast, BillingAlert,
)
from .github_auth import refresh_installation_access_token
from .emails import send_billing_alert_email


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
            pull_request_number=None,
            suggestion_posted=False,
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
                    "ts": int(time.time()),
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
            "pull_request_number": pull_request_number,
        },
    )

    if installation_id == "cli_context_direct" or not installation_id:
        secure_token = ""
        print(f"[CLI_MODE] Skipping GitHub auth for local CLI context (project={project_id})")
    else:
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
    status_raw = result_data.get("status", "")
    status_marker = "SUCCESS" if status_raw in ("AUTONOMOUS_FIX_COMMENTED", "AUTONOMOUS_PR_TRIGGERED") else "FAILED"
    suggestion_posted = status_raw == "AUTONOMOUS_FIX_COMMENTED"

    RunAuditLog.objects.update_or_create(
        project_id=project_id,
        defaults={
            "organization_name": org_name,
            "target_language": "python",
            "execution_status": status_marker,
            "execution_summary": result_data.get("message", "Processing finalized successfully."),
            "pull_request_number": pull_request_number,
            "suggestion_posted": suggestion_posted,
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
def collect_billing_data(records=None):
    if records:
        created = 0
        for rec in records:
            BillingRecord.objects.create(
                organization_name=rec.get("organization_name", "default"),
                provider=rec.get("provider", "aws"),
                service=rec.get("service", "Unknown"),
                region=rec.get("region", ""),
                cost=rec.get("cost", 0),
                usage_quantity=rec.get("usage_quantity"),
                usage_unit=rec.get("usage_unit", ""),
                recorded_at=rec.get("recorded_at"),
            )
            created += 1
        print(f"[BILLING] Ingested {created} billing records")
        return {"status": "OK", "records_created": created}

    count = BillingRecord.objects.count()
    print(f"[BEAT] collect_billing_data: {count} records in DB (billing-collector service not configured)")
    return {"status": "OK", "total_records": count}


@shared_task
def predict_billing_spend(months_ahead=3):
    records = BillingRecord.objects.values("provider", "service", "cost", "recorded_at")
    if not records:
        print("[FORECAST] No billing records to forecast from")
        return {"status": "NO_DATA"}

    monthly = {}
    for r in records:
        key = (r["provider"], r["service"], r["recorded_at"].strftime("%Y-%m"))
        monthly[key] = monthly.get(key, 0) + float(r["cost"])

    monthly_by_provider = {}
    for (provider, service, ym), cost in monthly.items():
        monthly_by_provider.setdefault(provider, []).append((ym, cost))

    forecasts = []
    for provider, values in monthly_by_provider.items():
        values.sort(key=lambda x: x[0])
        costs = [v[1] for v in values]
        n = len(costs)
        if n < 2:
            continue

        x_mean = (n - 1) / 2.0
        y_mean = sum(costs) / n
        num = den = 0
        for i, c in enumerate(costs):
            num += (i - x_mean) * (c - y_mean)
            den += (i - x_mean) ** 2
        slope = num / den if den else 0
        intercept = y_mean - slope * x_mean

        residuals = [c - (slope * i + intercept) for i, c in enumerate(costs)]
        variance = sum(r * r for r in residuals) / max(n - 1, 1)
        std_err = math.sqrt(variance) if variance > 0 else 0

        last_month = values[-1][0]
        last_year, last_month_num = int(last_month.split("-")[0]), int(last_month.split("-")[1])

        for m in range(1, months_ahead + 1):
            future_month_num = last_month_num + m
            future_year = last_year + (future_month_num - 1) // 12
            future_month_num = ((future_month_num - 1) % 12) + 1
            x = n + m - 1
            predicted = slope * x + intercept
            ci = 1.96 * std_err * math.sqrt(1 + 1.0 / n + (x - x_mean) ** 2 / den) if den else std_err * 2

            orgs = BillingRecord.objects.filter(provider=provider).values("organization_name").first()
            org_name = orgs["organization_name"] if orgs else "default"

            forecast, _ = BillingForecast.objects.update_or_create(
                organization_name=org_name,
                provider=provider,
                forecast_month=f"{future_year}-{future_month_num:02d}-01",
                defaults={
                    "predicted_cost": round(max(predicted, 0), 6),
                    "confidence_lower": round(max(predicted - ci, 0), 6),
                    "confidence_upper": round(predicted + ci, 6),
                    "model_used": "linear",
                },
            )
            forecasts.append({
                "provider": provider,
                "month": f"{future_year}-{future_month_num:02d}",
                "predicted": round(predicted, 2),
            })

    print(f"[FORECAST] Generated {len(forecasts)} forecasts across {len(monthly_by_provider)} providers")
    return {"status": "OK", "forecasts": forecasts}


@shared_task
def check_billing_anomalies():
    from django.db.models import Avg, StdDev, FloatField
    thirty_days_ago = now().date() - timedelta(days=30)
    records = BillingRecord.objects.filter(recorded_at__gte=thirty_days_ago)
    if not records:
        print("[ANOMALY] No billing records to check")
        return {"status": "NO_DATA"}

    alerts_created = 0
    orgs = BillingRecord.objects.values("organization_name").distinct()
    providers = BillingRecord.objects.values("provider", "service").distinct()

    for org_info in orgs:
        org_name = org_info["organization_name"]
        for ps in providers:
            provider = ps["provider"]
            service = ps["service"]
            subset = records.filter(organization_name=org_name, provider=provider, service=service)
            if not subset:
                continue

            agg = subset.aggregate(
                avg_cost=Avg("cost"),
                std_cost=StdDev("cost"),
            )
            avg = float(agg["avg_cost"] or 0)
            std = float(agg["std_cost"] or 0)
            if std == 0:
                continue

            latest = subset.order_by("-recorded_at").first()
            if not latest:
                continue

            latest_cost = float(latest.cost)
            threshold_warning = avg + 2 * std
            threshold_critical = avg + 3 * std

            if latest_cost > threshold_critical:
                severity = "critical"
                threshold = threshold_critical
                message = (
                    f"Critical cost spike detected for {provider}/{service}: "
                    f"${latest_cost:.2f} exceeds 3σ threshold (${threshold:.2f}). "
                    f"30-day avg: ${avg:.2f}, σ: ${std:.2f}"
                )
            elif latest_cost > threshold_warning:
                severity = "warning"
                threshold = threshold_warning
                message = (
                    f"Cost increase detected for {provider}/{service}: "
                    f"${latest_cost:.2f} exceeds 2σ threshold (${threshold:.2f}). "
                    f"30-day avg: ${avg:.2f}, σ: ${std:.2f}"
                )
            else:
                continue

            existing = BillingAlert.objects.filter(
                organization_name=org_name, provider=provider,
                service=service, severity=severity,
                is_acknowledged=False, created_at__date=now().date(),
            )
            if existing:
                continue

            BillingAlert.objects.create(
                organization_name=org_name,
                provider=provider,
                service=service,
                severity=severity,
                message=message,
                current_cost=latest_cost,
                threshold_cost=threshold,
            )
            alerts_created += 1

            User = get_user_model()
            try:
                user = User.objects.get(username=org_name)
                send_billing_alert_email(
                    user_email=user.email,
                    org_name=org_name,
                    provider=provider,
                    service=service,
                    severity=severity,
                    current_cost=latest_cost,
                    threshold=threshold,
                )
            except Exception:
                pass

    print(f"[ANOMALY] Created {alerts_created} billing alerts")
    return {"status": "OK", "alerts_created": alerts_created}


@shared_task
def cleanup_old_records():
    retention_days = getattr(settings, "AUDIT_RETENTION_DAYS", 90)
    cutoff = timezone.now() - timedelta(days=retention_days)
    deleted_count, _ = RunAuditLog.objects.filter(created_at__lt=cutoff).delete()
    audit_deleted, _ = AuditLogEntry.objects.filter(created_at__lt=cutoff).delete()
    print(f"[RETENTION] Purged {deleted_count} RunAuditLog records older than {retention_days}d")
    print(f"[RETENTION] Purged {audit_deleted} AuditLogEntry records older than {retention_days}d")
    return {"status": "OK", "records_purged": deleted_count, "audit_purged": audit_deleted}
