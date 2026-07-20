from rest_framework import serializers

from .models import (
    AudioCategory,
    AudioSpeaker,
    AudioTrack,
    AppRating,
    AppUserProfile,
    Book,
    BookPage,
    Category,
    Chapter,
    ContactMessage,
    FavoriteBook,
    Magazine,
    MagazineIssue,
    ReadingProgress,
    SocialLink,
    SideMenuItem,
)


class CategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = ("id", "name", "slug", "order")


class AudioCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = AudioCategory
        fields = ("id", "name", "slug", "order")


class AudioSpeakerSerializer(serializers.ModelSerializer):
    class Meta:
        model = AudioSpeaker
        fields = ("id", "name", "slug", "order")


class AudioTrackSerializer(serializers.ModelSerializer):
    category = AudioCategorySerializer(read_only=True)
    speaker = serializers.SerializerMethodField()
    speaker_id = serializers.IntegerField(source="speaker_ref_id", read_only=True)
    audio_url = serializers.SerializerMethodField()

    class Meta:
        model = AudioTrack
        fields = (
            "id",
            "title",
            "slug",
            "category",
            "speaker_id",
            "speaker",
            "language",
            "duration",
            "audio_url",
            "external_url",
            "description",
            "is_free",
            "play_count",
        )

    def get_audio_url(self, obj):
        request = self.context.get("request")
        if obj.audio_file and request:
            return request.build_absolute_uri(obj.audio_file.url)
        return obj.external_url or None

    def get_speaker(self, obj):
        if obj.speaker_ref:
            return obj.speaker_ref.name
        return obj.speaker


class BookListSerializer(serializers.ModelSerializer):
    category = CategorySerializer(read_only=True)
    cover_image_url = serializers.SerializerMethodField()
    chapter_count = serializers.IntegerField(source="chapters.count", read_only=True)

    class Meta:
        model = Book
        fields = (
            "id",
            "title",
            "slug",
            "category",
            "language",
            "author",
            "cover_image_url",
            "chapter_count",
        )

    def get_cover_image_url(self, obj):
        request = self.context.get("request")
        if obj.cover_image and request:
            return request.build_absolute_uri(obj.cover_image.url)
        return None


class BookDetailSerializer(BookListSerializer):
    class Meta(BookListSerializer.Meta):
        fields = BookListSerializer.Meta.fields + ("description", "created_at", "updated_at")


class MagazineSerializer(serializers.ModelSerializer):
    cover_image_url = serializers.SerializerMethodField()
    issue_count = serializers.IntegerField(source="issues.count", read_only=True)

    class Meta:
        model = Magazine
        fields = (
            "id",
            "title",
            "slug",
            "subtitle",
            "language",
            "cover_image_url",
            "cover_text",
            "issue_count",
        )

    def get_cover_image_url(self, obj):
        request = self.context.get("request")
        if obj.cover_image and request:
            return request.build_absolute_uri(obj.cover_image.url)
        return None


class MagazineIssueSerializer(serializers.ModelSerializer):
    magazine = MagazineSerializer(read_only=True)
    cover_image_url = serializers.SerializerMethodField()
    book_detail = BookListSerializer(source="book", read_only=True)
    first_chapter = serializers.SerializerMethodField()
    pages = serializers.SerializerMethodField()

    class Meta:
        model = MagazineIssue
        fields = (
            "id",
            "magazine",
            "title",
            "slug",
            "year",
            "month",
            "issue_number",
            "language",
            "cover_image_url",
            "book",
            "book_detail",
            "first_chapter",
            "pages",
        )

    def get_cover_image_url(self, obj):
        request = self.context.get("request")
        if obj.cover_image and request:
            return request.build_absolute_uri(obj.cover_image.url)
        if obj.magazine and obj.magazine.cover_image and request:
            return request.build_absolute_uri(obj.magazine.cover_image.url)
        return None

    def get_first_chapter(self, obj):
        chapter = obj.book.chapters.order_by("order", "id").first() if obj.book else None
        if not chapter:
            return None
        return {"id": chapter.id, "book": chapter.book_id, "title": chapter.title, "order": chapter.order}

    def get_pages(self, obj):
        request = self.context.get("request")
        if not obj.book:
            return []
        pages = BookPage.objects.filter(chapter__book=obj.book).order_by("chapter__order", "chapter__id", "page_number", "id")
        page_list = []
        for page in pages:
            page_list.append(
                {
                    "id": page.id,
                    "chapter": page.chapter_id,
                    "title": page.title,
                    "page_number": page.page_number,
                    "page_image_url": request.build_absolute_uri(page.page_image.url) if page.page_image and request else None,
                }
            )
        return page_list


class ChapterSerializer(serializers.ModelSerializer):
    page_count = serializers.IntegerField(source="pages.count", read_only=True)

    class Meta:
        model = Chapter
        fields = ("id", "book", "title", "order", "page_count")


class BookPageSerializer(serializers.ModelSerializer):
    page_image_url = serializers.SerializerMethodField()

    class Meta:
        model = BookPage
        fields = ("id", "chapter", "title", "page_number", "content", "page_image_url")

    def get_page_image_url(self, obj):
        request = self.context.get("request")
        if obj.page_image and request:
            return request.build_absolute_uri(obj.page_image.url)
        return None


class BookPageListSerializer(serializers.ModelSerializer):
    page_image_url = serializers.SerializerMethodField()

    class Meta:
        model = BookPage
        fields = ("id", "chapter", "title", "page_number", "page_image_url")

    def get_page_image_url(self, obj):
        request = self.context.get("request")
        if obj.page_image and request:
            return request.build_absolute_uri(obj.page_image.url)
        return None


class FavoriteBookSerializer(serializers.ModelSerializer):
    book_detail = BookListSerializer(source="book", read_only=True)

    class Meta:
        model = FavoriteBook
        fields = ("id", "book", "book_detail", "created_at")
        read_only_fields = ("id", "created_at")

    def create(self, validated_data):
        # Same book ko duplicate favorite banne se rokta hai.
        user = self.context["request"].user
        favorite, _created = FavoriteBook.objects.get_or_create(user=user, **validated_data)
        return favorite


class ReadingProgressSerializer(serializers.ModelSerializer):
    book_detail = BookListSerializer(source="book", read_only=True)

    class Meta:
        model = ReadingProgress
        fields = (
            "id",
            "book",
            "book_detail",
            "chapter",
            "page",
            "progress_percent",
            "updated_at",
        )
        read_only_fields = ("id", "updated_at")

    def create(self, validated_data):
        # User + book ke liye ek hi progress row rakhta hai.
        user = self.context["request"].user
        book = validated_data["book"]
        progress, _created = ReadingProgress.objects.update_or_create(
            user=user,
            book=book,
            defaults=validated_data,
        )
        return progress


class AppUserProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = AppUserProfile
        fields = ("id", "device_id", "name", "mobile", "email", "language", "updated_at")
        read_only_fields = ("id", "updated_at")


class AppRatingSerializer(serializers.ModelSerializer):
    class Meta:
        model = AppRating
        fields = ("id", "device_id", "rating", "title", "review", "nickname", "created_at", "updated_at")
        read_only_fields = ("id", "created_at", "updated_at")

    def validate_rating(self, value):
        if value < 1 or value > 5:
            raise serializers.ValidationError("Rating must be between 1 and 5.")
        return value


class ContactMessageSerializer(serializers.ModelSerializer):
    class Meta:
        model = ContactMessage
        fields = ("id", "device_id", "service_type", "name", "mobile", "email", "message", "created_at")
        read_only_fields = ("id", "created_at")


class SocialLinkSerializer(serializers.ModelSerializer):
    class Meta:
        model = SocialLink
        fields = ("id", "name", "label", "icon", "url", "color", "order")


class SideMenuItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = SideMenuItem
        fields = ("id", "section", "title", "icon", "action", "url", "order")
