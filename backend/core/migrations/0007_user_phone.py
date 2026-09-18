from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('core', '0006_alter_user_managers'),
    ]

    operations = [
        migrations.AddField(
            model_name='user',
            name='phone',
            field=models.CharField(blank=True, help_text='E.164 number, e.g. +27821234567', max_length=32),
        ),
    ]
