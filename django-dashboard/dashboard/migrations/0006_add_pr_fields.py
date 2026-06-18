from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('dashboard', '0005_deployment'),
    ]
    operations = [
        migrations.AddField(
            model_name='runauditlog',
            name='pull_request_number',
            field=models.IntegerField(null=True, blank=True, default=None),
        ),
        migrations.AddField(
            model_name='runauditlog',
            name='suggestion_posted',
            field=models.BooleanField(default=False),
        ),
    ]
