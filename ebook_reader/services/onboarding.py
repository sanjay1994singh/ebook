from __future__ import annotations

from dataclasses import asdict, dataclass, field

from django.db import IntegrityError

from ebook_reader.models import EbookDocument
from ebook_reader.tasks import detect_ebook_toc_document, inspect_ebook_document
from library.models import Book


@dataclass
class OnboardingFailure:
    book_id: int
    title: str
    error: str


@dataclass
class OnboardingSummary:
    examined: int = 0
    eligible: int = 0
    created: int = 0
    already_existed: int = 0
    missing_pdf: int = 0
    invalid_pdf_reference: int = 0
    queued_for_inspection: int = 0
    queued_for_toc_detection: int = 0
    skipped: int = 0
    failed: int = 0
    failure_details: list[OnboardingFailure] = field(default_factory=list)

    def as_dict(self) -> dict:
        data = asdict(self)
        data["failure_details"] = [asdict(item) for item in self.failure_details]
        return data


@dataclass(frozen=True)
class OnboardingOptions:
    book_ids: list[int] | None = None
    all_with_pdf: bool = False
    missing_only: bool = False
    existing_book_status: str = ""
    batch_size: int = 100
    dry_run: bool = False
    queue_inspection: bool = False
    queue_toc_detection: bool = False
    skip_existing: bool = False
    limit: int | None = None
    resume_from_id: int | None = None


def build_onboarding_queryset(options: OnboardingOptions):
    queryset = Book.objects.all().order_by("id").only(
        "id",
        "title",
        "pdf_file",
        "pdf_import_status",
        "is_published",
    )

    if options.book_ids:
        queryset = queryset.filter(id__in=options.book_ids)
    elif options.all_with_pdf or options.missing_only:
        queryset = queryset.exclude(pdf_file="")
    else:
        queryset = queryset.none()

    if options.resume_from_id:
        queryset = queryset.filter(id__gte=options.resume_from_id)

    if options.missing_only or options.skip_existing:
        queryset = queryset.filter(ebook_document__isnull=True)

    if options.existing_book_status:
        status = options.existing_book_status.strip().lower()
        if status == "published":
            queryset = queryset.filter(is_published=True)
        elif status == "unpublished":
            queryset = queryset.filter(is_published=False)
        else:
            queryset = queryset.filter(pdf_import_status=options.existing_book_status)

    cap = options.batch_size
    if options.limit is not None:
        cap = min(cap, options.limit)
    return queryset[:cap]


def onboard_ebooks(options: OnboardingOptions) -> OnboardingSummary:
    summary = OnboardingSummary()
    for book in build_onboarding_queryset(options):
        summary.examined += 1
        _onboard_one_book(book, options, summary)
    return summary


def create_ebook_document_for_book(book: Book, *, dry_run: bool = False) -> tuple[EbookDocument | None, bool]:
    if hasattr(book, "ebook_document"):
        return book.ebook_document, False
    if dry_run:
        return None, False
    return EbookDocument.objects.get_or_create(
        book=book,
        defaults={
            "toc_mode": EbookDocument.TocMode.AUTO,
            "status": EbookDocument.Status.PENDING,
        },
    )


def _onboard_one_book(book: Book, options: OnboardingOptions, summary: OnboardingSummary) -> None:
    if not book.pdf_file:
        summary.missing_pdf += 1
        summary.skipped += 1
        return

    if not _pdf_reference_exists(book):
        summary.invalid_pdf_reference += 1
        summary.skipped += 1
        return

    summary.eligible += 1

    try:
        document, created = create_ebook_document_for_book(book, dry_run=options.dry_run)
    except IntegrityError as error:
        summary.failed += 1
        summary.failure_details.append(
            OnboardingFailure(book_id=book.id, title=book.title, error=str(error))
        )
        return
    except Exception as error:
        summary.failed += 1
        summary.failure_details.append(
            OnboardingFailure(book_id=book.id, title=book.title, error=str(error))
        )
        return

    if created:
        summary.created += 1
    else:
        summary.already_existed += 1
        if options.skip_existing:
            summary.skipped += 1

    if options.dry_run or document is None:
        return

    if options.queue_inspection:
        inspect_ebook_document.delay(document.id)
        summary.queued_for_inspection += 1

    if options.queue_toc_detection:
        detect_ebook_toc_document.delay(document.id)
        summary.queued_for_toc_detection += 1


def onboard_selected_books(queryset) -> OnboardingSummary:
    summary = OnboardingSummary()
    for book in queryset.only("id", "title", "pdf_file"):
        summary.examined += 1
        _onboard_one_book(
            book,
            OnboardingOptions(book_ids=[book.id], batch_size=1),
            summary,
        )
    return summary


def _pdf_reference_exists(book: Book) -> bool:
    try:
        return bool(book.pdf_file.name) and book.pdf_file.storage.exists(book.pdf_file.name)
    except Exception:
        return False
