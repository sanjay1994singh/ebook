from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Seed command disabled. Books should be uploaded from admin only."

    def handle(self, *args, **options):
        self.stdout.write(
            self.style.WARNING("Seed skipped. Upload books from Django admin.")
        )
