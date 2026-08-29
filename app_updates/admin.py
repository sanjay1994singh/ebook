from django.contrib import admin

from .models import AppBuildRelease


@admin.register(AppBuildRelease)
class AppBuildReleaseAdmin(admin.ModelAdmin):
    list_display = (
        "version_name",
        "version_code",
        "channel",
        "platform",
        "is_active",
        "is_required",
        "rollout_percent",
        "updated_at",
    )
    list_filter = ("platform", "channel", "is_active", "is_required")
    search_fields = ("version_name", "version_code", "title", "release_notes")
    readonly_fields = ("created_at", "updated_at")
    actions = ("activate_selected_release",)

    @admin.action(description="Activate selected release and deactivate older same-channel builds")
    def activate_selected_release(self, request, queryset):
        for release in queryset.order_by("platform", "channel", "-version_code"):
            release.is_active = True
            release.save(update_fields=["is_active"])
