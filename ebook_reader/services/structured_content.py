"""Upload snapshots, resumable extraction and explicit publication gates."""
import hashlib
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.db import transaction
from django.utils import timezone

from ebook_reader.models import ContentEdition, ContentPage

ENGINE_VERSION = "structured-3-font-emphasis"


def queue_content(book, *, new_version=False, dispatch=True):
    if not book.pdf_file:
        raise ValidationError("Upload a PDF first.")
    from django.conf import settings
    if book.pdf_file.size > getattr(settings, "EBOOK_MAX_PDF_SIZE_MB", 500) * 1024 * 1024:
        raise ValidationError("PDF exceeds the configured size limit.")
    with book.pdf_file.open("rb") as source:
        data = source.read()
    if len(data) > getattr(settings, "EBOOK_MAX_PDF_SIZE_MB", 500) * 1024 * 1024:
        raise ValidationError("PDF exceeds the configured size limit.")
    digest = hashlib.sha256(data).hexdigest()
    with transaction.atomic():
        # Serialize version creation for this book (also supported by MySQL).
        type(book).objects.select_for_update().get(pk=book.pk)
        edition = None if new_version else ContentEdition.objects.filter(
            book=book, source_sha256=digest, engine_version=ENGINE_VERSION
        ).exclude(status=ContentEdition.Status.ARCHIVED).first()
        if edition is None:
            edition = ContentEdition(book=book, source_sha256=digest, engine_version=ENGINE_VERSION)
            edition.source_pdf.save(f"{book.pk}-{digest[:16]}.pdf", ContentFile(data), save=False)
            edition.save()
        elif edition.status == ContentEdition.Status.FAILED:
            edition.status = ContentEdition.Status.QUEUED
            edition.error = ""
            edition.save(update_fields=("status", "error"))
        if dispatch and edition.status == ContentEdition.Status.QUEUED:
            transaction.on_commit(lambda: _dispatch(edition.pk))
    return edition


def _dispatch(edition_id):
    from ebook_reader.tasks import process_content_edition
    try:
        process_content_edition.delay(edition_id)
    except Exception as error:
        ContentEdition.objects.filter(pk=edition_id, status="queued").update(status="failed", error=f"Queue unavailable: {error}"[:2000])


def process_edition(edition_id):
    from .structured_extraction import extract_pages
    claimed = ContentEdition.objects.filter(pk=edition_id, status__in=("queued", "failed")).update(status="processing", error="")
    if not claimed:
        return "skipped"
    edition = ContentEdition.objects.get(pk=edition_id)
    try:
        with edition.source_pdf.open("rb") as source:
            data = source.read()
        completed = set(edition.pages.values_list("page_number", flat=True))
        for total, number, layout, method, issues in extract_pages(data, skip=completed):
            if number is not None:
                # Existing draft corrections survive retries; new extraction needs a new version.
                ContentPage.objects.get_or_create(edition=edition, page_number=number, defaults={
                    "layout": layout, "plain_text": layout_text(layout),
                    "extraction_method": method, "issues": issues,
                })
            ContentEdition.objects.filter(pk=edition_id).update(total_pages=total, processed_pages=edition.pages.count())
        edition.refresh_from_db()
        if not edition.total_pages or edition.pages.count() != edition.total_pages:
            raise ValidationError("Extraction did not produce every source page.")
        ContentEdition.objects.filter(pk=edition_id).update(status="review")
        return "review"
    except Exception as error:
        ContentEdition.objects.filter(pk=edition_id).update(status="failed", error=str(error)[:4000])
        raise


def layout_text(layout):
    return "\n".join("".join(run["text"] for run in line["runs"]) for line in layout.get("lines", []))


def publish_edition(edition_id, *, allow_unreviewed=False):
    with transaction.atomic():
        initial = ContentEdition.objects.get(pk=edition_id)
        type(initial.book).objects.select_for_update().get(pk=initial.book_id)
        edition = ContentEdition.objects.select_for_update().get(pk=edition_id)
        pages = list(edition.pages.select_for_update().all())
        if edition.status != "review":
            raise ValidationError("Only a reviewed draft can be published.")
        if not edition.total_pages or [p.page_number for p in pages] != list(range(1, edition.total_pages + 1)):
            raise ValidationError("Every source page must be present.")
        if not allow_unreviewed and any(not p.reviewed_at for p in pages):
            raise ValidationError("Review and approve every page before publishing.")
        from .structured_extraction import validate_layout
        for page in pages:
            try:
                validate_layout(page.layout)
            except (ValueError, TypeError, KeyError) as error:
                raise ValidationError(f"Page {page.page_number}: {error}") from error
        ContentEdition.objects.filter(book=edition.book, status="published").update(status="archived")
        edition.status = "published"
        edition.published_at = timezone.now()
        edition.save(update_fields=("status", "published_at"))
        return edition
