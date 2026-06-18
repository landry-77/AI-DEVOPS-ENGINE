import json
from django.shortcuts import render, redirect
from django.views import View
from django.http import HttpResponseRedirect, JsonResponse, HttpResponse
from django.contrib import messages
from django.conf import settings
from django.contrib.auth import get_user_model, login, authenticate, logout
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm
from django.contrib.auth.views import LoginView as BaseLoginView
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from django.core.serializers import serialize
from django.views.generic import ListView
from django import forms
from .models import GitHubIntegration, RunAuditLog, DeveloperAPIKey, Deployment, AuditLogEntry, CLISession, BillingRecord, BillingForecast, BillingAlert
from .emails import send_instant_usage_invoice_email
from .auth_decorators import require_api_key, require_cli_session
from .tasks import execute_background_remediation_task, execute_deployment, collect_billing_data, predict_billing_spend, check_billing_anomalies
from .payment_backends import get_payment_backend


class SignUpForm(UserCreationForm):
    email = forms.EmailField(required=True)

    class Meta(UserCreationForm.Meta):
        fields = ("username", "email", "password1", "password2")

    def save(self, commit=True):
        user = super().save(commit=False)
        user.email = self.cleaned_data["email"]
        if commit:
            user.save()
        return user


class LandingView(View):
    def get(self, request):
        return render(request, "landing.html")


class SignupView(View):
    def get(self, request):
        form = SignUpForm()
        return render(request, "signup.html", {"form": form})

    def post(self, request):
        form = SignUpForm(request.POST)
        if form.is_valid():
            user = form.save()
            raw_password = form.cleaned_data.get("password1")
            user = authenticate(username=user.username, password=raw_password)
            login(request, user)
            messages.success(request, "Account created. Welcome to AI DevOps Engine!")
            return redirect("/dashboard/")
        return render(request, "signup.html", {"form": form})


class LoginView(BaseLoginView):
    template_name = "login.html"

    def get_success_url(self):
        user = self.request.user
        if user.is_staff:
            return "/dashboard/admin/"
        return settings.LOGIN_REDIRECT_URL


class LogoutView(View):
    def get(self, request):
        logout(request)
        return redirect("/")


class GitHubAppCallbackView(View):
    def get(self, request):
        installation_id = request.GET.get('installation_id')
        setup_action = request.GET.get('setup_action')
        cli_setup = request.GET.get('cli_setup')

        if not installation_id:
            messages.error(request, "Security handshake aborted: Missing installation confirmation token.")
            return HttpResponseRedirect('/dashboard/error')

        if request.user.is_authenticated:
            user_org_name = request.user.username
            integration, created = GitHubIntegration.objects.update_or_create(
                organization_name=user_org_name,
                defaults={
                    'installation_id': installation_id,
                    'encrypted_access_token': "",
                },
            )
            if cli_setup:
                raw_token, session = CLISession.generate_token_for_org(user_org_name, installation_id)
                return render(request, "cli_auth_success.html", {
                    "session_token": raw_token,
                    "expires_at": session.expires_at,
                    "organization_name": user_org_name,
                })
            messages.success(request, "Successfully integrated with organization workspace profiles.")
            return HttpResponseRedirect('/dashboard/')
        else:
            return render(request, "cli_auth_required.html", {
                "install_url": f"https://github.com/apps/{settings.GITHUB_APP_IDENTIFIER}/installations/new",
                "installation_id": installation_id,
            })


class CLIAuthTokenView(LoginRequiredMixin, View):
    def post(self, request):
        org_name = request.user.username
        integration = GitHubIntegration.objects.filter(organization_name=org_name).first()
        if not integration:
            return JsonResponse({"error": "No GitHub App installation found. Install the app first via /dashboard/github/."}, status=400)
        raw_token, session = CLISession.generate_token_for_org(org_name, integration.installation_id)
        return JsonResponse({
            "session_token": raw_token,
            "expires_at": session.expires_at.isoformat(),
            "organization_name": org_name,
        })


class CLIAuthExchangeView(View):
    @method_decorator(csrf_exempt)
    def dispatch(self, *args, **kwargs):
        return super().dispatch(*args, **kwargs)

    def post(self, request):
        try:
            body = json.loads(request.body)
            installation_id = body.get("installation_id")
            org_name = body.get("organization_name")
            if not installation_id or not org_name:
                return JsonResponse({"error": "Missing installation_id or organization_name"}, status=400)
            raw_token, session = CLISession.generate_token_for_org(org_name, installation_id)
            return JsonResponse({
                "session_token": raw_token,
                "expires_at": session.expires_at.isoformat(),
                "organization_name": org_name,
            })
        except Exception as e:
            return JsonResponse({"error": str(e)}, status=500)


class UserDashboardView(View):
    def get(self, request):
        integrations = GitHubIntegration.objects.all()
        return render(request, "dashboard.html", {"integrations": integrations})


class AdminDashboardView(LoginRequiredMixin, View):
    def get(self, request):
        if not request.user.is_staff:
            return redirect("/dashboard/")
        User = get_user_model()
        users = User.objects.all().values("id", "username", "email", "is_staff", "is_superuser", "is_active", "date_joined")
        return render(request, "admin_dashboard.html", {
            "users": users,
            "total_users": users.count(),
            "active_integrations": GitHubIntegration.objects.count(),
            "total_logs": AuditLogEntry.objects.count(),
            "total_deployments": Deployment.objects.count(),
        })


class AdminToggleUserActiveView(LoginRequiredMixin, View):
    def post(self, request):
        if not request.user.is_staff:
            return redirect("/dashboard/")
        from django.contrib.auth import get_user_model
        User = get_user_model()
        user_id = request.POST.get("user_id")
        if user_id and str(user_id) != str(request.user.id):
            u = User.objects.get(id=user_id)
            u.is_active = not u.is_active
            u.save()
            from django.contrib import messages
            messages.success(request, f"User '{u.username}' {'activated' if u.is_active else 'deactivated'}.")
        return redirect("/dashboard/admin/")


class AdminDeleteUserView(LoginRequiredMixin, View):
    def post(self, request):
        if not request.user.is_staff:
            return redirect("/dashboard/")
        from django.contrib.auth import get_user_model
        User = get_user_model()
        user_id = request.POST.get("user_id")
        if user_id and str(user_id) != str(request.user.id):
            u = User.objects.get(id=user_id)
            username = u.username
            u.delete()
            from django.contrib import messages
            messages.success(request, f"User '{username}' deleted.")
        return redirect("/dashboard/admin/")


class PRDashboardView(View):
    def get(self, request):
        return render(request, "pr_list.html")


class DeploymentDashboardView(View):
    def get(self, request):
        return render(request, "deployments.html")


class GitHubIntegrationDashboardView(View):
    def get(self, request):
        tenant = getattr(request, "tenant", None)
        integrations = GitHubIntegration.objects.filter(organization_name=tenant) if tenant else GitHubIntegration.objects.all()
        return render(request, "integrations.html", {"integrations": integrations})


def _log_audit(request, action, resource_type, resource_id=""):
    tenant = getattr(request, "tenant", None) or "anonymous"
    actor = getattr(request, "user", None)
    actor_name = actor.username if actor and actor.is_authenticated else "api_key:" + str(tenant)
    AuditLogEntry.objects.create(
        organization_name=str(tenant),
        actor=actor_name,
        action=action,
        resource_type=resource_type,
        resource_id=str(resource_id),
        ip_address=request.META.get("REMOTE_ADDR"),
    )


class LogsStreamView(View):
    def get(self, request):
        tenant = getattr(request, "tenant", None)
        logs = RunAuditLog.objects.for_tenant(tenant).order_by('-created_at')[:50] if tenant else RunAuditLog.objects.all().order_by('-created_at')[:50]
        data = [
            {
                "project_id": log.project_id,
                "repository_name": log.repository_name,
                "target_language": log.target_language,
                "execution_status": log.execution_status,
                "execution_summary": log.execution_summary,
                "pull_request_number": log.pull_request_number,
                "suggestion_posted": log.suggestion_posted,
                "created_at": log.created_at.isoformat(),
            }
            for log in logs
        ]
        _log_audit(request, "API_CALL", "logs_stream")
        return JsonResponse(data, safe=False)


class LogDetailView(View):
    def get(self, request, project_id):
        log = RunAuditLog.objects.filter(project_id=project_id).first()
        if not log:
            return JsonResponse({"error": "No log found for this project"}, status=404)
        _log_audit(request, "VIEW", "run_audit_log", project_id)
        return JsonResponse({
            "project_id": log.project_id,
            "repository_name": log.repository_name,
            "target_language": log.target_language,
            "execution_status": log.execution_status,
            "execution_summary": log.execution_summary,
            "created_at": log.created_at.isoformat(),
        })


class CreateStripeCheckoutSessionView(LoginRequiredMixin, View):
    def post(self, request, *args, **kwargs):
        org_name = request.user.username
        try:
            backend = get_payment_backend()
            result = backend.create_checkout_session(
                customer_email=request.user.email,
                organization_name=org_name,
            )
            if result.get("manual"):
                messages.info(request, result.get("message", "Invoice request submitted."))
                return redirect("/dashboard/")
            return HttpResponseRedirect(result["url"])
        except Exception as e:
            return JsonResponse({"error": str(e)}, status=500)


@method_decorator(csrf_exempt, name='dispatch')
class StripeWebhookListenerView(View):
    def post(self, request, *args, **kwargs):
        try:
            backend = get_payment_backend()
            sig_header = request.META.get('HTTP_STRIPE_SIGNATURE', '')
            result = backend.handle_webhook(request.body, sig_header)
            if result.get("event") == "error":
                return HttpResponse(status=400)
            return HttpResponse(status=200)
        except Exception as e:
            print(f"[Billing] Webhook error: {e}")
            return HttpResponse(status=400)


@method_decorator(csrf_exempt, name='dispatch')
class UsageMeteringWebhookView(View):
    def post(self, request, *args, **kwargs):
        auth_header = request.META.get('HTTP_AUTHORIZATION')
        if not auth_header or auth_header != "Bearer LocalSecretInternalTokenBetweenServices":
            return JsonResponse({"error": "Unauthorized internal service access."}, status=403)

        try:
            body = json.loads(request.body)
            project_id = body.get("project_id")
            org_name = body.get("organization_name")

            print(f"[Meter] Usage unit recorded: 1 bug fix for {org_name}, project {project_id}")

            User = get_user_model()
            try:
                user = User.objects.get(username=org_name)
                send_instant_usage_invoice_email(
                    user_email=user.email,
                    org_name=org_name,
                    project_id=project_id,
                )
            except User.DoesNotExist:
                print(f"[Meter] No user found for org {org_name} — skipping email notification.")

            return JsonResponse({"status": "METER_RECORDED", "project_id": project_id}, status=200)
        except Exception as e:
            return JsonResponse({"error": str(e)}, status=500)



@method_decorator(csrf_exempt, name='dispatch')
class CLIEngineTriggerGatewayView(View):
    def post(self, request, *args, **kwargs):
        auth_header = request.META.get("HTTP_AUTHORIZATION", "")
        if not auth_header.startswith("Bearer "):
            return JsonResponse({"error": "Missing or malformed Authorization header token."}, status=401)

        raw_cred = auth_header.split(" ")[1]
        import hashlib
        from django.utils import timezone
        hashed = hashlib.sha256(raw_cred.encode("utf-8")).hexdigest()

        session = CLISession.objects.filter(
            session_token_hash=hashed, is_active=True, expires_at__gt=timezone.now()
        ).first()
        api_key = DeveloperAPIKey.objects.filter(
            hashed_key=hashed, is_active=True
        ).first()

        if session:
            request.organization_name = session.organization_name
        elif api_key:
            request.organization_name = api_key.organization_name
        else:
            return JsonResponse({"error": "Invalid or expired credentials. Run 'patch-bot --auth' to re-authenticate."}, status=403)

        try:
            body = json.loads(request.body)
            project_id = body.get("project_id")
            target_language = body.get("target_language")
            bug_description = body.get("bug_description")
            buggy_file_content = body.get("buggy_file_content")

            if not all([project_id, target_language, bug_description, buggy_file_content]):
                return JsonResponse({"error": "Malformed payload structure: Missing parameters."}, status=400)

            integration = GitHubIntegration.objects.filter(
                organization_name=request.organization_name
            ).first()
            installation_id = str(integration.installation_id) if integration else "cli_context_direct"

            execute_background_remediation_task.delay(
                project_id=project_id,
                installation_id=installation_id,
                repository_full_name=f"{request.organization_name}/cli-workspace",
                pull_request_number=0,
                clone_url="local_stream",
                bug_description=bug_description,
                buggy_file_content=buggy_file_content,
                target_language=target_language,
                base_branch="main",
                target_file_path="",
                latest_commit_sha="",
            )

            _log_audit(request, "API_CALL", "cli_trigger_fix", project_id)

            return JsonResponse({
                "status": "QUEUED_FROM_CLI",
                "message": f"Remediation thread [{project_id}] successfully scheduled for sandbox execution.",
            }, status=202)

        except Exception as e:
            _log_audit(request, "API_ERROR", "cli_trigger_fix", str(e))
            return JsonResponse({"error": f"Internal pipeline gateway error: {str(e)}"}, status=500)


class APIKeyDashboardListView(LoginRequiredMixin, ListView):
    model = DeveloperAPIKey
    template_name = "api_key_management.html"
    context_object_name = "api_keys"

    def get_queryset(self):
        org_name = self.request.user.username
        return DeveloperAPIKey.objects.filter(organization_name=org_name).order_by("-created_at")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        raw_key = self.request.session.pop("LAST_GENERATED_RAW_KEY", None)
        if raw_key:
            context["raw_key_display"] = raw_key
        return context


class GenerateNewAPIKeyView(LoginRequiredMixin, View):
    def post(self, request, *args, **kwargs):
        org_name = request.user.username

        existing_keys_count = DeveloperAPIKey.objects.filter(organization_name=org_name, is_active=True).count()
        if existing_keys_count >= 5:
            messages.error(request, "Security threshold reached: You cannot maintain more than 5 active API keys simultaneously.")
            return redirect("api_key_dashboard")

        raw_token, key_instance = DeveloperAPIKey.generate_key_for_org(org_name)

        request.session["LAST_GENERATED_RAW_KEY"] = raw_token

        messages.success(request, "New cryptographic API key token successfully initialized.")
        return redirect("api_key_dashboard")


class RevokeAPIKeyView(LoginRequiredMixin, View):
    def post(self, request, key_id, *args, **kwargs):
        org_name = request.user.username

        try:
            key_record = DeveloperAPIKey.objects.get(id=key_id, organization_name=org_name)
            key_record.is_active = False
            key_record.save()
            messages.warning(request, f"API credential token with prefix {key_record.prefix} has been revoked.")
        except DeveloperAPIKey.DoesNotExist:
            messages.error(request, "Requested key context allocation not found.")

        return redirect("api_key_dashboard")


class DeploymentListView(View):
    def get(self, request):
        tenant = getattr(request, "tenant", None)
        deployments = Deployment.objects.for_tenant(tenant).order_by('-created_at')[:100] if tenant else Deployment.objects.all().order_by('-created_at')[:100]
        data = [
            {
                "id": d.id,
                "repository_name": d.repository_name,
                "commit_sha": d.commit_sha,
                "branch": d.branch,
                "status": d.status,
                "strategy": d.strategy,
                "target_url": d.target_url,
                "logs": d.logs,
                "triggered_by": d.triggered_by,
                "created_at": d.created_at.isoformat(),
                "deployed_at": d.deployed_at.isoformat() if d.deployed_at else None,
            }
            for d in deployments
        ]
        return JsonResponse(data, safe=False)


class DeploymentDetailView(View):
    def get(self, request, deployment_id):
        tenant = getattr(request, "tenant", None)
        dep = Deployment.objects.for_tenant(tenant).filter(id=deployment_id).first() if tenant else Deployment.objects.filter(id=deployment_id).first()
        if not dep:
            return JsonResponse({"error": "Deployment not found"}, status=404)
        return JsonResponse({
            "id": dep.id,
            "organization_name": dep.organization_name,
            "repository_name": dep.repository_name,
            "commit_sha": dep.commit_sha,
            "branch": dep.branch,
            "status": dep.status,
            "strategy": dep.strategy,
            "target_url": dep.target_url,
            "logs": dep.logs,
            "triggered_by": dep.triggered_by,
            "created_at": dep.created_at.isoformat(),
            "deployed_at": dep.deployed_at.isoformat() if dep.deployed_at else None,
        })


@method_decorator(csrf_exempt, name='dispatch')
class TriggerDeploymentView(View):
    def post(self, request, *args, **kwargs):
        try:
            body = json.loads(request.body)
            repository_full_name = body.get("repository_full_name")
            commit_sha = body.get("commit_sha")
            branch = body.get("branch", "main")
            strategy = body.get("strategy", "docker")

            if not all([repository_full_name, commit_sha]):
                return JsonResponse({"error": "Missing required fields: repository_full_name, commit_sha"}, status=400)

            org_name = getattr(request, "tenant", None) or request.user.username
            integration = GitHubIntegration.objects.filter(organization_name=org_name).first()
            installation_id = str(integration.installation_id) if integration else "cli_context_direct"

            execute_deployment.delay(
                organization_name=org_name,
                installation_id=installation_id,
                repository_full_name=repository_full_name,
                commit_sha=commit_sha,
                branch=branch,
                strategy=strategy,
            )

            return JsonResponse({
                "status": "DEPLOY_QUEUED",
                "message": f"Deployment of {repository_full_name} @ {commit_sha[:7]} queued.",
            }, status=202)

        except Exception as e:
            return JsonResponse({"error": str(e)}, status=500)


class BillingDashboardView(View):
    def get(self, request):
        return render(request, "cost_intelligence.html")


@method_decorator(csrf_exempt, name='dispatch')
class BillingRecordIngestionView(View):
    def post(self, request, *args, **kwargs):
        auth_header = request.META.get('HTTP_AUTHORIZATION')
        if not auth_header or auth_header != "Bearer LocalSecretInternalTokenBetweenServices":
            return JsonResponse({"error": "Unauthorized internal service access."}, status=403)

        try:
            body = json.loads(request.body)
            records = body if isinstance(body, list) else [body]
            task = collect_billing_data.delay(records)
            return JsonResponse({
                "status": "QUEUED",
                "task_id": task.id,
                "records": len(records),
            }, status=202)
        except Exception as e:
            return JsonResponse({"error": str(e)}, status=500)


class BillingSpendSummaryView(View):
    def get(self, request):
        tenant = getattr(request, "tenant", None)
        records = BillingRecord.objects.for_tenant(tenant) if tenant else BillingRecord.objects.all()

        total = records.aggregate(total=Sum("cost"))["total"] or 0
        by_provider = records.values("provider").annotate(total=Sum("cost")).order_by("-total")
        by_service = records.values("provider", "service").annotate(total=Sum("cost")).order_by("-total")[:10]

        active_alerts = BillingAlert.objects.filter(is_acknowledged=False).count()

        return JsonResponse({
            "total_cost": float(total),
            "by_provider": [
                {"provider": p["provider"], "cost": float(p["total"])} for p in by_provider
            ],
            "top_services": [
                {"provider": s["provider"], "service": s["service"], "cost": float(s["total"])}
                for s in by_service
            ],
            "active_alerts": active_alerts,
        })


class BillingPredictionListView(View):
    def get(self, request):
        tenant = getattr(request, "tenant", None)
        forecasts = BillingForecast.objects.for_tenant(tenant) if tenant else BillingForecast.objects.all()
        data = [
            {
                "id": f.id,
                "provider": f.provider,
                "forecast_month": f.forecast_month.isoformat(),
                "predicted_cost": float(f.predicted_cost),
                "confidence_lower": float(f.confidence_lower),
                "confidence_upper": float(f.confidence_upper),
                "actual_cost": float(f.actual_cost) if f.actual_cost else None,
                "model_used": f.model_used,
                "created_at": f.created_at.isoformat(),
            }
            for f in forecasts
        ]
        return JsonResponse(data, safe=False)


class BillingAlertListView(View):
    def get(self, request):
        tenant = getattr(request, "tenant", None)
        acknowledged = request.GET.get("acknowledged", "false").lower() == "true"
        alerts = BillingAlert.objects.for_tenant(tenant) if tenant else BillingAlert.objects.all()
        if not acknowledged:
            alerts = alerts.filter(is_acknowledged=False)
        data = [
            {
                "id": a.id,
                "provider": a.provider,
                "service": a.service,
                "severity": a.severity,
                "message": a.message,
                "current_cost": float(a.current_cost),
                "threshold_cost": float(a.threshold_cost),
                "is_acknowledged": a.is_acknowledged,
                "created_at": a.created_at.isoformat(),
            }
            for a in alerts
        ]
        return JsonResponse(data, safe=False)


@method_decorator(csrf_exempt, name='dispatch')
class BillingAlertAcknowledgeView(View):
    def post(self, request, alert_id):
        tenant = getattr(request, "tenant", None)
        qs = BillingAlert.objects.for_tenant(tenant) if tenant else BillingAlert.objects.all()
        alert = qs.filter(id=alert_id).first()
        if not alert:
            return JsonResponse({"error": "Alert not found"}, status=404)
        alert.is_acknowledged = True
        alert.save()
        return JsonResponse({"status": "ACKNOWLEDGED", "alert_id": alert.id})
