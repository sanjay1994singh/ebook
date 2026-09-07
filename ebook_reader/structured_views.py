import copy
import json

import fitz
from django.contrib.admin.views.decorators import staff_member_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST
from django.views.decorators.clickjacking import xframe_options_exempt

from ebook_reader.models import ContentEdition, ContentPage
from ebook_reader.services.structured_content import layout_text, publish_edition
from ebook_reader.services.structured_extraction import validate_layout
from library.models import Book


def published_edition(book_id):
    return ContentEdition.objects.filter(book_id=book_id, book__is_published=True, status="published").first()


def _edition(request, edition_id):
    query = ContentEdition.objects.select_related("book")
    if not (request.user.is_active and request.user.is_staff and request.user.has_perm("ebook_reader.view_contentpage")):
        query = query.filter(status="published", book__is_published=True)
    return get_object_or_404(query, pk=edition_id)


def _response(payload, status=200):
    response = JsonResponse(payload, status=status)
    response["Cache-Control"] = "no-store"
    return response


def manifest(request, book_id):
    book = get_object_or_404(Book, pk=book_id, is_published=True)
    edition = published_edition(book.pk)
    if not edition:
        return _response({"available": False})
    return _response({"available": True, "edition_id": edition.pk, "total_pages": edition.total_pages,
        "reader_url": request.build_absolute_uri(reverse("ebook_reader:content_reader", args=[book.pk]))})


@xframe_options_exempt
def reader(request, book_id):
    edition = published_edition(book_id)
    if not edition:
        raise Http404("Reviewed content is not published yet.")
    response = render(request, "ebook_reader/content_reader.html", _context(request, edition))
    from django.conf import settings
    from urllib.parse import urlsplit
    origins = []
    for value in getattr(settings, "CONTENT_READER_FRAME_ORIGINS", getattr(settings, "CORS_ALLOWED_ORIGINS", [])):
        parsed = urlsplit(value)
        if parsed.scheme in ("http", "https") and parsed.netloc and not parsed.path and not parsed.query and not parsed.fragment and "'" not in value and ";" not in value:
            origins.append(value)
    response["Content-Security-Policy"] = "frame-ancestors 'self' " + " ".join(origins) + "; object-src 'none'; base-uri 'self'"
    response["Cache-Control"] = "no-store"
    return response


def _context(request, edition, *, review=False):
    try:
        initial = max(1, min(int(request.GET.get("page", 1)), edition.total_pages or 1))
    except (TypeError, ValueError):
        initial = 1
    return {"edition": edition, "review": review, "reader_config": {
        "edition": edition.pk, "book": edition.book_id, "title": edition.book.title,
        "total": edition.total_pages, "initial": initial, "review": review,
        "editable": review and edition.status == "review",
        "page_url": reverse("ebook_reader:content_page", args=[edition.pk, 1]).replace("/pages/1/", "/pages/{page}/"),
        "source_url": reverse("ebook_reader:content_source", args=[edition.pk, 1]).replace("/source/1/", "/source/{page}/"),
        "review_url": reverse("ebook_reader:content_review_save", args=[edition.pk, 1]).replace("/review/1/", "/review/{page}/"),
        "search_url": reverse("ebook_reader:content_search", args=[edition.pk]),
        "publish_url": reverse("ebook_reader:content_publish", args=[edition.pk]),
        "chapters": list(edition.book.chapters.exclude(start_page=None).values("title", "start_page")),
    }}


@staff_member_required
def draft_preview(request, edition_id):
    if not request.user.has_perm("ebook_reader.view_contentpage"):
        raise PermissionDenied
    edition = get_object_or_404(ContentEdition.objects.select_related("book"), pk=edition_id)
    context = _context(request, edition)
    context["draft_preview"] = True
    response = render(request, "ebook_reader/content_reader.html", context)
    response["Cache-Control"] = "private, no-store"
    return response


def page_data(request, edition_id, page_number):
    edition = _edition(request, edition_id)
    page = get_object_or_404(ContentPage, edition=edition, page_number=page_number)
    payload = {"page": page.page_number, "layout": page.layout, "plain_text": page.plain_text}
    if request.user.is_staff:
        payload.update(issues=page.issues, method=page.extraction_method, reviewed=bool(page.reviewed_at), revision=page.revision)
        payload["review_summary"] = review_summary(edition)
    return _response(payload)


def review_summary(edition):
    states = list(edition.pages.values_list("page_number", "reviewed_at"))
    return {"total": edition.total_pages, "approved": sum(reviewed is not None for _, reviewed in states),
        "pending": [number for number, reviewed in states if reviewed is None],
        "available": [number for number, _ in states]}


def search(request, edition_id):
    edition = _edition(request, edition_id)
    query = request.GET.get("q", "").strip()[:120]
    pages = edition.pages.filter(plain_text__icontains=query) if query else edition.pages.none()
    return _response({"results": [{"page": p.page_number, "excerpt": _excerpt(p.plain_text, query)} for p in pages.only("page_number", "plain_text")[:50]]})


def _excerpt(text, query):
    index = text.casefold().find(query.casefold())
    return text[max(0, index - 45):max(0, index - 45) + 180]


@staff_member_required
def review(request, edition_id):
    if not request.user.has_perm("ebook_reader.change_contentpage"):
        raise PermissionDenied
    edition = get_object_or_404(ContentEdition.objects.select_related("book"), pk=edition_id)
    response = render(request, "ebook_reader/content_reader.html", _context(request, edition, review=True))
    response["Cache-Control"] = "no-store"
    return response


@staff_member_required
def source_page(request, edition_id, page_number):
    if not request.user.has_perm("ebook_reader.view_contentpage"):
        raise PermissionDenied
    edition = get_object_or_404(ContentEdition, pk=edition_id)
    if not 1 <= page_number <= edition.total_pages:
        raise Http404
    with edition.source_pdf.open("rb") as source:
        with fitz.open(stream=source.read(), filetype="pdf") as document:
            response = HttpResponse(document[page_number - 1].get_pixmap(dpi=110).tobytes("png"), content_type="image/png")
    response["Cache-Control"] = "private, no-store"
    return response


@staff_member_required
@require_POST
def save_review(request, edition_id, page_number):
    if not request.user.has_perm("ebook_reader.change_contentpage"):
        raise PermissionDenied
    try:
        if len(request.body) > 2_000_000:
            raise ValueError("Page edit is too large.")
        payload = json.loads(request.body)
        with transaction.atomic():
            edition = get_object_or_404(ContentEdition.objects.select_for_update(), pk=edition_id)
            if edition.status != "review":
                return _response({"error": "Only draft editions can be edited. Create a new version to change published content."}, 409)
            page = get_object_or_404(ContentPage.objects.select_for_update(), edition=edition, page_number=page_number)
            if payload.get("revision") != page.revision:
                return _response({"error": "This page changed in another session. Reload before editing."}, 409)
            layout = copy.deepcopy(page.layout)
            # Fonts and generated decoration are immutable; never accept SVG/HTML from the editor.
            layout["lines"] = payload["lines"]
            validate_layout(layout)
            page.layout = layout
            page.plain_text = layout_text(layout)
            page.reviewed_at = timezone.now() if payload.get("approve") is True else None
            page.reviewed_by = request.user if page.reviewed_at else None
            page.revision += 1
            page.save()
        return _response({"saved": True, "reviewed": bool(page.reviewed_at), "revision": page.revision, "review_summary": review_summary(edition)})
    except (ValueError, TypeError, KeyError, AttributeError) as error:
        return _response({"error": str(error)}, 400)


@staff_member_required
@require_POST
def publish(request, edition_id):
    if not request.user.has_perm("ebook_reader.change_contentedition"):
        raise PermissionDenied
    try:
        edition = publish_edition(edition_id)
        return _response({"published": True, "url": reverse("ebook_reader:content_reader", args=[edition.book_id])})
    except ValidationError as error:
        return _response({"error": " ".join(error.messages)}, 400)
