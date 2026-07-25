from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import F, Q


class EbookDocument(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        PROCESSING = "processing", "Processing"
        REVIEW_REQUIRED = "review_required", "Review required"
        READY = "ready", "Ready"
        FAILED = "failed", "Failed"

    class TocMode(models.TextChoices):
        AUTO = "auto", "Auto detect"
        MANUAL = "manual", "Manual page range"
        NONE = "none", "No TOC"

    class PageMappingMode(models.TextChoices):
        AUTO = "auto", "Auto"
        MANUAL_OFFSET = "manual_offset", "Manual offset"
        MANUAL_ANCHORS = "manual_anchors", "Manual anchors"
        NONE = "none", "No printed page mapping"

    class PageMappingStatus(models.TextChoices):
        NOT_CHECKED = "not_checked", "Not checked"
        DETECTED = "detected", "Detected"
        REVIEW_REQUIRED = "review_required", "Review required"
        ACCEPTED = "accepted", "Accepted"
        FAILED = "failed", "Failed"

    book = models.OneToOneField(
        "library.Book",
        on_delete=models.CASCADE,
        related_name="ebook_document",
    )
    status = models.CharField(
        max_length=24,
        choices=Status.choices,
        default=Status.PENDING,
    )
    new_ebook_reader_enabled = models.BooleanField(default=False)
    new_ebook_reader_web_enabled = models.BooleanField(default=False)
    new_ebook_reader_mobile_enabled = models.BooleanField(default=False)
    toc_mode = models.CharField(
        max_length=12,
        choices=TocMode.choices,
        default=TocMode.AUTO,
    )
    toc_start_page = models.PositiveIntegerField(null=True, blank=True)
    toc_end_page = models.PositiveIntegerField(null=True, blank=True)
    detected_toc_start_page = models.PositiveIntegerField(null=True, blank=True)
    detected_toc_end_page = models.PositiveIntegerField(null=True, blank=True)
    toc_detection_confidence = models.FloatField(null=True, blank=True)
    toc_detection_metadata = models.JSONField(default=dict, blank=True)
    toc_scan_page_limit = models.PositiveIntegerField(null=True, blank=True)
    total_pdf_pages = models.PositiveIntegerField(null=True, blank=True)
    page_mapping_mode = models.CharField(
        max_length=20,
        choices=PageMappingMode.choices,
        default=PageMappingMode.AUTO,
    )
    page_number_offset = models.IntegerField(null=True, blank=True)
    detected_page_number_offset = models.IntegerField(null=True, blank=True)
    page_mapping_confidence = models.FloatField(null=True, blank=True)
    page_mapping_metadata = models.JSONField(default=dict, blank=True)
    page_mapping_status = models.CharField(
        max_length=20,
        choices=PageMappingStatus.choices,
        default=PageMappingStatus.NOT_CHECKED,
    )
    processing_error = models.TextField(blank=True)
    processing_metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("book__title", "id")
        indexes = [
            models.Index(fields=["status"], name="ebook_doc_status_idx"),
            models.Index(
                fields=["status", "new_ebook_reader_enabled"],
                name="ebook_doc_enabled_idx",
            ),
            models.Index(fields=["book", "status"], name="ebook_doc_book_status_idx"),
            models.Index(fields=["updated_at"], name="ebook_doc_updated_idx"),
            models.Index(fields=["toc_mode"], name="ebook_doc_toc_mode_idx"),
            models.Index(
                fields=["page_mapping_status"],
                name="ebook_doc_map_status_idx",
            ),
            models.Index(
                fields=["page_mapping_mode"],
                name="ebook_doc_map_mode_idx",
            ),
        ]
        constraints = [
            models.CheckConstraint(
                check=Q(toc_end_page__isnull=True)
                | Q(
                    toc_start_page__isnull=False,
                    toc_end_page__gte=F("toc_start_page"),
                ),
                name="ebook_doc_toc_end_gte_start",
            ),
            models.CheckConstraint(
                check=Q(detected_toc_end_page__isnull=True)
                | Q(
                    detected_toc_start_page__isnull=False,
                    detected_toc_end_page__gte=F("detected_toc_start_page"),
                ),
                name="ebook_doc_detected_toc_end_gte_start",
            ),
        ]

    def clean(self):
        super().clean()
        self._validate_page_range(
            "toc_start_page",
            "toc_end_page",
            self.toc_start_page,
            self.toc_end_page,
            require_complete=self.toc_mode == self.TocMode.MANUAL,
        )
        self._validate_page_range(
            "detected_toc_start_page",
            "detected_toc_end_page",
            self.detected_toc_start_page,
            self.detected_toc_end_page,
            require_complete=False,
        )
        if (
            self.page_mapping_mode == self.PageMappingMode.MANUAL_OFFSET
            and self.page_number_offset is None
        ):
            raise ValidationError(
                {"page_number_offset": "Manual offset is required in manual offset mode."}
            )

    def _validate_page_range(
        self,
        start_field,
        end_field,
        start_page,
        end_page,
        *,
        require_complete,
    ):
        errors = {}
        if require_complete and start_page is None:
            errors[start_field] = "Start page is required for manual TOC mode."
        if require_complete and end_page is None:
            errors[end_field] = "End page is required for manual TOC mode."
        if end_page is not None and start_page is None:
            errors[start_field] = "Start page is required when end page is set."
        if start_page is not None and end_page is not None and end_page < start_page:
            errors[end_field] = "End page must be greater than or equal to start page."

        total_pages = self.total_pdf_pages
        if total_pages:
            if start_page is not None and start_page > total_pages:
                errors[start_field] = "Start page cannot be greater than total PDF pages."
            if end_page is not None and end_page > total_pages:
                errors[end_field] = "End page cannot be greater than total PDF pages."

        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return f"Ebook document for {self.book}"


class EbookPageMappingAnchor(models.Model):
    ebook = models.ForeignKey(
        EbookDocument,
        on_delete=models.CASCADE,
        related_name="page_mapping_anchors",
    )
    printed_page_number = models.PositiveIntegerField()
    physical_pdf_page = models.PositiveIntegerField()
    note = models.CharField(max_length=255, blank=True)
    is_verified = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("ebook", "printed_page_number", "physical_pdf_page", "id")
        indexes = [
            models.Index(
                fields=["ebook", "printed_page_number"],
                name="ebook_map_anchor_print_idx",
            ),
            models.Index(
                fields=["ebook", "physical_pdf_page"],
                name="ebook_map_anchor_phys_idx",
            ),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["ebook", "printed_page_number", "physical_pdf_page"],
                name="unique_page_mapping_anchor",
            ),
            models.CheckConstraint(
                check=Q(printed_page_number__gte=1),
                name="ebook_map_anchor_print_gte_1",
            ),
            models.CheckConstraint(
                check=Q(physical_pdf_page__gte=1),
                name="ebook_map_anchor_phys_gte_1",
            ),
        ]

    def clean(self):
        super().clean()
        total_pages = self.ebook.total_pdf_pages if self.ebook_id else None
        if total_pages and self.physical_pdf_page > total_pages:
            raise ValidationError(
                {"physical_pdf_page": "Physical PDF page cannot exceed total PDF pages."}
            )

    @property
    def offset(self):
        return self.physical_pdf_page - self.printed_page_number

    def __str__(self):
        return (
            f"{self.ebook}: printed page {self.printed_page_number} -> "
            f"PDF page {self.physical_pdf_page}"
        )


class EbookProcessingRun(models.Model):
    class Status(models.TextChoices):
        PROCESSING = "processing", "Processing"
        COMPLETED = "completed", "Completed"
        SKIPPED = "skipped", "Skipped"
        FAILED = "failed", "Failed"

    ebook_document = models.ForeignKey(
        EbookDocument,
        on_delete=models.CASCADE,
        related_name="processing_runs",
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PROCESSING,
    )
    started_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    extraction_engine = models.CharField(max_length=120, blank=True)
    parser_version = models.CharField(max_length=40, blank=True)
    mapping_strategy = models.CharField(max_length=120, blank=True)
    valid_count = models.PositiveIntegerField(default=0)
    invalid_count = models.PositiveIntegerField(default=0)
    unclassified_count = models.PositiveIntegerField(default=0)
    diagnostics = models.JSONField(default=dict, blank=True)
    error_message = models.TextField(blank=True)

    class Meta:
        ordering = ("-started_at", "-id")
        indexes = [
            models.Index(
                fields=["ebook_document", "status"],
                name="ebook_run_doc_status_idx",
            ),
            models.Index(fields=["started_at"], name="ebook_run_started_idx"),
        ]

    def __str__(self):
        return f"{self.ebook_document}: {self.status} at {self.started_at}"


class EbookLesson(models.Model):
    ebook = models.ForeignKey(
        EbookDocument,
        on_delete=models.CASCADE,
        related_name="lessons",
    )
    order = models.PositiveIntegerField(null=True, blank=True)
    title = models.CharField(max_length=255)
    printed_page_number = models.PositiveIntegerField(null=True, blank=True)
    start_page = models.PositiveIntegerField(null=True, blank=True)
    end_page = models.PositiveIntegerField(null=True, blank=True)
    source_toc_page = models.PositiveIntegerField(null=True, blank=True)
    confidence = models.FloatField(null=True, blank=True)
    parser_strategy = models.CharField(max_length=120, blank=True)
    warnings = models.JSONField(default=list, blank=True)
    is_verified = models.BooleanField(default=False)
    verified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="verified_ebook_lessons",
        null=True,
        blank=True,
    )
    verified_at = models.DateTimeField(null=True, blank=True)
    is_manually_edited = models.BooleanField(default=False)
    processing_run = models.ForeignKey(
        EbookProcessingRun,
        on_delete=models.SET_NULL,
        related_name="lessons",
        null=True,
        blank=True,
    )
    raw_ocr_text = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("ebook", "order", "id")
        indexes = [
            models.Index(fields=["ebook", "order"], name="ebook_lesson_order_idx"),
            models.Index(fields=["ebook", "start_page"], name="ebook_lesson_start_idx"),
            models.Index(
                fields=["ebook", "is_verified"],
                name="ebook_lesson_verified_idx",
            ),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["ebook", "order"],
                name="unique_lesson_order_per_ebook",
            ),
            models.CheckConstraint(
                check=Q(start_page__isnull=True) | Q(start_page__gte=1),
                name="ebook_lesson_start_page_gte_1",
            ),
            models.CheckConstraint(
                check=Q(end_page__isnull=True)
                | Q(
                    start_page__isnull=False,
                    end_page__gte=F("start_page"),
                ),
                name="ebook_lesson_end_page_gte_start",
            ),
        ]

    def clean(self):
        super().clean()
        if self.start_page is not None and self.start_page < 1:
            raise ValidationError(
                {"start_page": "Start page must be greater than or equal to 1."}
            )
        if self.end_page is not None and self.start_page is None:
            raise ValidationError(
                {"start_page": "Start page is required when end page is set."}
            )
        if self.end_page is not None and self.end_page < self.start_page:
            raise ValidationError(
                {"end_page": "End page must be greater than or equal to start page."}
            )

    def __str__(self):
        return f"{self.ebook}: {self.order}. {self.title}"


class EbookReadingProgress(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="ebook_reading_progress",
    )
    ebook_document = models.ForeignKey(
        EbookDocument,
        on_delete=models.CASCADE,
        related_name="reading_progress",
    )
    current_page = models.PositiveIntegerField()
    current_lesson = models.ForeignKey(
        EbookLesson,
        on_delete=models.SET_NULL,
        related_name="reading_progress",
        null=True,
        blank=True,
    )
    percentage = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
    )
    started_at = models.DateTimeField(null=True, blank=True)
    last_read_at = models.DateTimeField()
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-last_read_at", "-id")
        constraints = [
            models.UniqueConstraint(
                fields=["user", "ebook_document"],
                name="unique_ebook_progress_per_user",
            ),
            models.CheckConstraint(
                check=Q(current_page__gte=1),
                name="ebook_progress_current_page_gte_1",
            ),
        ]
        indexes = [
            models.Index(
                fields=["user", "ebook_document"],
                name="ebook_progress_user_doc_idx",
            ),
            models.Index(fields=["last_read_at"], name="ebook_progress_last_read_idx"),
        ]

    def __str__(self):
        return f"{self.user} - {self.ebook_document} - page {self.current_page}"


class EbookTocCandidate(models.Model):
    class CandidateType(models.TextChoices):
        INVALID = "invalid", "Invalid"
        UNCLASSIFIED = "unclassified", "Unclassified"

    ebook_document = models.ForeignKey(
        EbookDocument,
        on_delete=models.CASCADE,
        related_name="toc_candidates",
    )
    processing_run = models.ForeignKey(
        EbookProcessingRun,
        on_delete=models.CASCADE,
        related_name="toc_candidates",
    )
    candidate_type = models.CharField(max_length=20, choices=CandidateType.choices)
    order = models.PositiveIntegerField(null=True, blank=True)
    title = models.CharField(max_length=255, blank=True)
    printed_page_number = models.PositiveIntegerField(null=True, blank=True)
    proposed_pdf_page = models.PositiveIntegerField(null=True, blank=True)
    source_toc_page = models.PositiveIntegerField(null=True, blank=True)
    parser_strategy = models.CharField(max_length=120, blank=True)
    raw_source_text = models.TextField(blank=True)
    confidence = models.FloatField(null=True, blank=True)
    warnings = models.JSONField(default=list, blank=True)
    validation_errors = models.JSONField(default=list, blank=True)
    diagnostics = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("ebook_document", "source_toc_page", "id")
        indexes = [
            models.Index(
                fields=["ebook_document", "candidate_type"],
                name="ebook_toc_cand_type_idx",
            ),
            models.Index(
                fields=["processing_run", "candidate_type"],
                name="ebook_toc_cand_run_idx",
            ),
        ]

    def __str__(self):
        return f"{self.ebook_document}: {self.candidate_type} TOC candidate"
