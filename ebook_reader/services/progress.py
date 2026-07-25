from decimal import Decimal, ROUND_HALF_UP

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from ebook_reader.models import EbookDocument, EbookLesson, EbookReadingProgress


def resolve_current_lesson(ebook_document, current_page):
    """Find the verified lesson containing a physical PDF page."""

    lessons = list(
        EbookLesson.objects.filter(
            ebook=ebook_document,
            is_verified=True,
            start_page__isnull=False,
        ).order_by("order", "id")
    )
    total_pages = ebook_document.total_pdf_pages or _fallback_total_pages(lessons)
    for index, lesson in enumerate(lessons):
        next_lesson = lessons[index + 1] if index + 1 < len(lessons) else None
        start_page = lesson.start_page or 1
        end_page = lesson.end_page
        if end_page is None and next_lesson and next_lesson.start_page:
            end_page = next_lesson.start_page - 1
        if end_page is None:
            end_page = total_pages
        if start_page <= current_page <= end_page:
            return lesson
    return None


def save_ebook_progress(user, ebook_document, current_page):
    """Create or update reading progress using physical PDF page numbers."""

    validate_progress_page(ebook_document, current_page)
    now = timezone.now()
    percentage = calculate_percentage(ebook_document, current_page)
    current_lesson = resolve_current_lesson(ebook_document, current_page)
    completed_at = now if percentage == Decimal("100.00") else None

    with transaction.atomic():
        progress = (
            EbookReadingProgress.objects.select_for_update()
            .filter(user=user, ebook_document=ebook_document)
            .first()
        )
        if progress is None:
            progress = EbookReadingProgress(
                user=user,
                ebook_document=ebook_document,
                started_at=now,
            )
        progress.current_page = current_page
        progress.current_lesson = current_lesson
        progress.percentage = percentage
        progress.last_read_at = now
        progress.completed_at = completed_at
        progress.save()
    return progress


def validate_progress_page(ebook_document, current_page):
    total_pages = ebook_document.total_pdf_pages
    if current_page < 1:
        raise ValidationError("Current page must be greater than or equal to 1.")
    if total_pages and current_page > total_pages:
        raise ValidationError("Current page is outside this ebook PDF.")


def calculate_percentage(ebook_document, current_page):
    total_pages = ebook_document.total_pdf_pages or current_page
    if total_pages <= 0:
        return None
    value = (Decimal(current_page) / Decimal(total_pages)) * Decimal("100")
    value = min(value, Decimal("100"))
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def progress_payload(progress):
    current_lesson = progress.current_lesson
    return {
        "current_page": progress.current_page,
        "current_lesson": _lesson_summary(current_lesson),
        "percentage": progress.percentage,
        "last_read_at": progress.last_read_at,
        "completed": bool(progress.completed_at),
        "completed_at": progress.completed_at,
    }


def empty_progress_payload(ebook_document):
    return {
        "current_page": None,
        "current_lesson": None,
        "percentage": None,
        "last_read_at": None,
        "completed": False,
        "completed_at": None,
    }


def _lesson_summary(lesson):
    if lesson is None:
        return None
    return {
        "id": lesson.id,
        "order": lesson.order,
        "title": lesson.title,
        "start_page": lesson.start_page,
        "end_page": lesson.end_page,
    }


def _fallback_total_pages(lessons):
    pages = [lesson.end_page or lesson.start_page for lesson in lessons if lesson.start_page]
    return max(pages) if pages else 1
