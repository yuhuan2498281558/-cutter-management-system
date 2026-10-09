from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('shield', '0041_stratumbasicinfo_stratum_type_ratios')]
    operations = [
        migrations.AddField(
            model_name='stratumbasicinfo',
            name='longitudinal_type_ratios',
            field=models.JSONField(blank=True, default=dict, verbose_name='longitudinal-section area percentages'),
        ),
    ]
