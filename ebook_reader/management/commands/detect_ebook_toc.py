import json

from django.core.management.base import BaseCommand, CommandError

from ebook_reader.models import EbookDocument
from ebook_reader.services.ocr.exceptions import OcrError
from ebook_reader.services.pdf_metadata import EbookPdfError
from ebook_reader.services.toc_detection import detect_ebook_toc
from ebook_reader.services.toc_detection.ocr_provider import ocr_text_provider_for_document


class Command(BaseCommand):
    help = "Detect the TOC location for an EbookDocument PDF without creating lessons."

    def add_arguments(self, parser):
        parser.add_argument("ebook_id", type=int, help="EbookDocument id.")
        parser.add_argument(
            "--max-pages",
            type=int,
            default=None,
            help="Maximum number of initial PDF pages to scan for embedded TOC text.",
        )
        parser.add_argument(
            "--ocr",
            action="store_true",
            help="Enable OCR fallback when embedded text is missing or unusable.",
        )

    def handle(self, *args, **options):
        try:
            ebook_document = EbookDocument.objects.select_related("book").get(
                id=options["ebook_id"]
            )
        except EbookDocument.DoesNotExist as error:
            raise CommandError(
                f"EbookDocument id not found: {options['ebook_id']}"
            ) from error

        try:
            ocr_text_provider = (
                ocr_text_provider_for_document(ebook_document)
                if options["ocr"]
                else None
            )
            result = detect_ebook_toc(
                ebook_document,
                max_pages=options["max_pages"],
                ocr_text_provider=ocr_text_provider,
            )
        except EbookPdfError as error:
            raise CommandError(json.dumps(error.as_dict(), ensure_ascii=False)) from error
        except OcrError as error:
            raise CommandError(json.dumps(error.as_dict(), ensure_ascii=False)) from error

        self.stdout.write(json.dumps(result, indent=2, ensure_ascii=False))
