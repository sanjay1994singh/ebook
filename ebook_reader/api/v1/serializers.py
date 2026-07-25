from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from ebook_reader.models import EbookDocument, EbookLesson, EbookReadingProgress
from ebook_reader.services.progress import (
    empty_progress_payload,
    progress_payload,
    save_ebook_progress,
)
from ebook_reader.services.feature_flags import (
    is_mobile_reader_available,
    is_web_reader_available,
)
from library.serializers import CategorySerializer


class EbookLessonPublicSerializer(serializers.ModelSerializer):
    class Meta:
        model = EbookLesson
        fields = (
            "id",
            "order",
            "title",
            "start_page",
            "end_page",
            "printed_page_number",
        )


class EbookListSerializer(serializers.ModelSerializer):
    existing_book_id = serializers.IntegerField(source="book_id", read_only=True)
    title = serializers.CharField(source="book.title", read_only=True)
    slug = serializers.CharField(source="book.slug", read_only=True)
    author = serializers.CharField(source="book.author", read_only=True)
    short_description = serializers.SerializerMethodField()
    cover_image_url = serializers.SerializerMethodField()
    lesson_count = serializers.IntegerField(read_only=True)
    progress_summary = serializers.SerializerMethodField()
    reader_available = serializers.SerializerMethodField()
    category = CategorySerializer(source="book.category", read_only=True)

    class Meta:
        model = EbookDocument
        fields = (
            "id",
            "existing_book_id",
            "title",
            "slug",
            "author",
            "short_description",
            "category",
            "cover_image_url",
            "total_pdf_pages",
            "lesson_count",
            "progress_summary",
            "reader_available",
        )

    def get_short_description(self, obj):
        description = obj.book.description or ""
        return description[:240]

    def get_cover_image_url(self, obj):
        request = self.context.get("request")
        if obj.book.cover_image and request:
            return request.build_absolute_uri(obj.book.cover_image.url)
        return None

    def get_progress_summary(self, obj):
        request = self.context.get("request")
        if not request or not request.user.is_authenticated:
            return None
        progress = getattr(obj, "_user_progress", None)
        if not progress:
            progress = EbookReadingProgress.objects.filter(
                user=request.user,
                ebook_document=obj,
            ).select_related("current_lesson").first()
        if not progress:
            return None
        return progress_payload(progress)

    def get_reader_available(self, obj):
        request = self.context.get("request")
        user = request.user if request else None
        return is_mobile_reader_available(obj, user) and obj.lesson_count > 0


class EbookDetailSerializer(EbookListSerializer):
    existing_book = serializers.SerializerMethodField()
    continue_reading_page = serializers.SerializerMethodField()
    access_restrictions = serializers.SerializerMethodField()

    class Meta(EbookListSerializer.Meta):
        fields = EbookListSerializer.Meta.fields + (
            "existing_book",
            "continue_reading_page",
            "access_restrictions",
            "created_at",
            "updated_at",
        )

    def get_existing_book(self, obj):
        return {
            "id": obj.book_id,
            "title": obj.book.title,
            "slug": obj.book.slug,
            "language": obj.book.language,
            "author": obj.book.author,
            "description": obj.book.description,
            "is_published": obj.book.is_published,
        }

    def get_continue_reading_page(self, obj):
        progress = self.get_progress_summary(obj)
        if progress and progress.get("current_page"):
            current_lesson = progress.get("current_lesson")
            return {
                "pdf_page": progress["current_page"],
                "lesson_id": current_lesson["id"] if current_lesson else None,
            }
        first_lesson = obj.lessons.filter(is_verified=True, start_page__isnull=False).order_by("order", "id").first()
        if first_lesson:
            return {"pdf_page": first_lesson.start_page, "lesson_id": first_lesson.id}
        return None

    def get_access_restrictions(self, obj):
        return {
            "requires_authentication": False,
            "requires_subscription": False,
            "reason": None,
        }


class EbookReaderConfigSerializer(serializers.ModelSerializer):
    ebook_id = serializers.IntegerField(source="id", read_only=True)
    total_pages = serializers.IntegerField(source="total_pdf_pages", read_only=True)
    initial_page = serializers.SerializerMethodField()
    lessons = serializers.SerializerMethodField()
    lessons_endpoint = serializers.SerializerMethodField()
    pdf_access_method = serializers.SerializerMethodField()
    reader_url = serializers.SerializerMethodField()
    expires_at = serializers.SerializerMethodField()
    capability_flags = serializers.SerializerMethodField()

    class Meta:
        model = EbookDocument
        fields = (
            "ebook_id",
            "total_pages",
            "initial_page",
            "lessons_endpoint",
            "lessons",
            "pdf_access_method",
            "reader_url",
            "expires_at",
            "capability_flags",
        )

    def get_initial_page(self, obj):
        request = self.context.get("request")
        if request and request.user.is_authenticated:
            progress = getattr(obj, "_user_progress", None)
            if not progress:
                progress = EbookReadingProgress.objects.filter(
                    user=request.user,
                    ebook_document=obj,
                ).first()
            if progress:
                return progress.current_page
        first_lesson = obj.lessons.filter(is_verified=True, start_page__isnull=False).order_by("order", "id").first()
        return first_lesson.start_page if first_lesson else 1

    def get_lessons(self, obj):
        lessons = obj.lessons.filter(is_verified=True, start_page__isnull=False).order_by("order", "id")
        return EbookLessonPublicSerializer(lessons, many=True).data

    def get_lessons_endpoint(self, obj):
        request = self.context.get("request")
        path = f"/api/v1/ebooks/{obj.id}/lessons/"
        return request.build_absolute_uri(path) if request else path

    def get_pdf_access_method(self, obj):
        return "authenticated_stream" if obj.book.pdf_file else "unavailable"

    def get_reader_url(self, obj):
        request = self.context.get("request")
        if not obj.book.pdf_file:
            return None
        path = f"/api/v1/ebooks/{obj.id}/pdf-access/"
        return request.build_absolute_uri(path) if request else path

    def get_expires_at(self, obj):
        return None

    def get_capability_flags(self, obj):
        request = self.context.get("request")
        user = request.user if request else None
        return {
            "supports_lessons": True,
            "supports_pdf_pages": True,
            "supports_progress": True,
            "offline_cache_allowed": True,
            "web_reader_enabled": is_web_reader_available(obj, user),
            "mobile_reader_enabled": is_mobile_reader_available(obj, user),
        }


class EbookDiagnosticsSerializer(serializers.ModelSerializer):
    book_title = serializers.CharField(source="book.title", read_only=True)

    class Meta:
        model = EbookDocument
        fields = (
            "id",
            "book_title",
            "status",
            "toc_mode",
            "toc_start_page",
            "toc_end_page",
            "detected_toc_start_page",
            "detected_toc_end_page",
            "toc_detection_confidence",
            "page_mapping_mode",
            "page_mapping_status",
            "page_number_offset",
            "detected_page_number_offset",
            "page_mapping_confidence",
            "processing_metadata",
        )


class EbookProgressSerializer(serializers.Serializer):
    current_page = serializers.IntegerField(required=True)
    current_lesson = serializers.SerializerMethodField(read_only=True)
    percentage = serializers.DecimalField(max_digits=5, decimal_places=2, read_only=True)
    last_read_at = serializers.DateTimeField(read_only=True)
    completed = serializers.BooleanField(read_only=True)
    completed_at = serializers.DateTimeField(read_only=True, allow_null=True)

    def get_current_lesson(self, obj):
        if isinstance(obj, dict):
            return obj.get("current_lesson")
        return progress_payload(obj)["current_lesson"]

    def to_representation(self, instance):
        if isinstance(instance, EbookReadingProgress):
            return super().to_representation(progress_payload(instance))
        return super().to_representation(instance)


class EbookProgressUpdateSerializer(serializers.Serializer):
    current_page = serializers.IntegerField()

    def validate_current_page(self, value):
        ebook = self.context["ebook"]
        try:
            if value < 1:
                raise DjangoValidationError("Current page must be greater than or equal to 1.")
            if ebook.total_pdf_pages and value > ebook.total_pdf_pages:
                raise DjangoValidationError("Current page is outside this ebook PDF.")
        except DjangoValidationError as exc:
            raise serializers.ValidationError(exc.messages[0])
        return value

    def save(self, **kwargs):
        request = self.context["request"]
        ebook = self.context["ebook"]
        return save_ebook_progress(
            user=request.user,
            ebook_document=ebook,
            current_page=self.validated_data["current_page"],
        )


def progress_response_for(ebook, user):
    progress = EbookReadingProgress.objects.filter(
        user=user,
        ebook_document=ebook,
    ).select_related("current_lesson").first()
    if not progress:
        return empty_progress_payload(ebook)
    return progress_payload(progress)
