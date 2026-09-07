from django.contrib import admin, messages
from django.urls import reverse
from django.utils.html import format_html
from ebook_reader.models import ContentEdition, ContentPage
from ebook_reader.services.structured_content import _dispatch, queue_content


@admin.register(ContentEdition)
class ContentEditionAdmin(admin.ModelAdmin):
    list_display = ("book", "status", "processed_pages", "total_pages", "review_link", "created_at")
    list_filter = ("status",)
    search_fields = ("book__title",)
    readonly_fields = ("book", "source_file_label", "source_sha256", "engine_version", "status", "total_pages", "processed_pages", "error", "created_at", "published_at", "review_link")
    exclude = ("source_pdf",)
    actions = ("retry_failed", "new_version")

    def has_add_permission(self, request):
        return False

    @admin.display(description="Private source snapshot")
    def source_file_label(self, obj):
        return obj.source_pdf.name

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.display(description="Review")
    def review_link(self, obj):
        return format_html('<a href="{}">Compare and edit pages</a>', reverse("ebook_reader:content_review", args=[obj.pk]))

    @admin.action(description="Retry failed/queued extraction (keeps corrected pages)")
    def retry_failed(self, request, queryset):
        for edition in queryset.filter(status__in=("failed", "queued")):
            edition.status = "queued"
            edition.save(update_fields=("status",))
            _dispatch(edition.pk)
        self.message_user(request, "Queued extraction retries.", messages.SUCCESS)

    @admin.action(description="Extract a NEW draft version from current uploaded PDF")
    def new_version(self, request, queryset):
        for edition in queryset.select_related("book"):
            queue_content(edition.book, new_version=True)
        self.message_user(request, "New draft versions queued. Existing editions are preserved.")


@admin.register(ContentPage)
class ContentPageAdmin(admin.ModelAdmin):
    list_display = ("edition", "page_number", "extraction_method", "reviewed_at", "review_link")
    list_filter = ("edition", "extraction_method", "reviewed_at")
    search_fields = ("plain_text", "edition__book__title")
    readonly_fields = ("edition", "page_number", "layout", "plain_text", "extraction_method", "issues", "reviewed_at", "reviewed_by", "revision", "review_link")

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def review_link(self, obj):
        return format_html('<a href="{}?page={}">Compare and edit</a>', reverse("ebook_reader:content_review", args=[obj.edition_id]), obj.page_number)
