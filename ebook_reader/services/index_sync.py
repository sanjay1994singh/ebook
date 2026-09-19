from __future__ import annotations

from dataclasses import asdict, dataclass, field

from django.db import transaction

from ebook_reader.models import EbookDocument, EbookLesson
from library.models import Book, Chapter


@dataclass(frozen=True)
class IndexSyncResult:
    book_id: int
    ebook_document_id: int | None = None
    synced: int = 0
    skipped: int = 0
    replaced_existing: bool = False
    warnings: list[str] = field(default_factory=list)

    def as_dict(self):
        return asdict(self)


def sync_lessons_to_book_chapters(
    ebook_document: EbookDocument,
    *,
    replace_existing: bool = False,
) -> IndexSyncResult:
    """Publish verified/generated ebook lessons into the public Book chapter index."""
    lessons = list(
        ebook_document.lessons.exclude(start_page__isnull=True)
        .order_by("order", "id")
        .only("id", "title", "order", "start_page", "end_page", "ebook_id")
    )
    warnings = []
    if not lessons:
        return IndexSyncResult(
            book_id=ebook_document.book_id,
            ebook_document_id=ebook_document.id,
            skipped=ebook_document.lessons.count(),
            warnings=["No lessons with valid mapped start pages were available."],
        )

    with transaction.atomic():
        book = Book.objects.select_for_update().get(pk=ebook_document.book_id)
        existing_count = book.chapters.count()
        if existing_count and not replace_existing:
            warnings.append(
                "Book already has chapters; existing chapter index was kept. Use replace_existing to overwrite it."
            )
            return IndexSyncResult(
                book_id=book.id,
                ebook_document_id=ebook_document.id,
                skipped=len(lessons),
                warnings=warnings,
            )

        if replace_existing:
            book.chapters.all().delete()

        chapters = []
        total_pages = _total_pages_for(book, ebook_document)
        for index, lesson in enumerate(lessons, start=1):
            start_page = lesson.start_page
            end_page = lesson.end_page or _next_start_page(lessons, index) or total_pages
            if end_page is not None and start_page is not None and end_page < start_page:
                end_page = start_page
            chapters.append(
                Chapter(
                    book=book,
                    title=lesson.title.strip() or f"Chapter {index}",
                    order=lesson.order or index,
                    start_page=start_page,
                    end_page=end_page,
                )
            )
        Chapter.objects.bulk_create(chapters)

    return IndexSyncResult(
        book_id=ebook_document.book_id,
        ebook_document_id=ebook_document.id,
        synced=len(chapters),
        replaced_existing=bool(existing_count and replace_existing),
        warnings=warnings,
    )


def sync_book_index_from_document(
    book: Book,
    *,
    replace_existing: bool = False,
) -> IndexSyncResult:
    try:
        ebook_document = book.ebook_document
    except EbookDocument.DoesNotExist:
        return IndexSyncResult(book_id=book.id, warnings=["Book has no EbookDocument."])
    return sync_lessons_to_book_chapters(
        ebook_document,
        replace_existing=replace_existing,
    )


def _next_start_page(lessons: list[EbookLesson], current_index: int):
    if current_index >= len(lessons):
        return None
    next_page = lessons[current_index].start_page
    return next_page - 1 if next_page and next_page > 1 else None


def _total_pages_for(book: Book, ebook_document: EbookDocument):
    if ebook_document.total_pdf_pages:
        return ebook_document.total_pdf_pages
    published = book.content_editions.filter(status="published").order_by("-published_at", "-id").first()
    return published.total_pages if published else None
