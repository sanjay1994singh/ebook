from django.contrib import admin
from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import path, reverse
from django.utils.html import format_html

from .models import (
    EbookDocument,
    EbookLesson,
    EbookPageMappingAnchor,
    EbookProcessingRun,
    EbookReadingProgress,
    EbookTocCandidate,
)
from .forms import LessonReviewFormSet, PageMappingAnchorFormSet, TocReviewSettingsForm
from .services.admin_actions import mark_ready_when_verified, reset_to_pending
from .services.admin_review import (
    accept_detected_range_for_document,
    delete_draft_lessons,
    lesson_queryset_for_review,
    mark_all_valid_verified,
    mark_lessons_verified,
    ready_eligibility,
    rerun_processing,
    review_header_context,
    selected_lesson_ids,
    unverify_lessons,
)
from .services.page_mapping.estimator import estimate_page_mapping, save_detected_mapping
from .services.page_mapping.models import PageNumberSample
from .services.toc_detection.admin_workflow import (
    accept_detected_toc_range,
    mark_as_no_toc,
    run_toc_detection,
    switch_to_manual_mode,
)
from .services.toc_processing import process_ebook_toc
from .tasks import inspect_ebook_document


class EbookLessonInline(admin.TabularInline):
    model = EbookLesson
    extra = 0
    fields = (
        "order",
        "title",
        "start_page",
        "end_page",
        "confidence",
        "is_verified",
    )


class EbookPageMappingAnchorInline(admin.TabularInline):
    model = EbookPageMappingAnchor
    extra = 0
    fields = (
        "printed_page_number",
        "physical_pdf_page",
        "is_verified",
        "note",
    )


@admin.register(EbookReadingProgress)
class EbookReadingProgressAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "ebook_document",
        "current_page",
        "current_lesson",
        "percentage",
        "last_read_at",
        "completed_at",
    )
    list_filter = ("completed_at", "last_read_at")
    search_fields = (
        "user__username",
        "user__email",
        "ebook_document__book__title",
    )
    raw_id_fields = ("user", "ebook_document", "current_lesson")
    readonly_fields = ("created_at", "updated_at")


@admin.register(EbookDocument)
class EbookDocumentAdmin(admin.ModelAdmin):
    list_display = (
        "book",
        "status",
        "new_ebook_reader_enabled",
        "new_ebook_reader_web_enabled",
        "new_ebook_reader_mobile_enabled",
        "toc_mode",
        "total_pdf_pages",
        "manual_toc_range",
        "detected_toc_range",
        "toc_detection_confidence",
        "page_mapping_mode",
        "page_mapping_status",
        "page_number_offset",
        "detected_page_number_offset",
        "page_mapping_confidence",
        "lesson_count",
        "verified_lesson_count",
        "updated_at",
        "review_toc_link",
    )
    list_filter = (
        "status",
        "new_ebook_reader_enabled",
        "new_ebook_reader_web_enabled",
        "new_ebook_reader_mobile_enabled",
        "toc_mode",
        "page_mapping_mode",
        "page_mapping_status",
    )
    readonly_fields = (
        "detected_toc_start_page",
        "detected_toc_end_page",
        "toc_detection_confidence",
        "toc_detection_metadata",
        "detected_page_number_offset",
        "page_mapping_confidence",
        "page_mapping_metadata",
        "mapped_page_preview",
        "created_at",
        "updated_at",
    )
    search_fields = ("book__title", "book__slug")
    autocomplete_fields = ("book",)
    inlines = (EbookPageMappingAnchorInline, EbookLessonInline)
    actions = (
        "inspect_selected_ebook_pdfs",
        "run_selected_toc_detection",
        "accept_selected_detected_toc_range",
        "switch_selected_to_manual",
        "mark_selected_as_no_toc",
        "estimate_selected_page_mapping",
        "accept_selected_detected_page_mapping",
        "mark_selected_mapping_as_none",
        "process_or_refresh_selected_tocs",
        "mark_selected_ready",
        "reset_selected_pending",
    )

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        return queryset.select_related("book").annotate(
            lesson_total=Count("lessons", distinct=True),
            verified_lesson_total=Count(
                "lessons",
                filter=Q(lessons__is_verified=True),
                distinct=True,
            ),
        )

    def lesson_count(self, obj):
        return obj.lesson_total

    def verified_lesson_count(self, obj):
        return obj.verified_lesson_total

    def manual_toc_range(self, obj):
        if obj.toc_start_page and obj.toc_end_page:
            return f"{obj.toc_start_page}-{obj.toc_end_page}"
        return "-"

    def detected_toc_range(self, obj):
        if obj.detected_toc_start_page and obj.detected_toc_end_page:
            return f"{obj.detected_toc_start_page}-{obj.detected_toc_end_page}"
        return "-"

    def mapped_page_preview(self, obj):
        if obj.page_number_offset is None:
            return "Configure or accept a page mapping to preview mapped pages."
        examples = []
        for printed_page in (1, 10, 26):
            pdf_page = printed_page + obj.page_number_offset
            if obj.total_pdf_pages and (pdf_page < 1 or pdf_page > obj.total_pdf_pages):
                examples.append(f"printed {printed_page} -> outside PDF ({pdf_page})")
            else:
                examples.append(f"printed {printed_page} -> PDF {pdf_page}")
        return "; ".join(examples)

    def review_toc_link(self, obj):
        url = reverse("admin:ebook_reader_ebookdocument_review_toc", args=[obj.id])
        return format_html('<a class="button" href="{}">Review TOC</a>', url)

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                "<int:object_id>/review-toc/",
                self.admin_site.admin_view(self.review_toc_view),
                name="ebook_reader_ebookdocument_review_toc",
            )
        ]
        return custom_urls + urls

    def review_toc_view(self, request, object_id):
        ebook_document = get_object_or_404(
            EbookDocument.objects.select_related("book"),
            id=object_id,
        )
        if not self.has_change_permission(request, ebook_document):
            from django.core.exceptions import PermissionDenied

            raise PermissionDenied

        if request.method == "POST":
            response = self._handle_review_post(request, ebook_document)
            if response:
                return response

        filter_value = request.GET.get("filter", "")
        search = request.GET.get("q", "")
        queryset = lesson_queryset_for_review(
            ebook_document,
            filter_value=filter_value,
            search=search,
        )
        paginator = Paginator(queryset, 50)
        page_obj = paginator.get_page(request.GET.get("page"))
        formset = LessonReviewFormSet(
            queryset=page_obj.object_list,
            total_pdf_pages=ebook_document.total_pdf_pages,
            request_user=request.user,
            prefix="lessons",
        )
        settings_form = TocReviewSettingsForm(instance=ebook_document, prefix="settings")
        anchor_formset = PageMappingAnchorFormSet(
            queryset=ebook_document.page_mapping_anchors.all(),
            prefix="anchors",
        )
        context = {
            **self.admin_site.each_context(request),
            "opts": self.model._meta,
            "title": "Review ebook TOC",
            "ebook_document": ebook_document,
            "header": review_header_context(ebook_document),
            "ready_eligibility": ready_eligibility(ebook_document),
            "lesson_formset": formset,
            "settings_form": settings_form,
            "anchor_formset": anchor_formset,
            "page_obj": page_obj,
            "filter_value": filter_value,
            "search": search,
            "invalid_candidates": ebook_document.toc_candidates.filter(
                candidate_type=EbookTocCandidate.CandidateType.INVALID
            ).order_by("source_toc_page", "id")[:100],
            "unclassified_candidates": ebook_document.toc_candidates.filter(
                candidate_type=EbookTocCandidate.CandidateType.UNCLASSIFIED
            ).order_by("source_toc_page", "id")[:100],
        }
        return render(request, "admin/ebook_reader/ebookdocument/review_toc.html", context)

    def _handle_review_post(self, request, ebook_document):
        action = request.POST.get("action", "save")
        redirect_url = reverse(
            "admin:ebook_reader_ebookdocument_review_toc",
            args=[ebook_document.id],
        )
        if action == "save":
            return self._save_review_forms(request, ebook_document, redirect_url)

        selected_ids = selected_lesson_ids(request.POST)
        if action == "mark_selected_verified":
            updated, skipped = mark_lessons_verified(ebook_document, selected_ids, request.user)
            self.message_user(request, f"Verified {updated} lesson(s); skipped={skipped}.", messages.SUCCESS)
        elif action == "mark_all_valid_verified":
            updated, skipped = mark_all_valid_verified(ebook_document, request.user)
            self.message_user(request, f"Verified {updated} lesson(s); skipped={skipped}.", messages.SUCCESS)
        elif action == "unverify_selected":
            updated = unverify_lessons(ebook_document, selected_ids)
            self.message_user(request, f"Unverified {updated} lesson(s).", messages.SUCCESS)
        elif action == "delete_selected":
            if request.POST.get("confirm_delete") != "yes":
                self.message_user(request, "Delete requires confirmation.", messages.WARNING)
            else:
                deleted = delete_draft_lessons(ebook_document, selected_ids)
                self.message_user(request, f"Deleted {deleted} draft lesson(s).", messages.SUCCESS)
        elif action == "rerun_processing":
            result = rerun_processing(ebook_document, force=False)
            self.message_user(request, f"Processing result: {result.status}.", messages.SUCCESS)
        elif action == "force_rerun_processing":
            if request.POST.get("confirm_force") != "yes":
                self.message_user(request, "Force re-run requires high-risk confirmation.", messages.ERROR)
            else:
                result = rerun_processing(ebook_document, force=True)
                self.message_user(request, f"Force processing result: {result.status}.", messages.WARNING)
        elif action == "accept_detected_range":
            accepted = accept_detected_range_for_document(ebook_document)
            self.message_user(
                request,
                "Detected TOC range accepted." if accepted else "No detected TOC range to accept.",
                messages.SUCCESS if accepted else messages.WARNING,
            )
        return redirect(redirect_url)

    def _save_review_forms(self, request, ebook_document, redirect_url):
        lesson_qs = lesson_queryset_for_review(
            ebook_document,
            filter_value=request.GET.get("filter", ""),
            search=request.GET.get("q", ""),
        )
        paginator = Paginator(lesson_qs, 50)
        page_obj = paginator.get_page(request.GET.get("page"))
        formset = LessonReviewFormSet(
            request.POST,
            queryset=page_obj.object_list,
            total_pdf_pages=ebook_document.total_pdf_pages,
            request_user=request.user,
            prefix="lessons",
        )
        settings_form = TocReviewSettingsForm(
            request.POST,
            instance=ebook_document,
            prefix="settings",
        )
        anchor_formset = PageMappingAnchorFormSet(
            request.POST,
            queryset=ebook_document.page_mapping_anchors.all(),
            prefix="anchors",
        )
        if formset.is_valid() and settings_form.is_valid() and anchor_formset.is_valid():
            settings_form.save()
            for anchor in anchor_formset.save(commit=False):
                anchor.ebook = ebook_document
                anchor.save()
            for deleted_anchor in anchor_formset.deleted_objects:
                deleted_anchor.delete()
            formset.save()
            self.message_user(request, "TOC review changes saved.", messages.SUCCESS)
            return redirect(redirect_url)

        self.message_user(request, "Please fix the highlighted review errors.", messages.ERROR)
        context = {
            **self.admin_site.each_context(request),
            "opts": self.model._meta,
            "title": "Review ebook TOC",
            "ebook_document": ebook_document,
            "header": review_header_context(ebook_document),
            "ready_eligibility": ready_eligibility(ebook_document),
            "lesson_formset": formset,
            "settings_form": settings_form,
            "anchor_formset": anchor_formset,
            "page_obj": page_obj,
            "filter_value": request.GET.get("filter", ""),
            "search": request.GET.get("q", ""),
            "invalid_candidates": ebook_document.toc_candidates.filter(
                candidate_type=EbookTocCandidate.CandidateType.INVALID
            ).order_by("source_toc_page", "id")[:100],
            "unclassified_candidates": ebook_document.toc_candidates.filter(
                candidate_type=EbookTocCandidate.CandidateType.UNCLASSIFIED
            ).order_by("source_toc_page", "id")[:100],
        }
        return render(request, "admin/ebook_reader/ebookdocument/review_toc.html", context)

    @admin.action(description="Mark selected ebooks as ready when all lessons are verified")
    def mark_selected_ready(self, request, queryset):
        result = mark_ready_when_verified(queryset)
        if result.updated:
            self.message_user(
                request,
                f"{result.updated} ebook document(s) marked ready.",
                messages.SUCCESS,
            )
        if result.skipped:
            self.message_user(
                request,
                (
                    f"{result.skipped} ebook document(s) skipped because they have "
                    "no lessons or unverified lessons."
                ),
                messages.WARNING,
            )

    @admin.action(description="Reset selected ebooks to pending")
    def reset_selected_pending(self, request, queryset):
        updated = reset_to_pending(queryset)
        self.message_user(
            request,
            f"{updated} ebook document(s) reset to pending.",
            messages.SUCCESS,
        )

    @admin.action(description="Inspect selected ebook PDFs")
    def inspect_selected_ebook_pdfs(self, request, queryset):
        queued_count = 0
        for ebook_document_id in queryset.values_list("id", flat=True):
            inspect_ebook_document.delay(ebook_document_id)
            queued_count += 1
        self.message_user(
            request,
            f"{queued_count} ebook PDF inspection task(s) queued.",
            messages.SUCCESS,
        )

    @admin.action(description="Run detection")
    def run_selected_toc_detection(self, request, queryset):
        result = run_toc_detection(queryset)
        self.message_user(
            request,
            f"TOC detection complete. detected={result.detected}, failed={result.failed}, skipped={result.skipped}.",
            messages.SUCCESS if not result.failed else messages.WARNING,
        )

    @admin.action(description="Accept detected range")
    def accept_selected_detected_toc_range(self, request, queryset):
        result = accept_detected_toc_range(queryset)
        self.message_user(
            request,
            f"Accepted detected TOC range for {result.updated} ebook document(s); skipped={result.skipped}.",
            messages.SUCCESS if result.updated else messages.WARNING,
        )

    @admin.action(description="Switch to manual")
    def switch_selected_to_manual(self, request, queryset):
        updated = switch_to_manual_mode(queryset)
        self.message_user(
            request,
            f"{updated} ebook document(s) switched to manual TOC mode.",
            messages.SUCCESS,
        )

    @admin.action(description="Mark as no TOC")
    def mark_selected_as_no_toc(self, request, queryset):
        updated = mark_as_no_toc(queryset)
        self.message_user(
            request,
            f"{updated} ebook document(s) marked as no TOC.",
            messages.SUCCESS,
        )

    @admin.action(description="Estimate page mapping from stored samples")
    def estimate_selected_page_mapping(self, request, queryset):
        detected = failed = skipped = 0
        for ebook_document in queryset.prefetch_related("page_mapping_anchors"):
            samples = _samples_from_metadata(ebook_document.page_mapping_metadata)
            result = estimate_page_mapping(ebook_document, samples)
            save_detected_mapping(ebook_document, result)
            if result.status == "detected":
                detected += 1
            elif result.status == "review_required":
                skipped += 1
            else:
                failed += 1
        self.message_user(
            request,
            f"Page mapping estimation complete. detected={detected}, review_required={skipped}, failed={failed}.",
            messages.SUCCESS if not failed else messages.WARNING,
        )

    @admin.action(description="Accept detected page mapping")
    def accept_selected_detected_page_mapping(self, request, queryset):
        updated = skipped = 0
        for ebook_document in queryset:
            if ebook_document.detected_page_number_offset is None:
                skipped += 1
                continue
            ebook_document.page_mapping_mode = EbookDocument.PageMappingMode.MANUAL_OFFSET
            ebook_document.page_number_offset = ebook_document.detected_page_number_offset
            ebook_document.page_mapping_status = EbookDocument.PageMappingStatus.ACCEPTED
            ebook_document.save(
                update_fields=[
                    "page_mapping_mode",
                    "page_number_offset",
                    "page_mapping_status",
                    "updated_at",
                ]
            )
            updated += 1
        self.message_user(
            request,
            f"Accepted detected page mapping for {updated} ebook document(s); skipped={skipped}.",
            messages.SUCCESS if updated else messages.WARNING,
        )

    @admin.action(description="Mark page mapping as none")
    def mark_selected_mapping_as_none(self, request, queryset):
        updated = queryset.update(
            page_mapping_mode=EbookDocument.PageMappingMode.NONE,
            page_mapping_status=EbookDocument.PageMappingStatus.ACCEPTED,
        )
        self.message_user(
            request,
            f"{updated} ebook document(s) marked as having no printed page mapping.",
            messages.SUCCESS,
        )

    @admin.action(description="Process or refresh selected ebook TOCs")
    def process_or_refresh_selected_tocs(self, request, queryset):
        processed = failed = skipped = 0
        for ebook_document_id in queryset.values_list("id", flat=True):
            result = process_ebook_toc(ebook_document_id)
            if result.status == "failed":
                failed += 1
            elif result.status == "skipped":
                skipped += 1
            else:
                processed += 1
        self.message_user(
            request,
            f"TOC processing complete. processed={processed}, skipped={skipped}, failed={failed}.",
            messages.SUCCESS if not failed else messages.WARNING,
        )


@admin.register(EbookLesson)
class EbookLessonAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "ebook",
        "order",
        "start_page",
        "end_page",
        "confidence",
        "is_verified",
    )
    list_filter = ("is_verified", "ebook__status")
    readonly_fields = ("created_at", "updated_at")
    search_fields = ("title", "ebook__book__title")
    autocomplete_fields = ("ebook",)


@admin.register(EbookPageMappingAnchor)
class EbookPageMappingAnchorAdmin(admin.ModelAdmin):
    list_display = (
        "ebook",
        "printed_page_number",
        "physical_pdf_page",
        "is_verified",
        "updated_at",
    )
    list_filter = ("is_verified",)
    search_fields = ("ebook__book__title", "note")
    autocomplete_fields = ("ebook",)
    readonly_fields = ("created_at", "updated_at")


@admin.register(EbookProcessingRun)
class EbookProcessingRunAdmin(admin.ModelAdmin):
    list_display = (
        "ebook_document",
        "status",
        "parser_version",
        "mapping_strategy",
        "valid_count",
        "invalid_count",
        "unclassified_count",
        "started_at",
        "completed_at",
    )
    list_filter = ("status", "parser_version", "mapping_strategy")
    search_fields = ("ebook_document__book__title", "error_message")
    autocomplete_fields = ("ebook_document",)
    readonly_fields = (
        "started_at",
        "completed_at",
        "diagnostics",
        "error_message",
    )


@admin.register(EbookTocCandidate)
class EbookTocCandidateAdmin(admin.ModelAdmin):
    list_display = (
        "ebook_document",
        "candidate_type",
        "order",
        "title",
        "printed_page_number",
        "proposed_pdf_page",
        "source_toc_page",
        "confidence",
    )
    list_filter = ("candidate_type", "parser_strategy")
    search_fields = ("ebook_document__book__title", "title", "raw_source_text")
    autocomplete_fields = ("ebook_document", "processing_run")
    readonly_fields = ("created_at",)


def _samples_from_metadata(metadata):
    samples = []
    for item in (metadata or {}).get("samples", []):
        samples.append(
            PageNumberSample(
                printed_page_number=item.get("printed_page_number"),
                physical_pdf_page=item.get("physical_pdf_page"),
                source=item.get("source", "admin_metadata"),
                confidence=item.get("confidence"),
                evidence=item.get("evidence", []),
            )
        )
    return samples
