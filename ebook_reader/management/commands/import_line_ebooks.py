from pathlib import Path

from django.core.files import File
from django.core.management.base import BaseCommand, CommandError

from ebook_reader.models import Book
from ebook_reader.tasks import process_uploaded_book
from ebook_reader.utils import extract_book_pages


class Command(BaseCommand):
    help = "Import a folder of PDFs into the page-and-line ebook reader."

    def add_arguments(self, parser):
        parser.add_argument("folder", help="Folder containing PDF files")
        parser.add_argument("--recursive", action="store_true")
        parser.add_argument("--author", default="")
        parser.add_argument(
            "--synchronous",
            action="store_true",
            help="Process immediately instead of queueing Celery jobs",
        )
        parser.add_argument(
            "--force-ocr",
            action="store_true",
            help="OCR every page, including pages with valid Unicode text",
        )

    def handle(self, *args, **options):
        folder = Path(options["folder"]).expanduser().resolve()
        if not folder.is_dir():
            raise CommandError(f"Folder does not exist: {folder}")

        pattern = "**/*.pdf" if options["recursive"] else "*.pdf"
        paths = sorted(path for path in folder.glob(pattern) if path.is_file())
        if not paths:
            raise CommandError(f"No PDF files found in: {folder}")

        imported = skipped = failed = 0
        for path in paths:
            title = path.stem.strip()
            if Book.objects.filter(title=title).exists():
                skipped += 1
                self.stdout.write(self.style.WARNING(f"Skipped existing: {title}"))
                continue
            try:
                book = Book(title=title, author=options["author"])
                book._skip_auto_extraction = True
                with path.open("rb") as stream:
                    book.pdf_file.save(path.name, File(stream), save=False)
                    book.save()
                if options["synchronous"]:
                    extract_book_pages(book, force_ocr=options["force_ocr"])
                else:
                    process_uploaded_book.delay(book.pk, force_ocr=options["force_ocr"])
                imported += 1
                self.stdout.write(self.style.SUCCESS(f"Imported: {title}"))
            except Exception as error:
                failed += 1
                self.stderr.write(self.style.ERROR(f"Failed {path.name}: {error}"))

        self.stdout.write(
            self.style.SUCCESS(
                f"Complete: imported={imported}, skipped={skipped}, failed={failed}"
            )
        )
