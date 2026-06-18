import dashboard.models
from django.db import migrations, models


def encrypt_existing_patched_code(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("dashboard", "0006_add_pr_fields"),
    ]

    operations = [
        migrations.CreateModel(
            name="AuditLogEntry",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("organization_name", models.CharField(db_index=True, max_length=255)),
                ("actor", models.CharField(max_length=255)),
                ("action", models.CharField(choices=[("VIEW", "View"), ("EXPORT", "Export"), ("DELETE", "Delete"), ("API_CALL", "API Call")], max_length=20)),
                ("resource_type", models.CharField(max_length=100)),
                ("resource_id", models.CharField(blank=True, default="", max_length=255)),
                ("ip_address", models.GenericIPAddressField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "verbose_name_plural": "audit log entries",
                "ordering": ["-created_at"],
            },
        ),
    ]
