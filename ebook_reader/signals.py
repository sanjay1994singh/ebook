import logging

from django.conf import settings
from django.db import transaction
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver

from .models import Book
from .utils import extract_book_pages

logger = logging.getLogger(__name__)


@receiver(pre_save, sender=Book)
def remember_previous_pdf(sender, instance, **kwargs):
    if not instance.pk:
        instance._pdf_changed = True
        return
    previous_name = sender.objects.filter(pk=instance.pk).values_list("pdf_file", flat=True).first()
    instance._pdf_changed = previous_name != instance.pdf_file.name


@receiver(post_save, sender=Book)
def extract_uploaded_pdf(sender, instance, created, raw=False, **kwargs):
    if (
        raw
        or getattr(instance, "_skip_auto_extraction", False)
        or not instance.pdf_file
        or not (created or getattr(instance, "_pdf_changed", False))
    ):
        return

    def process():
        if getattr(settings, "EBOOK_READER_ASYNC_PROCESSING", False):
            from .tasks import process_uploaded_book

            try:
                process_uploaded_book.delay(instance.pk)
            except Exception as error:
                sender.objects.filter(pk=instance.pk).update(
                    processing_status=Book.ProcessingStatus.FAILED,
                    processing_error=f"Could not queue PDF processing: {error}"[:4000],
                )
                logger.exception("Could not queue PDF processing for Book pk=%s", instance.pk)
            return
        try:
            extract_book_pages(instance)
        except Exception:
            logger.exception("Could not extract PDF for ebook_reader.Book pk=%s", instance.pk)

    transaction.on_commit(process)
