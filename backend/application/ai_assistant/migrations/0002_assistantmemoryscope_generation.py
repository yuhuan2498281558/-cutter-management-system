from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("ai_assistant", "0001_initial")]

    operations = [
        migrations.AddField(
            model_name="assistantmemoryscope",
            name="generation",
            field=models.PositiveBigIntegerField(default=0),
        ),
    ]
