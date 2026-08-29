from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("library", "0013_appbuildrelease"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[],
            state_operations=[
                migrations.DeleteModel(name="AppBuildRelease"),
            ],
        ),
    ]
