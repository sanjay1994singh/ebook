import json

from django.core.management.base import BaseCommand

from ebook_reader.services.toc_processing import process_ebook_toc


class Command(BaseCommand):
    help = "Parse an accepted ebook TOC range and persist draft lessons."

    def add_arguments(self, parser):
        parser.add_argument("ebook_id", type=int)
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--force", action="store_true")
        parser.add_argument("--show-diagnostics", action="store_true")

    def handle(self, *args, **options):
        result = process_ebook_toc(
            options["ebook_id"],
            force=options["force"],
            dry_run=options["dry_run"],
        )
        data = result.as_dict()
        if not options["show_diagnostics"]:
            data.pop("diagnostics", None)
        self.stdout.write(json.dumps(data, ensure_ascii=False, indent=2))
