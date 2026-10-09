from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('shield', '0040_remove_unused_dictionaries')]
    operations = [
        migrations.AddField(
            model_name='stratumbasicinfo',
            name='stratum_type_ratios',
            field=models.JSONField(blank=True, default=dict, verbose_name='cross-section stratum percentages'),
        ),
    ]
