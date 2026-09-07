from pathlib import Path
from django.core.files import File
from django.core.management.base import BaseCommand, CommandError
from ebook_reader.services.structured_content import process_edition, queue_content
from library.models import Book


class Command(BaseCommand):
    help = "Extract a PDF into an unpublished, reviewable content edition."

    def add_arguments(self, parser):
        parser.add_argument("--book-id", type=int)
        parser.add_argument("--pdf")
        parser.add_argument("--title")
        parser.add_argument("--new-version", action="store_true")
        parser.add_argument("--queue", action="store_true")

    def handle(self, *args, **options):
        if options["book_id"]:
            book = Book.objects.get(pk=options["book_id"])
        elif options["pdf"] and options["title"]:
            path = Path(options["pdf"])
            if not path.is_file():
                raise CommandError("PDF file does not exist.")
            book = Book(title=options["title"], is_published=False, auto_extract_pdf=False)
            with path.open("rb") as source:
                book.pdf_file.save(path.name, File(source), save=False)
            book.save()
        else:
            raise CommandError("Use --book-id or both --pdf and --title.")
        edition = queue_content(book, new_version=options["new_version"], dispatch=options["queue"])
        self.stdout.write(f"Book {book.pk}; edition {edition.pk}; status {edition.status}")
        self.stdout.flush()
        if not options["queue"]:
            process_edition(edition.pk)
        edition.refresh_from_db()
        self.stdout.write(f"{edition.processed_pages}/{edition.total_pages} pages; {edition.status}; review /ebooks/content/editions/{edition.pk}/review/")
