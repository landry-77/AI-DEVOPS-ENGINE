import hashlib
import os
from datetime import timedelta
from django.db import models
from django.utils import timezone
from cryptography.fernet import Fernet
from django.conf import settings


class EncryptedField(models.CharField):
    def from_db_value(self, value, expression, connection):
        if not value:
            return value
        f = Fernet(settings.FERNET_KEYS[0].encode())
        return f.decrypt(value.encode()).decode()

    def get_prep_value(self, value):
        if not value:
            return value
        f = Fernet(settings.FERNET_KEYS[0].encode())
        return f.encrypt(value.encode()).decode()


class EncryptedTextField(models.TextField):
    def from_db_value(self, value, expression, connection):
        if not value:
            return value
        f = Fernet(settings.FERNET_KEYS[0].encode())
        return f.decrypt(value.encode()).decode()

    def get_prep_value(self, value):
        if not value:
            return value
        f = Fernet(settings.FERNET_KEYS[0].encode())
        return f.encrypt(value.encode()).decode()


class GitHubIntegration(models.Model):
    organization_name = models.CharField(max_length=255, unique=True)
    installation_id = models.CharField(max_length=100, unique=True)
    encrypted_access_token = EncryptedField(max_length=512)
    registered_at = models.DateTimeField(auto_now_add=True)


class TenantManager(models.Manager):
    def for_tenant(self, tenant_name):
        return self.filter(organization_name=tenant_name)


class RunAuditLog(models.Model):
    organization_name = models.CharField(max_length=255, db_index=True)
    project_id = models.CharField(max_length=255, db_index=True)
    repository_name = models.CharField(max_length=255)
    target_language = models.CharField(max_length=50)
    execution_status = models.CharField(max_length=50)
    execution_summary = models.TextField()
    pull_request_number = models.IntegerField(null=True, blank=True, default=None)
    suggestion_posted = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = TenantManager()


class DeveloperAPIKey(models.Model):
    organization_name = models.CharField(max_length=255, db_index=True)
    prefix = models.CharField(max_length=16)
    hashed_key = models.CharField(max_length=64, unique=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    @staticmethod
    def generate_key_for_org(org_name: str) -> tuple[str, "DeveloperAPIKey"]:
        raw_secret = os.urandom(24).hex()
        prefix = "sk_live_"
        full_key = f"{prefix}{raw_secret}"
        hashed = hashlib.sha256(full_key.encode("utf-8")).hexdigest()
        instance = DeveloperAPIKey.objects.create(
            organization_name=org_name,
            prefix=prefix,
            hashed_key=hashed,
        )
        return full_key, instance


class CLISession(models.Model):
    organization_name = models.CharField(max_length=255, db_index=True)
    installation_id = models.CharField(max_length=100)
    session_token_hash = models.CharField(max_length=64, unique=True)
    expires_at = models.DateTimeField()
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = TenantManager()

    @staticmethod
    def generate_token_for_org(org_name: str, installation_id: str, expiry_days: int = 30) -> tuple[str, "CLISession"]:
        raw_token = os.urandom(32).hex()
        token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
        expires = timezone.now() + timedelta(days=expiry_days)
        instance = CLISession.objects.create(
            organization_name=org_name,
            installation_id=installation_id,
            session_token_hash=token_hash,
            expires_at=expires,
        )
        return raw_token, instance


class BillingRecord(models.Model):
    PROVIDER_CHOICES = [
        ('aws', 'AWS'),
        ('gcp', 'GCP'),
        ('azure', 'Azure'),
    ]
    organization_name = models.CharField(max_length=255, db_index=True)
    provider = models.CharField(max_length=20, choices=PROVIDER_CHOICES)
    service = models.CharField(max_length=100)
    region = models.CharField(max_length=50, blank=True, default='')
    cost = models.DecimalField(max_digits=14, decimal_places=6)
    usage_quantity = models.DecimalField(max_digits=14, decimal_places=6, null=True, blank=True)
    usage_unit = models.CharField(max_length=50, blank=True, default='')
    recorded_at = models.DateField()
    created_at = models.DateTimeField(auto_now_add=True)

    objects = TenantManager()

    class Meta:
        ordering = ['-recorded_at']


class BillingForecast(models.Model):
    MODEL_CHOICES = [
        ('linear', 'Linear Regression'),
        ('moving_avg', 'Moving Average'),
    ]
    organization_name = models.CharField(max_length=255, db_index=True)
    provider = models.CharField(max_length=20)
    forecast_month = models.DateField()
    predicted_cost = models.DecimalField(max_digits=14, decimal_places=6)
    confidence_lower = models.DecimalField(max_digits=14, decimal_places=6)
    confidence_upper = models.DecimalField(max_digits=14, decimal_places=6)
    actual_cost = models.DecimalField(max_digits=14, decimal_places=6, null=True, blank=True)
    model_used = models.CharField(max_length=20, choices=MODEL_CHOICES, default='linear')
    created_at = models.DateTimeField(auto_now_add=True)

    objects = TenantManager()

    class Meta:
        ordering = ['forecast_month']


class BillingAlert(models.Model):
    SEVERITY_CHOICES = [
        ('warning', 'Warning'),
        ('critical', 'Critical'),
    ]
    organization_name = models.CharField(max_length=255, db_index=True)
    provider = models.CharField(max_length=20)
    service = models.CharField(max_length=100)
    severity = models.CharField(max_length=20, choices=SEVERITY_CHOICES)
    message = models.TextField()
    current_cost = models.DecimalField(max_digits=14, decimal_places=6)
    threshold_cost = models.DecimalField(max_digits=14, decimal_places=6)
    is_acknowledged = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = TenantManager()

    class Meta:
        ordering = ['-created_at']


class Deployment(models.Model):
    STATUS_CHOICES = [
        ('QUEUED', 'Queued'),
        ('BUILDING', 'Building'),
        ('DEPLOYING', 'Deploying'),
        ('DEPLOYED', 'Deployed'),
        ('ROLLED_BACK', 'Rolled Back'),
        ('FAILED', 'Failed'),
    ]
    STRATEGY_CHOICES = [
        ('docker', 'Docker'),
        ('kubernetes', 'Kubernetes'),
        ('serverless', 'Serverless'),
        ('custom_script', 'Custom Script'),
    ]
    organization_name = models.CharField(max_length=255, db_index=True)
    repository_name = models.CharField(max_length=255)
    commit_sha = models.CharField(max_length=40)
    branch = models.CharField(max_length=255, default='main')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='QUEUED')
    strategy = models.CharField(max_length=20, choices=STRATEGY_CHOICES, default='docker')
    target_url = models.URLField(blank=True, default='')
    logs = models.TextField(blank=True, default='')
    triggered_by = models.CharField(max_length=20, default='auto')
    created_at = models.DateTimeField(auto_now_add=True)
    deployed_at = models.DateTimeField(null=True, blank=True)

    objects = TenantManager()


class AuditLogEntry(models.Model):
    ACTION_CHOICES = [
        ('VIEW', 'View'),
        ('EXPORT', 'Export'),
        ('DELETE', 'Delete'),
        ('API_CALL', 'API Call'),
    ]
    organization_name = models.CharField(max_length=255, db_index=True)
    actor = models.CharField(max_length=255)
    action = models.CharField(max_length=20, choices=ACTION_CHOICES)
    resource_type = models.CharField(max_length=100)
    resource_id = models.CharField(max_length=255, blank=True, default="")
    ip_address = models.GenericIPAddressField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = TenantManager()

    class Meta:
        verbose_name_plural = "audit log entries"
        ordering = ["-created_at"]
