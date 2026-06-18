from django.db import migrations


def enable_rls(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    schema_editor.execute("ALTER TABLE dashboard_runauditlog ENABLE ROW LEVEL SECURITY;")
    schema_editor.execute("""
        CREATE POLICY tenant_isolation_policy ON dashboard_runauditlog
        FOR ALL
        USING (repository_name LIKE current_setting('app.current_tenant') || '/%');
    """)


def disable_rls(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    schema_editor.execute("ALTER TABLE dashboard_runauditlog DISABLE ROW LEVEL SECURITY;")
    schema_editor.execute("DROP POLICY tenant_isolation_policy ON dashboard_runauditlog;")


class Migration(migrations.Migration):

    dependencies = [
        ("dashboard", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(enable_rls, disable_rls),
    ]
