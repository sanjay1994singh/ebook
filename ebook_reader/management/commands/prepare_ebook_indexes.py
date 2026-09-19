import json

from django.core.management.base import BaseCommand, CommandError

from ebook_reader.services.index_preparation import prepare_book_index
from library.models import Book


class Command(BaseCommand):
    help = "Prepare public book indexes from uploaded PDF table-of-contents pages."

    def add_arguments(self, parser):
        parser.add_argument("--book-id", type=int, action="append", dest="book_id")
        parser.add_argument("--book-ids", type=str, default="", dest="book_ids")
        parser.add_argument("--all-with-pdf", action="store_true")
        parser.add_argument("--published-only", action="store_true")
        parser.add_argument("--replace-chapters", action="store_true")
        parser.add_argument("--force-toc", action="store_true")
        parser.add_argument("--limit", type=int)
        parser.add_argument("--resume-from-id", type=int)

    def handle(self, *args, **options):
        book_ids = self._parse_book_ids(options)
        if not book_ids and not options["all_with_pdf"]:
            raise CommandError("Use --book-id, --book-ids or --all-with-pdf.")
        if options["limit"] is not None and options["limit"] < 1:
            raise CommandError("--limit must be greater than 0.")

        queryset = Book.objects.exclude(pdf_file="").order_by("id")
        if book_ids:
            queryset = queryset.filter(id__in=book_ids)
        if options["published_only"]:
            queryset = queryset.filter(is_published=True)
        if options["resume_from_id"]:
            queryset = queryset.filter(id__gte=options["resume_from_id"])
        if options["limit"]:
            queryset = queryset[: options["limit"]]

        results = []
        for book in queryset:
            result = prepare_book_index(
                book,
                replace_chapters=options["replace_chapters"],
                force_toc=options["force_toc"],
            )
            results.append(result.as_dict())

        summary = {
            "examined": len(results),
            "ready": sum(1 for item in results if item["status"] == "ready"),
            "review_required": sum(1 for item in results if item["status"] == "review_required"),
            "failed": sum(1 for item in results if item["status"] == "failed"),
            "results": results,
        }
        self.stdout.write(json.dumps(summary, ensure_ascii=False, indent=2))

    def _parse_book_ids(self, options):
        ids = list(options.get("book_id") or [])
        comma_value = options.get("book_ids") or ""
        if comma_value:
            try:
                ids.extend(
                    int(value.strip())
                    for value in comma_value.split(",")
                    if value.strip()
                )
            except ValueError as error:
                raise CommandError("--book-ids must contain comma-separated integers.") from error
        seen = set()
        unique_ids = []
        for book_id in ids:
            if book_id in seen:
                continue
            seen.add(book_id)
            unique_ids.append(book_id)
        return unique_ids
