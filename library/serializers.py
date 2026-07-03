from rest_framework import serializers

from .models import (
    AudioCategory,
    AudioTrack,
    Book,
    BookPage,
    Category,
    Chapter,
    FavoriteBook,
    Magazine,
    MagazineIssue,
    ReadingProgress,
)


class CategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = ("id", "name", "slug", "order")


class AudioCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = AudioCategory
        fields = ("id", "name", "slug", "order")


class AudioTrackSerializer(serializers.ModelSerializer):
    category = AudioCategorySerializer(read_only=True)
    audio_url = serializers.SerializerMethodField()

    class Meta:
        model = AudioTrack
        fields = (
            "id",
            "title",
            "slug",
            "category",
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
        )

    def get_cover_image_url(self, obj):
        request = self.context.get("request")
        if obj.cover_image and request:
            return request.build_absolute_uri(obj.cover_image.url)
        if obj.magazine and obj.magazine.cover_image and request:
            return request.build_absolute_uri(obj.magazine.cover_image.url)
        return None


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
