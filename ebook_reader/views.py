from django.core.exceptions import PermissionDenied
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.middleware.csrf import get_token

from ebook_reader.models import EbookDocument, EbookLesson, EbookReadingProgress
from ebook_reader.services.feature_flags import (
    can_user_access_new_ebook,
    is_staff_user,
    is_web_reader_available,
    staff_only_enabled,
    web_reader_globally_enabled,
)


def health_check(request):
    return JsonResponse({"status": "ok", "app": "ebook_reader"})


def web_reader(request, ebook_id):
    """Parallel beta web reader for verified ebook lessons and protected PDFs."""

    if not web_reader_globally_enabled():
        raise Http404("The beta ebook reader is disabled.")
    if staff_only_enabled() and not _is_staff(request):
        raise PermissionDenied("The beta ebook reader is available to staff only.")

    ebook = _get_readable_ebook(request, ebook_id)
    lessons = list(_verified_lessons(ebook))
    total_pages = ebook.total_pdf_pages or _fallback_total_pages(lessons)
    explicit_page = "page" in request.GET
    initial_page = _page_from_request(request, total_pages)
    if not explicit_page:
        saved_page = _saved_progress_page(request, ebook)
        if saved_page:
            initial_page = _page_from_value(saved_page, total_pages)
    current_lesson = _lesson_for_page(lessons, initial_page, total_pages)

    return render(
        request,
        "ebook_reader/web/reader.html",
        {
            "ebook": ebook,
            "book": ebook.book,
            "lessons": lessons,
            "current_lesson": current_lesson,
            "initial_page": initial_page,
            "total_pages": total_pages,
            "reader_payload": _reader_payload(
                request,
                ebook=ebook,
                lessons=lessons,
                initial_page=initial_page,
                total_pages=total_pages,
            ),
        },
    )


def user_can_preview_reader(request, ebook_document):
    return is_web_reader_available(ebook_document, request.user) and _user_can_access_ebook(
        request,
        ebook_document,
    )


def _get_readable_ebook(request, ebook_id):
    ebook = get_object_or_404(
        EbookDocument.objects.select_related("book", "book__category"),
        id=ebook_id,
    )
    if not is_web_reader_available(ebook, request.user):
        raise Http404("The beta ebook reader is not enabled for this ebook.")
    if not _user_can_access_ebook(request, ebook):
        if ebook.status != EbookDocument.Status.READY:
            raise Http404("Ebook is not ready.")
        raise PermissionDenied("You do not have access to this ebook.")
    if not ebook.book.pdf_file:
        raise Http404("PDF file is not available.")
    return ebook


def _user_can_access_ebook(request, ebook):
    return can_user_access_new_ebook(ebook, request.user)


def _staff_only_enabled():
    return staff_only_enabled()


def _is_staff(request):
    return is_staff_user(request.user)


def _verified_lessons(ebook):
    return EbookLesson.objects.filter(
        ebook=ebook,
        is_verified=True,
        start_page__isnull=False,
    ).order_by("order", "id")


def _fallback_total_pages(lessons):
    pages = [lesson.end_page or lesson.start_page for lesson in lessons if lesson.start_page]
    return max(pages) if pages else 1


def _page_from_request(request, total_pages):
    return _page_from_value(request.GET.get("page"), total_pages)


def _page_from_value(raw_page, total_pages):
    try:
        page = int(raw_page) if raw_page else 1
    except (TypeError, ValueError):
        return 1
    if page < 1:
        return 1
    if total_pages and page > total_pages:
        return total_pages
    return page


def _lesson_for_page(lessons, page, total_pages):
    for index, lesson in enumerate(lessons):
        next_lesson = lessons[index + 1] if index + 1 < len(lessons) else None
        start_page = lesson.start_page or 1
        end_page = lesson.end_page
        if end_page is None and next_lesson and next_lesson.start_page:
            end_page = next_lesson.start_page - 1
        if end_page is None:
            end_page = total_pages
        if start_page <= page <= end_page:
            return lesson
    return None


def _reader_payload(request, *, ebook, lessons, initial_page, total_pages):
    lesson_payload = []
    for index, lesson in enumerate(lessons):
        next_lesson = lessons[index + 1] if index + 1 < len(lessons) else None
        derived_end_page = lesson.end_page
        if derived_end_page is None and next_lesson and next_lesson.start_page:
            derived_end_page = next_lesson.start_page - 1
        lesson_payload.append(
            {
                "id": lesson.id,
                "order": lesson.order,
                "title": lesson.title,
                "start_page": lesson.start_page,
                "end_page": lesson.end_page,
                "active_end_page": derived_end_page or total_pages,
                "printed_page_number": lesson.printed_page_number,
            }
        )

    return {
        "ebookId": ebook.id,
        "title": ebook.book.title,
        "initialPage": initial_page,
        "totalPages": total_pages,
        "lessons": lesson_payload,
        "pdfUrl": request.build_absolute_uri(reverse("ebook_v1_pdf_access", args=[ebook.id])),
        "progressUrl": request.build_absolute_uri(reverse("ebook_v1_progress", args=[ebook.id])),
        "csrfToken": get_token(request),
        "lessonsUrl": request.build_absolute_uri(reverse("ebook_v1_lessons", args=[ebook.id])),
        "readerConfigUrl": request.build_absolute_uri(reverse("ebook_v1_reader_config", args=[ebook.id])),
    }


def _saved_progress_page(request, ebook):
    if not (request.user and request.user.is_authenticated):
        return None
    progress = EbookReadingProgress.objects.filter(
        user=request.user,
        ebook_document=ebook,
    ).only("current_page").first()
    return progress.current_page if progress else None
