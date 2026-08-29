from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="AppBuildRelease",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("platform", models.CharField(choices=[("android", "Android")], default="android", max_length=20)),
                ("channel", models.CharField(choices=[("testing", "Testing release"), ("play_store", "Play Store release")], default="testing", max_length=30)),
                ("version_name", models.CharField(help_text="Example: 1.0.1", max_length=40)),
                ("version_code", models.PositiveIntegerField(help_text="Android versionCode. Higher number means newer build.")),
                ("title", models.CharField(blank=True, max_length=180)),
                ("release_notes", models.TextField(blank=True)),
                ("artifact_file", models.FileField(blank=True, null=True, upload_to="app_releases/")),
                ("artifact_url", models.URLField(blank=True, help_text="Optional direct APK URL for testing releases.")),
                ("play_store_url", models.URLField(blank=True, help_text="Production Play Store listing URL.")),
                ("is_active", models.BooleanField(default=True)),
                ("is_required", models.BooleanField(default=False)),
                ("rollout_percent", models.PositiveSmallIntegerField(default=100)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "ordering": ("-version_code", "-created_at"),
            },
        ),
        migrations.AddIndex(
            model_name="appbuildrelease",
            index=models.Index(fields=["platform", "channel", "is_active", "-version_code"], name="app_update_lookup_idx"),
        ),
    ]
