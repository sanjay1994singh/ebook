import json

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from ebook_reader.models import EbookDocument
from ebook_reader.services.ocr import get_ocr_engine
from ebook_reader.services.ocr.exceptions import OcrError
from ebook_reader.services.pdf_metadata import EbookPdfError
from ebook_reader.services.pdf_rendering import render_pdf_page_to_image


class Command(BaseCommand):
    help = "Render and OCR one selected EbookDocument PDF page."

    def add_arguments(self, parser):
        parser.add_argument("ebook_id", type=int, help="EbookDocument id.")
        parser.add_argument("page_number", type=int, help="1-based PDF page number.")
        parser.add_argument("--format", choices=("json", "text"), default="json")
        parser.add_argument("--engine", default=None, help="OCR engine name.")

    def handle(self, *args, **options):
        try:
            ebook_document = EbookDocument.objects.select_related("book").get(
                id=options["ebook_id"]
            )
        except EbookDocument.DoesNotExist as error:
            raise CommandError(f"EbookDocument id not found: {options['ebook_id']}") from error

        try:
            image = render_pdf_page_to_image(
                ebook_document,
                options["page_number"],
                dpi=settings.EBOOK_RENDER_DPI,
            )
            result = get_ocr_engine(options["engine"]).extract(image)
        except EbookPdfError as error:
            raise CommandError(json.dumps(error.as_dict(), ensure_ascii=False)) from error
        except OcrError as error:
            raise CommandError(json.dumps(error.as_dict(), ensure_ascii=False)) from error

        if options["format"] == "text":
            self.stdout.write(result.full_text)
            return
        self.stdout.write(json.dumps(result.as_dict(), indent=2, ensure_ascii=False))
