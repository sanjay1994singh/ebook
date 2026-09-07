"""Versioned extracted content, independent of the original PDF reader."""
from django.conf import settings
from django.db import models
from .content_storage import ContentSourceStorage


class ContentEdition(models.Model):
    class Status(models.TextChoices):
        QUEUED = "queued", "Queued"
        PROCESSING = "processing", "Processing"
        REVIEW = "review", "Needs review"
        PUBLISHED = "published", "Published"
        ARCHIVED = "archived", "Archived"
        FAILED = "failed", "Failed"

    book = models.ForeignKey("library.Book", on_delete=models.CASCADE, related_name="content_editions")
    source_pdf = models.FileField(upload_to="content_sources/%Y/%m/", storage=ContentSourceStorage())
    source_sha256 = models.CharField(max_length=64)
    engine_version = models.CharField(max_length=40, default="structured-1")
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.QUEUED)
    total_pages = models.PositiveIntegerField(default=0)
    processed_pages = models.PositiveIntegerField(default=0)
    error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    published_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-id",)
        indexes = [models.Index(fields=("book", "status"), name="content_book_status_idx")]

    def __str__(self):
        return f"{self.book.title} / version {self.pk} / {self.status}"


class ContentPage(models.Model):
    edition = models.ForeignKey(ContentEdition, on_delete=models.CASCADE, related_name="pages")
    page_number = models.PositiveIntegerField()
    layout = models.JSONField(default=dict)
    plain_text = models.TextField(blank=True)
    extraction_method = models.CharField(max_length=32)
    issues = models.JSONField(default=list, blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    revision = models.PositiveIntegerField(default=1)

    class Meta:
        ordering = ("page_number",)
        constraints = [models.UniqueConstraint(fields=("edition", "page_number"), name="content_edition_page_unique")]

    def __str__(self):
        return f"{self.edition.book.title} / page {self.page_number}"
