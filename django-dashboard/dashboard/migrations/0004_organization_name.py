from django.db import migrations, models


def backfill_org_name(apps, schema_editor):
    RunAuditLog = apps.get_model("dashboard", "RunAuditLog")
    RunAuditLog.objects.filter(organization_name="default").update(
        organization_name=models.F("repository_name")
    )


def recreate_rls_policy(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    schema_editor.execute("DROP POLICY IF EXISTS tenant_isolation_policy ON dashboard_runauditlog;")
    schema_editor.execute("""
        CREATE POLICY tenant_isolation_policy ON dashboard_runauditlog
        FOR ALL
        USING (
            current_setting('app.current_tenant', true) IS NULL
            OR organization_name = current_setting('app.current_tenant')
        );
    """)


def drop_rls_policy(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    schema_editor.execute("DROP POLICY tenant_isolation_policy ON dashboard_runauditlog;")


class Migration(migrations.Migration):

    dependencies = [
        ("dashboard", "0003_developerapikey"),
    ]

    operations = [
        migrations.AddField(
            model_name="runauditlog",
            name="organization_name",
            field=models.CharField(default="default", max_length=255, db_index=True),
            preserve_default=False,
        ),
        migrations.RunPython(backfill_org_name, migrations.RunPython.noop),
        migrations.RunPython(recreate_rls_policy, drop_rls_policy),
    ]
