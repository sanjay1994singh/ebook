from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.core.files import File
from django.utils.text import slugify

from library.models import Book, Category
from library.pdf_importer import extract_pdf_to_book


class Command(BaseCommand):
    help = "Import all PDFs from a folder as books, skipping duplicates."

    def add_arguments(self, parser):
        parser.add_argument("folder_path", help="Folder containing PDF files.")
        parser.add_argument("--category", default="Vani", help="Category name for imported books.")
        parser.add_argument(
            "--skip-extract",
            action="store_true",
            help="Create book records only, without extracting pages.",
        )

    def handle(self, *args, **options):
        folder_path = Path(options["folder_path"])
        if not folder_path.exists() or not folder_path.is_dir():
            raise CommandError(f"Folder not found: {folder_path}")

        category, _created = Category.objects.get_or_create(
            name=options["category"],
            defaults={"slug": slugify(options["category"], allow_unicode=True)},
        )

        pdf_files = sorted(folder_path.glob("*.pdf"), key=lambda item: item.name.lower())
        if not pdf_files:
            self.stdout.write(self.style.WARNING("No PDF files found."))
            return

        created_count = 0
        skipped_count = 0
        failed_count = 0

        for pdf_path in pdf_files:
            title = self._title_from_filename(pdf_path.name)
            slug = slugify(title, allow_unicode=True)

            if pdf_path.stat().st_size == 0:
                skipped_count += 1
                self.stdout.write(self.style.WARNING(f"SKIP empty file: {pdf_path.name}"))
                continue

            duplicate = self._book_already_exists(title, slug, pdf_path.name)
            if duplicate:
                skipped_count += 1
                self.stdout.write(self.style.WARNING(f"SKIP duplicate: {title}"))
                continue

            try:
                book = Book(
                    title=title,
                    slug=slug,
                    category=category,
                    language="हिंदी",
                    pdf_import_status="copying",
                    is_published=True,
                )

                with pdf_path.open("rb") as pdf_file:
                    book.pdf_file.save(pdf_path.name, File(pdf_file), save=True)

                if options["skip_extract"]:
                    book.pdf_import_status = "not_extracted"
                    book.save(update_fields=["pdf_import_status", "updated_at"])
                    imported_pages = 0
                else:
                    imported_pages = extract_pdf_to_book(book)
                    if not book.cover_image:
                        self._save_cover_from_first_page(book)

                created_count += 1
                self.stdout.write(self.style.SUCCESS(f"IMPORTED: {title} ({imported_pages} pages)"))
            except Exception as error:
                failed_count += 1
                self.stdout.write(self.style.ERROR(f"FAILED: {pdf_path.name} - {error}"))

        self.stdout.write(
            self.style.SUCCESS(
                f"Done. created={created_count}, skipped={skipped_count}, failed={failed_count}"
            )
        )

    def _title_from_filename(self, filename):
        title = Path(filename).stem
        for word in (" PDF", " Pdf", " pdf"):
            title = title.replace(word, "")
        return " ".join(title.replace("_", " ").replace("-", " ").split())

    def _book_already_exists(self, title, slug, filename):
        if Book.objects.filter(slug=slug).exists() or Book.objects.filter(title__iexact=title).exists():
            return True

        new_file_key = self._normalize_duplicate_key(Path(filename).stem)
        for existing_book in Book.objects.exclude(pdf_file=""):
            existing_name = Path(existing_book.pdf_file.name).stem
            keys = {
                self._normalize_duplicate_key(existing_book.title),
                self._normalize_duplicate_key(existing_book.slug),
                self._normalize_duplicate_key(existing_name),
            }
            if new_file_key in keys:
                return True
        return False

    def _normalize_duplicate_key(self, value):
        clean_value = value.lower()
        for word in ("pdf", "book", "pustak"):
            clean_value = clean_value.replace(word, "")
        return "".join(character for character in clean_value if character.isalnum())

    def _save_cover_from_first_page(self, book):
        first_page = book.chapters.order_by("order", "id").first()
        if not first_page:
            return

        first_book_page = first_page.pages.order_by("page_number", "id").first()
        if not first_book_page or not first_book_page.page_image:
            return

        source_path = Path(first_book_page.page_image.path)
        if not source_path.exists():
            return

        cover_name = f"{book.slug}-cover{source_path.suffix}"
        with source_path.open("rb") as source_file:
            book.cover_image.save(cover_name, File(source_file), save=True)
