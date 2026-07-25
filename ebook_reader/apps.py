from django.apps import AppConfig


class EbookReaderConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "ebook_reader"

    def ready(self):
        from . import checks  # noqa: F401
