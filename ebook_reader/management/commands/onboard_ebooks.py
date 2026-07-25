import json

from django.core.management.base import BaseCommand, CommandError

from ebook_reader.services.onboarding import OnboardingOptions, onboard_ebooks


class Command(BaseCommand):
    help = "Safely create EbookDocument records for existing Book PDFs."

    def add_arguments(self, parser):
        parser.add_argument("--book-id", type=int, action="append", dest="book_id")
        parser.add_argument("--book-ids", type=str, default="", dest="book_ids")
        parser.add_argument("--all-with-pdf", action="store_true")
        parser.add_argument("--missing-only", action="store_true")
        parser.add_argument("--status", type=str, default="")
        parser.add_argument("--batch-size", type=int, default=100)
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--queue-inspection", action="store_true")
        parser.add_argument("--queue-toc-detection", action="store_true")
        parser.add_argument("--skip-existing", action="store_true")
        parser.add_argument("--limit", type=int)
        parser.add_argument("--resume-from-id", type=int)

    def handle(self, *args, **options):
        if options["batch_size"] < 1:
            raise CommandError("--batch-size must be greater than 0.")
        if options["limit"] is not None and options["limit"] < 1:
            raise CommandError("--limit must be greater than 0.")

        book_ids = self._parse_book_ids(options)
        if not book_ids and not options["all_with_pdf"] and not options["missing_only"]:
            raise CommandError("Use --book-id, --book-ids, --all-with-pdf or --missing-only.")

        summary = onboard_ebooks(
            OnboardingOptions(
                book_ids=book_ids,
                all_with_pdf=options["all_with_pdf"],
                missing_only=options["missing_only"],
                existing_book_status=options["status"],
                batch_size=options["batch_size"],
                dry_run=options["dry_run"],
                queue_inspection=options["queue_inspection"],
                queue_toc_detection=options["queue_toc_detection"],
                skip_existing=options["skip_existing"],
                limit=options["limit"],
                resume_from_id=options["resume_from_id"],
            )
        )
        self.stdout.write(json.dumps(summary.as_dict(), ensure_ascii=False, indent=2))

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
