from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('dashboard', '0010_enterprise_compliance'),
    ]

    operations = [
        migrations.CreateModel(
            name='BillingAlert',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('organization_name', models.CharField(db_index=True, max_length=255)),
                ('provider', models.CharField(max_length=20)),
                ('service', models.CharField(max_length=100)),
                ('severity', models.CharField(choices=[('warning', 'Warning'), ('critical', 'Critical')], max_length=20)),
                ('message', models.TextField()),
                ('current_cost', models.DecimalField(decimal_places=6, max_digits=14)),
                ('threshold_cost', models.DecimalField(decimal_places=6, max_digits=14)),
                ('is_acknowledged', models.BooleanField(default=False)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
            ],
            options={
                'ordering': ['-created_at'],
            },
        ),
        migrations.CreateModel(
            name='BillingForecast',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('organization_name', models.CharField(db_index=True, max_length=255)),
                ('provider', models.CharField(max_length=20)),
                ('forecast_month', models.DateField()),
                ('predicted_cost', models.DecimalField(decimal_places=6, max_digits=14)),
                ('confidence_lower', models.DecimalField(decimal_places=6, max_digits=14)),
                ('confidence_upper', models.DecimalField(decimal_places=6, max_digits=14)),
                ('actual_cost', models.DecimalField(blank=True, decimal_places=6, max_digits=14, null=True)),
                ('model_used', models.CharField(choices=[('linear', 'Linear Regression'), ('moving_avg', 'Moving Average')], default='linear', max_length=20)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
            ],
            options={
                'ordering': ['forecast_month'],
            },
        ),
        migrations.CreateModel(
            name='BillingRecord',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('organization_name', models.CharField(db_index=True, max_length=255)),
                ('provider', models.CharField(choices=[('aws', 'AWS'), ('gcp', 'GCP'), ('azure', 'Azure')], max_length=20)),
                ('service', models.CharField(max_length=100)),
                ('region', models.CharField(blank=True, default='', max_length=50)),
                ('cost', models.DecimalField(decimal_places=6, max_digits=14)),
                ('usage_quantity', models.DecimalField(blank=True, decimal_places=6, max_digits=14, null=True)),
                ('usage_unit', models.CharField(blank=True, default='', max_length=50)),
                ('recorded_at', models.DateField()),
                ('created_at', models.DateTimeField(auto_now_add=True)),
            ],
            options={
                'ordering': ['-recorded_at'],
            },
        ),
    ]
