from dataclasses import dataclass

from django.db.models import Count, Q

from ebook_reader.models import EbookDocument, EbookLesson
from ebook_reader.services.pdf_metadata import EbookPdfError, inspect_pdf_metadata
from ebook_reader.services.toc_parser import resolve_effective_toc_range
from ebook_reader.services.toc_processing import process_ebook_toc


LOW_CONFIDENCE = 0.55


@dataclass(frozen=True)
class ReadyEligibility:
    eligible: bool
    reasons: list[str]


def review_header_context(ebook_document: EbookDocument) -> dict:
    lesson_qs = ebook_document.lessons.all()
    candidate_qs = ebook_document.toc_candidates.all()
    last_run = ebook_document.processing_runs.order_by("-started_at", "-id").first()
    start, end, range_warnings = resolve_effective_toc_range(ebook_document)
    return {
        "book_title": ebook_document.book.title,
        "ebook_id": ebook_document.id,
        "status": ebook_document.status,
        "toc_mode": ebook_document.toc_mode,
        "effective_toc_range": _format_range(start, end),
        "effective_toc_warnings": range_warnings,
        "detected_toc_range": _format_range(
            ebook_document.detected_toc_start_page,
            ebook_document.detected_toc_end_page,
        ),
        "toc_detection_confidence": ebook_document.toc_detection_confidence,
        "page_mapping_mode": ebook_document.page_mapping_mode,
        "page_mapping_confidence": ebook_document.page_mapping_confidence,
        "total_pdf_pages": ebook_document.total_pdf_pages,
        "last_processing_run": last_run,
        "total_candidate_count": candidate_qs.count(),
        "valid_count": lesson_qs.count(),
        "invalid_count": candidate_qs.filter(candidate_type="invalid").count(),
        "unclassified_count": candidate_qs.filter(candidate_type="unclassified").count(),
        "verified_lesson_count": lesson_qs.filter(is_verified=True).count(),
        "low_confidence_count": lesson_qs.filter(
            Q(confidence__lt=LOW_CONFIDENCE) | Q(confidence__isnull=True)
        ).count(),
    }


def lesson_queryset_for_review(ebook_document, *, filter_value="", search=""):
    queryset = ebook_document.lessons.order_by("order", "id")
    if search:
        queryset = queryset.filter(title__icontains=search)
    if filter_value == "low_confidence":
        queryset = queryset.filter(Q(confidence__lt=LOW_CONFIDENCE) | Q(confidence__isnull=True))
    elif filter_value == "unverified":
        queryset = queryset.filter(is_verified=False)
    elif filter_value == "missing_page":
        queryset = queryset.filter(start_page__isnull=True)
    elif filter_value == "manually_edited":
        queryset = queryset.filter(is_manually_edited=True)
    elif filter_value == "duplicate_order":
        duplicate_orders = (
            ebook_document.lessons.exclude(order__isnull=True)
            .values("order")
            .annotate(total=Count("id"))
            .filter(total__gt=1)
            .values_list("order", flat=True)
        )
        queryset = queryset.filter(order__in=list(duplicate_orders))
    elif filter_value == "invalid":
        queryset = queryset.none()
    return queryset


def selected_lesson_ids(post_data):
    ids = []
    for key, value in post_data.items():
        if key.endswith("-selected") and value == "on":
            prefix = key.rsplit("-", 1)[0]
            lesson_id = post_data.get(f"{prefix}-id")
            if lesson_id and lesson_id.isdigit():
                ids.append(int(lesson_id))
    return ids


def mark_lessons_verified(ebook_document, lesson_ids, user):
    queryset = _owned_lessons(ebook_document, lesson_ids)
    updated = 0
    skipped = 0
    for lesson in queryset:
        errors = validation_errors_for_lesson(lesson, ebook_document)
        if errors:
            skipped += 1
            continue
        lesson.is_verified = True
        lesson.verified_by = user
        from django.utils import timezone

        lesson.verified_at = timezone.now()
        lesson.save(update_fields=["is_verified", "verified_by", "verified_at", "updated_at"])
        updated += 1
    return updated, skipped


def mark_all_valid_verified(ebook_document, user):
    ids = list(ebook_document.lessons.values_list("id", flat=True))
    return mark_lessons_verified(ebook_document, ids, user)


def unverify_lessons(ebook_document, lesson_ids):
    return _owned_lessons(ebook_document, lesson_ids).update(
        is_verified=False,
        verified_by=None,
        verified_at=None,
    )


def delete_draft_lessons(ebook_document, lesson_ids):
    queryset = _owned_lessons(ebook_document, lesson_ids).filter(
        is_verified=False,
        is_manually_edited=False,
    )
    count = queryset.count()
    queryset.delete()
    return count


def accept_detected_range_for_document(ebook_document):
    if not ebook_document.detected_toc_start_page or not ebook_document.detected_toc_end_page:
        return False
    ebook_document.toc_mode = EbookDocument.TocMode.MANUAL
    ebook_document.toc_start_page = ebook_document.detected_toc_start_page
    ebook_document.toc_end_page = ebook_document.detected_toc_end_page
    ebook_document.full_clean()
    ebook_document.save(
        update_fields=["toc_mode", "toc_start_page", "toc_end_page", "updated_at"]
    )
    return True


def rerun_processing(ebook_document, *, force=False):
    return process_ebook_toc(ebook_document.id, force=force)


def ready_eligibility(ebook_document) -> ReadyEligibility:
    reasons = []
    lessons = list(ebook_document.lessons.all())
    if not lessons:
        reasons.append("At least one lesson is required.")
    duplicate_orders = _duplicate_orders(lessons)
    if duplicate_orders:
        reasons.append(f"Duplicate lesson order(s): {', '.join(map(str, duplicate_orders))}.")
    for lesson in lessons:
        reasons.extend(validation_errors_for_lesson(lesson, ebook_document))
        if not lesson.is_verified:
            reasons.append(f"Lesson {lesson.id} is not verified.")
    try:
        inspect_pdf_metadata(ebook_document)
    except EbookPdfError as error:
        reasons.append(f"PDF is not readable: {error.message}")
    if ebook_document.page_mapping_mode != EbookDocument.PageMappingMode.NONE:
        if (
            ebook_document.page_mapping_status != EbookDocument.PageMappingStatus.ACCEPTED
            and ebook_document.page_mapping_mode == EbookDocument.PageMappingMode.AUTO
        ):
            reasons.append("Page mapping must be accepted or manually configured.")
    return ReadyEligibility(eligible=not reasons, reasons=reasons)


def validation_errors_for_lesson(lesson, ebook_document):
    errors = []
    if not (lesson.title or "").strip():
        errors.append(f"Lesson {lesson.id} title is blank.")
    if lesson.start_page is None:
        errors.append(f"Lesson {lesson.id} has no physical PDF start page.")
    elif ebook_document.total_pdf_pages and lesson.start_page > ebook_document.total_pdf_pages:
        errors.append(f"Lesson {lesson.id} start page exceeds total PDF pages.")
    if lesson.end_page is not None:
        if lesson.start_page is None or lesson.end_page < lesson.start_page:
            errors.append(f"Lesson {lesson.id} end page is before start page.")
    return errors


def _owned_lessons(ebook_document, lesson_ids):
    return EbookLesson.objects.filter(ebook=ebook_document, id__in=lesson_ids)


def _duplicate_orders(lessons):
    counts = {}
    for lesson in lessons:
        if lesson.order is not None:
            counts[lesson.order] = counts.get(lesson.order, 0) + 1
    return sorted(order for order, count in counts.items() if count > 1)


def _format_range(start, end):
    if start and end:
        return f"{start}-{end}"
    return "-"
