import os
import shutil
import subprocess
import tempfile
from urllib.parse import urlparse

from django.conf import settings
from django.core.checks import Error, Warning, register
from django.core.files.storage import default_storage


@register()
def ebook_reader_production_checks(app_configs, **kwargs):
    messages = []
    messages.extend(_feature_flag_checks())
    messages.extend(_task_queue_checks())
    messages.extend(_ocr_checks())
    messages.extend(_pdf_rendering_checks())
    messages.extend(_storage_checks())
    messages.extend(_limit_checks())
    messages.extend(_cors_checks())
    messages.extend(_temp_directory_checks())
    return messages


def _feature_flag_checks():
    messages = []
    system_enabled = getattr(settings, "EBOOK_SYSTEM_ENABLED", False)
    web_enabled = getattr(settings, "EBOOK_WEB_READER_ENABLED", False)
    mobile_enabled = getattr(settings, "EBOOK_MOBILE_READER_ENABLED", False)
    processing_enabled = getattr(settings, "EBOOK_PROCESSING_ENABLED", False)

    if not system_enabled and (web_enabled or mobile_enabled or processing_enabled):
        messages.append(
            Warning(
                "EBOOK_SYSTEM_ENABLED is false, so web/mobile/processing ebook flags are overridden.",
                id="ebook_reader.W001",
            )
        )
    if getattr(settings, "EBOOK_READER_STAFF_ONLY", True) is False and settings.DEBUG is False:
        messages.append(
            Warning(
                "EBOOK_READER_STAFF_ONLY is false in non-debug mode. Confirm beta rollout is intended.",
                id="ebook_reader.W002",
            )
        )
    return messages


def _task_queue_checks():
    messages = []
    broker_url = getattr(settings, "CELERY_BROKER_URL", "")
    if getattr(settings, "EBOOK_PROCESSING_ENABLED", False) and not broker_url:
        messages.append(
            Error(
                "EBOOK_PROCESSING_ENABLED requires CELERY_BROKER_URL.",
                id="ebook_reader.E001",
            )
        )
        return messages

    parsed = urlparse(broker_url)
    if broker_url and parsed.scheme not in {"redis", "rediss", "memory", "amqp", "sqla"}:
        messages.append(
            Warning(
                f"Celery broker scheme '{parsed.scheme}' is not a commonly tested ebook processing broker.",
                id="ebook_reader.W003",
            )
        )
    return messages


def _ocr_checks():
    messages = []
    engine = str(getattr(settings, "EBOOK_OCR_ENGINE", "")).lower()
    languages = str(getattr(settings, "EBOOK_OCR_LANGUAGES", ""))
    if engine not in {"tesseract"}:
        messages.append(
            Warning(
                f"EBOOK_OCR_ENGINE '{engine}' is not recognised by the current OCR factory.",
                id="ebook_reader.W004",
            )
        )
        return messages

    executable = shutil.which("tesseract")
    if not executable:
        messages.append(
            Warning(
                "Tesseract executable was not found. Scanned Hindi TOC OCR will not work.",
                id="ebook_reader.W005",
            )
        )
        return messages

    if "hin" in languages:
        try:
            result = subprocess.run(
                [executable, "--list-langs"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            if "hin" not in result.stdout.split():
                messages.append(
                    Warning(
                        "Tesseract Hindi language data 'hin' was not reported by --list-langs.",
                        id="ebook_reader.W006",
                    )
                )
        except Exception:
            messages.append(
                Warning(
                    "Could not verify Tesseract language data.",
                    id="ebook_reader.W007",
                )
            )
    return messages


def _pdf_rendering_checks():
    try:
        import fitz  # noqa: F401
    except Exception as error:
        return [
            Error(
                f"PyMuPDF import failed: {error}",
                id="ebook_reader.E002",
            )
        ]
    return []


def _storage_checks():
    messages = []
    if not getattr(settings, "MEDIA_ROOT", None):
        messages.append(
            Warning(
                "MEDIA_ROOT is not configured. Verify uploaded PDF storage before enabling ebook delivery.",
                id="ebook_reader.W008",
            )
        )
    try:
        default_storage.exists("__ebook_reader_storage_check__")
    except Exception as error:
        messages.append(
            Warning(
                f"Default storage could not be checked safely: {error}",
                id="ebook_reader.W009",
            )
        )
    return messages


def _limit_checks():
    messages = []
    scan_limit = getattr(settings, "EBOOK_READER_TOC_SCAN_PAGE_LIMIT", 40)
    if scan_limit > 80:
        messages.append(
            Warning(
                "EBOOK_READER_TOC_SCAN_PAGE_LIMIT is high. Large scanned PDFs can overload OCR workers.",
                id="ebook_reader.W010",
            )
        )
    if getattr(settings, "EBOOK_SIGNED_URL_EXPIRES_SECONDS", 900) > 3600:
        messages.append(
            Warning(
                "EBOOK_SIGNED_URL_EXPIRES_SECONDS is longer than one hour.",
                id="ebook_reader.W011",
            )
        )
    if getattr(settings, "EBOOK_MAX_PDF_PAGES", 0) <= 0:
        messages.append(
            Error(
                "EBOOK_MAX_PDF_PAGES must be greater than zero.",
                id="ebook_reader.E003",
            )
        )
    return messages


def _cors_checks():
    if getattr(settings, "CORS_ALLOW_ALL_ORIGINS", False) and getattr(settings, "CORS_ALLOW_CREDENTIALS", False):
        return [
            Error(
                "Credentialed wildcard CORS is unsafe for ebook PDF access.",
                id="ebook_reader.E004",
            )
        ]
    return []


def _temp_directory_checks():
    temp_dir = tempfile.gettempdir()
    if not os.access(temp_dir, os.W_OK):
        return [
            Error(
                f"Temporary directory is not writable: {temp_dir}",
                id="ebook_reader.E005",
            )
        ]
    return []
