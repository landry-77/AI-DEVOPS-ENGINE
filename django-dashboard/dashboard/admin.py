from django.contrib import admin
from .models import GitHubIntegration, RunAuditLog, Deployment, BillingRecord, BillingForecast, BillingAlert


@admin.register(GitHubIntegration)
class GitHubIntegrationAdmin(admin.ModelAdmin):
    list_display = ('organization_name', 'installation_id', 'registered_at')
    readonly_fields = ('registered_at',)


@admin.register(RunAuditLog)
class RunAuditLogAdmin(admin.ModelAdmin):
    list_display = ('project_id', 'repository_name', 'target_language', 'execution_status', 'created_at')
    list_filter = ('execution_status', 'target_language')
    readonly_fields = ('created_at',)


@admin.register(Deployment)
class DeploymentAdmin(admin.ModelAdmin):
    list_display = ('repository_name', 'commit_sha', 'status', 'strategy', 'created_at', 'deployed_at')
    list_filter = ('status', 'strategy')
    readonly_fields = ('created_at', 'deployed_at')


@admin.register(BillingRecord)
class BillingRecordAdmin(admin.ModelAdmin):
    list_display = ('organization_name', 'provider', 'service', 'cost', 'recorded_at')
    list_filter = ('provider', 'service')
    readonly_fields = ('created_at',)


@admin.register(BillingForecast)
class BillingForecastAdmin(admin.ModelAdmin):
    list_display = ('organization_name', 'provider', 'forecast_month', 'predicted_cost', 'model_used')
    list_filter = ('provider', 'model_used')
    readonly_fields = ('created_at',)


@admin.register(BillingAlert)
class BillingAlertAdmin(admin.ModelAdmin):
    list_display = ('organization_name', 'provider', 'service', 'severity', 'current_cost', 'is_acknowledged', 'created_at')
    list_filter = ('severity', 'is_acknowledged', 'provider')
    readonly_fields = ('created_at',)
