from django.db import migrations


def keep_latest_active_release(apps, schema_editor):
    AppBuildRelease = apps.get_model("app_updates", "AppBuildRelease")
    active_groups = (
        AppBuildRelease.objects.filter(is_active=True)
        .values_list("platform", "channel")
        .distinct()
    )
    for platform, channel in active_groups:
        releases = AppBuildRelease.objects.filter(
            platform=platform,
            channel=channel,
            is_active=True,
        ).order_by("-version_code", "-created_at", "-id")
        latest = releases.first()
        if latest:
            releases.exclude(pk=latest.pk).update(is_active=False)


class Migration(migrations.Migration):
    dependencies = [
        ("app_updates", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(keep_latest_active_release, migrations.RunPython.noop),
    ]
