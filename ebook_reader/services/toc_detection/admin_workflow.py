from dataclasses import dataclass

from django.core.exceptions import ValidationError

from ebook_reader.models import EbookDocument

from .detector import detect_ebook_toc


@dataclass(frozen=True)
class TocDetectionActionResult:
    detected: int = 0
    failed: int = 0
    skipped: int = 0


@dataclass(frozen=True)
class TocAcceptActionResult:
    updated: int = 0
    skipped: int = 0


def run_toc_detection(queryset):
    detected = failed = skipped = 0
    for ebook_document in queryset.select_related("book"):
        if ebook_document.toc_mode == EbookDocument.TocMode.NONE:
            skipped += 1
            continue

        try:
            result = detect_ebook_toc(ebook_document)
            updates = {
                "toc_detection_confidence": result["confidence"],
                "toc_detection_metadata": result,
                "status": EbookDocument.Status.REVIEW_REQUIRED,
            }
            if ebook_document.toc_mode == EbookDocument.TocMode.AUTO:
                updates.update(
                    {
                        "detected_toc_start_page": result["detected_start_page"],
                        "detected_toc_end_page": result["detected_end_page"],
                    }
                )
            EbookDocument.objects.filter(id=ebook_document.id).update(**updates)
            if result.get("found"):
                detected += 1
            else:
                failed += 1
        except Exception as error:
            EbookDocument.objects.filter(id=ebook_document.id).update(
                status=EbookDocument.Status.REVIEW_REQUIRED,
                toc_detection_metadata={
                    "found": False,
                    "warnings": [str(error)],
                    "requires_manual_configuration": True,
                },
            )
            failed += 1
    return TocDetectionActionResult(detected=detected, failed=failed, skipped=skipped)


def accept_detected_toc_range(queryset):
    updated = skipped = 0
    for ebook_document in queryset:
        if not ebook_document.detected_toc_start_page or not ebook_document.detected_toc_end_page:
            skipped += 1
            continue

        ebook_document.toc_mode = EbookDocument.TocMode.MANUAL
        ebook_document.toc_start_page = ebook_document.detected_toc_start_page
        ebook_document.toc_end_page = ebook_document.detected_toc_end_page
        try:
            ebook_document.full_clean()
        except ValidationError:
            skipped += 1
            continue
        ebook_document.save(
            update_fields=[
                "toc_mode",
                "toc_start_page",
                "toc_end_page",
                "updated_at",
            ]
        )
        updated += 1
    return TocAcceptActionResult(updated=updated, skipped=skipped)


def switch_to_manual_mode(queryset):
    return queryset.update(toc_mode=EbookDocument.TocMode.MANUAL)


def mark_as_no_toc(queryset):
    return queryset.update(toc_mode=EbookDocument.TocMode.NONE)
