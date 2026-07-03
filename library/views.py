from rest_framework import generics, permissions

from .models import AudioCategory, AudioTrack, Book, BookPage, Category, Chapter, FavoriteBook, ReadingProgress
from .pagination import StandardResultsSetPagination
from .serializers import (
    AudioCategorySerializer,
    AudioTrackSerializer,
    BookDetailSerializer,
    BookListSerializer,
    BookPageSerializer,
    BookPageListSerializer,
    CategorySerializer,
    ChapterSerializer,
    FavoriteBookSerializer,
    ReadingProgressSerializer,
)


class CategoryListView(generics.ListAPIView):
    queryset = Category.objects.all()
    serializer_class = CategorySerializer


class AudioCategoryListView(generics.ListAPIView):
    queryset = AudioCategory.objects.all()
    serializer_class = AudioCategorySerializer


class AudioTrackListView(generics.ListAPIView):
    serializer_class = AudioTrackSerializer
    pagination_class = StandardResultsSetPagination

    def get_queryset(self):
        queryset = AudioTrack.objects.filter(is_published=True).select_related("category")
        category = self.request.query_params.get("category")
        free = self.request.query_params.get("free")
        if category:
            queryset = queryset.filter(category__slug=category)
        if free in {"1", "true", "True"}:
            queryset = queryset.filter(is_free=True)
        return queryset


class FreeAudioTrackListView(generics.ListAPIView):
    serializer_class = AudioTrackSerializer

    def get_queryset(self):
        return AudioTrack.objects.filter(is_published=True, is_free=True).select_related("category")[:5]


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
