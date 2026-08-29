from django.db import models


class AppBuildRelease(models.Model):
    PLATFORM_ANDROID = "android"
    PLATFORM_CHOICES = ((PLATFORM_ANDROID, "Android"),)

    CHANNEL_TESTING = "testing"
    CHANNEL_PLAY_STORE = "play_store"
    CHANNEL_CHOICES = (
        (CHANNEL_TESTING, "Testing release"),
        (CHANNEL_PLAY_STORE, "Play Store release"),
    )

    platform = models.CharField(max_length=20, choices=PLATFORM_CHOICES, default=PLATFORM_ANDROID)
    channel = models.CharField(max_length=30, choices=CHANNEL_CHOICES, default=CHANNEL_TESTING)
    version_name = models.CharField(max_length=40, help_text="Example: 1.0.1")
    version_code = models.PositiveIntegerField(help_text="Android versionCode. Higher number means newer build.")
    title = models.CharField(max_length=180, blank=True)
    release_notes = models.TextField(blank=True)
    artifact_file = models.FileField(upload_to="app_releases/", blank=True, null=True)
    artifact_url = models.URLField(blank=True, help_text="Optional direct APK URL for testing releases.")
    play_store_url = models.URLField(blank=True, help_text="Production Play Store listing URL.")
    is_active = models.BooleanField(default=True)
    is_required = models.BooleanField(default=False)
    rollout_percent = models.PositiveSmallIntegerField(default=100)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-version_code", "-created_at")
        indexes = [
            models.Index(fields=["platform", "channel", "is_active", "-version_code"], name="app_update_lookup_idx"),
        ]

    def __str__(self):
        return f"{self.get_channel_display()} {self.version_name} ({self.version_code})"

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if self.is_active:
            AppBuildRelease.objects.filter(
                platform=self.platform,
                channel=self.channel,
                is_active=True,
            ).exclude(pk=self.pk).update(is_active=False)
