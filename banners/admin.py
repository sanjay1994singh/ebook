from django.contrib import admin

from .models import Banner


@admin.register(Banner)
class BannerAdmin(admin.ModelAdmin):
    list_display = ("title", "device", "is_published", "order", "starts_at", "ends_at")
    list_filter = ("device", "is_published")
    search_fields = ("title",)
    prepopulated_fields = {"slug": ("title",)}
    list_editable = ("is_published", "order")
    fieldsets = (
        ("Banner details", {"fields": ("title", "slug", "device", "link_url")}),
        ("Images", {"fields": ("mobile_image", "desktop_image")}),
        ("Publish", {"fields": ("is_published", "order", "starts_at", "ends_at")}),
    )
