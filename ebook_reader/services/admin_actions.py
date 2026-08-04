from dataclasses import dataclass

from django.db.models import Count, F, Q

from ebook_reader.models import EbookDocument


@dataclass(frozen=True)
class ReadyActionResult:
    updated: int
    skipped: int


def documents_ready_for_review(queryset):
    return queryset.annotate(
        lesson_total=Count("lessons", distinct=True),
        verified_lesson_total=Count(
            "lessons",
            filter=Q(lessons__is_verified=True),
            distinct=True,
        ),
    ).filter(
        lesson_total__gt=0,
        lesson_total=F("verified_lesson_total"),
    )


def mark_ready_when_verified(queryset):
    ready_ids = list(documents_ready_for_review(queryset).values_list("id", flat=True))
    updated = queryset.model.objects.filter(id__in=ready_ids).update(
        status=EbookDocument.Status.READY
    )
    skipped = queryset.exclude(id__in=ready_ids).count()
    return ReadyActionResult(updated=updated, skipped=skipped)


def reset_to_pending(queryset):
    return queryset.update(status=EbookDocument.Status.PENDING)
