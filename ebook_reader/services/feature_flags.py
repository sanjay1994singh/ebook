from django.conf import settings

from ebook_reader.models import EbookDocument


def ebook_system_enabled() -> bool:
    return bool(getattr(settings, "EBOOK_SYSTEM_ENABLED", False))


def web_reader_globally_enabled() -> bool:
    return ebook_system_enabled() and bool(getattr(settings, "EBOOK_WEB_READER_ENABLED", False))


def mobile_reader_globally_enabled() -> bool:
    return ebook_system_enabled() and bool(getattr(settings, "EBOOK_MOBILE_READER_ENABLED", False))


def processing_globally_enabled() -> bool:
    return ebook_system_enabled() and bool(getattr(settings, "EBOOK_PROCESSING_ENABLED", False))


def staff_only_enabled() -> bool:
    return bool(getattr(settings, "EBOOK_READER_STAFF_ONLY", True))


def is_staff_user(user) -> bool:
    return bool(user and user.is_authenticated and user.is_staff)


def is_ready_for_new_reader(ebook_document: EbookDocument) -> bool:
    return (
        ebook_system_enabled()
        and ebook_document.status == EbookDocument.Status.READY
        and ebook_document.new_ebook_reader_enabled
        and bool(ebook_document.book.pdf_file)
    )


def is_web_reader_available(ebook_document: EbookDocument, user=None) -> bool:
    if not (
        web_reader_globally_enabled()
        and is_ready_for_new_reader(ebook_document)
        and ebook_document.new_ebook_reader_web_enabled
    ):
        return False
    if staff_only_enabled() and not is_staff_user(user):
        return False
    return True


def is_mobile_reader_available(ebook_document: EbookDocument, user=None) -> bool:
    if not (
        mobile_reader_globally_enabled()
        and is_ready_for_new_reader(ebook_document)
        and ebook_document.new_ebook_reader_mobile_enabled
    ):
        return False
    if staff_only_enabled() and not is_staff_user(user):
        return False
    return True


def can_user_access_new_ebook(ebook_document: EbookDocument, user=None) -> bool:
    if not is_ready_for_new_reader(ebook_document):
        return False
    if is_staff_user(user):
        return True
    return bool(ebook_document.book.is_published)
