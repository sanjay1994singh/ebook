from rest_framework import generics, permissions
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import (
    AudioCategory,
    AudioSpeaker,
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
from .pagination import StandardResultsSetPagination
from .serializers import (
    AudioCategorySerializer,
    AudioSpeakerSerializer,
    AudioTrackSerializer,
    BookDetailSerializer,
    BookListSerializer,
    BookPageSerializer,
    BookPageListSerializer,
    CategorySerializer,
    ChapterSerializer,
    FavoriteBookSerializer,
    MagazineIssueSerializer,
    MagazineSerializer,
    ReadingProgressSerializer,
)


class CategoryListView(generics.ListAPIView):
    queryset = Category.objects.all()
    serializer_class = CategorySerializer


class AudioCategoryListView(generics.ListAPIView):
    queryset = AudioCategory.objects.all()
    serializer_class = AudioCategorySerializer


class AudioSpeakerModelListView(generics.ListAPIView):
    queryset = AudioSpeaker.objects.all()
    serializer_class = AudioSpeakerSerializer


class AudioTrackListView(generics.ListAPIView):
    serializer_class = AudioTrackSerializer
    pagination_class = StandardResultsSetPagination

    def get_queryset(self):
        queryset = AudioTrack.objects.filter(is_published=True).select_related("category", "speaker_ref")
        category = self.request.query_params.get("category")
        speaker = self.request.query_params.get("speaker")
        free = self.request.query_params.get("free")
        if category:
            queryset = queryset.filter(category__slug=category)
        if speaker:
            if str(speaker).isdigit():
                queryset = queryset.filter(speaker_ref_id=speaker)
            else:
                queryset = queryset.filter(speaker_ref__name=speaker) | queryset.filter(speaker=speaker)
        if free in {"1", "true", "True"}:
            queryset = queryset.filter(is_free=True)
        return queryset


class AudioSpeakerListView(APIView):
    def get(self, request):
        # Category select hone ke baad speaker list return karta hai.
        queryset = AudioTrack.objects.filter(is_published=True)
        category = request.query_params.get("category")
        if category:
            queryset = queryset.filter(category__slug=category)

        speaker_rows = (
            queryset.exclude(speaker_ref=None)
            .values("speaker_ref_id", "speaker_ref__name")
            .distinct()
            .order_by("speaker_ref__name")
        )
        speakers = []
        used_names = set()
        for row in speaker_rows:
            speaker_name = row["speaker_ref__name"]
            used_names.add(speaker_name)
            speakers.append(
                {
                    "id": row["speaker_ref_id"],
                    "name": speaker_name,
                    "audio_count": queryset.filter(speaker_ref_id=row["speaker_ref_id"]).count(),
                }
            )

        text_speaker_names = (
            queryset.exclude(speaker="")
            .values_list("speaker", flat=True)
            .distinct()
            .order_by("speaker")
        )
        for speaker in text_speaker_names:
            if speaker in used_names:
                continue
            speakers.append(
                {
                    "id": speaker,
                    "name": speaker,
                    "audio_count": queryset.filter(speaker=speaker).count(),
                }
            )
        return Response(speakers)


class FreeAudioTrackListView(generics.ListAPIView):
    serializer_class = AudioTrackSerializer

    def get_queryset(self):
        return AudioTrack.objects.filter(is_published=True, is_free=True).select_related("category", "speaker_ref")[:5]


class BookListView(generics.ListAPIView):
    serializer_class = BookListSerializer
    pagination_class = StandardResultsSetPagination

    def get_queryset(self):
        # Only published books mobile app me dikhengi.
        queryset = Book.objects.filter(is_published=True).select_related("category")
        category = self.request.query_params.get("category")
        if category:
            queryset = queryset.filter(category__slug=category)
        return queryset


class BookDetailView(generics.RetrieveAPIView):
    queryset = Book.objects.filter(is_published=True).select_related("category")
    serializer_class = BookDetailSerializer
    lookup_field = "slug"


class MagazineListView(generics.ListAPIView):
    queryset = Magazine.objects.filter(is_published=True).prefetch_related("issues")
    serializer_class = MagazineSerializer
    pagination_class = StandardResultsSetPagination


class MagazineIssueListView(generics.ListAPIView):
    serializer_class = MagazineIssueSerializer
    pagination_class = StandardResultsSetPagination

    def get_queryset(self):
        return (
            MagazineIssue.objects.filter(magazine__slug=self.kwargs["slug"], magazine__is_published=True, is_published=True)
            .select_related("magazine", "book", "book__category")
            .order_by("order", "-year", "-issue_number", "title")
        )


class ChapterListView(generics.ListAPIView):
    serializer_class = ChapterSerializer

    def get_queryset(self):
        return Chapter.objects.filter(book__slug=self.kwargs["slug"], book__is_published=True)


class BookPageDetailView(generics.RetrieveAPIView):
    queryset = BookPage.objects.select_related("chapter", "chapter__book")
    serializer_class = BookPageSerializer


class ChapterPageListView(generics.ListAPIView):
    serializer_class = BookPageListSerializer

    def get_queryset(self):
        return BookPage.objects.filter(chapter_id=self.kwargs["chapter_id"])


class FavoriteListCreateView(generics.ListCreateAPIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = FavoriteBookSerializer

    def get_queryset(self):
        return FavoriteBook.objects.filter(user=self.request.user).select_related("book", "book__category")

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)


class FavoriteDeleteView(generics.DestroyAPIView):
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return FavoriteBook.objects.filter(user=self.request.user)

    def get_object(self):
        return self.get_queryset().get(book_id=self.kwargs["book_id"])


class ReadingProgressListCreateView(generics.ListCreateAPIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = ReadingProgressSerializer

    def get_queryset(self):
        return ReadingProgress.objects.filter(user=self.request.user).select_related(
            "book",
            "book__category",
            "chapter",
            "page",
        )

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)
