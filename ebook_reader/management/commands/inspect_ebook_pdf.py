import json

from django.core.management.base import BaseCommand, CommandError

from ebook_reader.models import EbookDocument
from ebook_reader.services.pdf_metadata import EbookPdfError, inspect_pdf_metadata


class Command(BaseCommand):
    help = "Inspect the existing Book PDF linked to an EbookDocument."

    def add_arguments(self, parser):
        parser.add_argument("ebook_id", type=int, help="EbookDocument id.")

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
            metadata = inspect_pdf_metadata(ebook_document)
        except EbookPdfError as error:
            raise CommandError(json.dumps(error.as_dict(), ensure_ascii=False)) from error

        self.stdout.write(json.dumps(metadata.as_dict(), indent=2, ensure_ascii=False))
