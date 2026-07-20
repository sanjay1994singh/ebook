from rest_framework import generics, permissions
from rest_framework.response import Response
from rest_framework.views import APIView

from content.models import AmritVachan
from content.serializers import AmritVachanSerializer
from youtube_feed.services import get_channel_videos

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
from .pagination import StandardResultsSetPagination
from .serializers import (
    AudioCategorySerializer,
    AudioSpeakerSerializer,
    AudioTrackSerializer,
    AppRatingSerializer,
    AppUserProfileSerializer,
    BookDetailSerializer,
    BookListSerializer,
    BookPageSerializer,
    BookPageListSerializer,
    CategorySerializer,
    ChapterSerializer,
    ContactMessageSerializer,
    FavoriteBookSerializer,
    MagazineIssueSerializer,
    MagazineSerializer,
    ReadingProgressSerializer,
    SocialLinkSerializer,
    SideMenuItemSerializer,
)


class CategoryListView(generics.ListAPIView):
    queryset = Category.objects.exclude(slug__in=["patrika", "magazine"])
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
        queryset = (
            Book.objects.filter(is_published=True)
            .filter(magazine_issue__isnull=True)
            .exclude(category__slug__in=["patrika", "magazine"])
            .select_related("category")
        )
        category = self.request.query_params.get("category")
        author = self.request.query_params.get("author")
        if category:
            queryset = queryset.filter(category__slug=category)
        if author:
            queryset = queryset.filter(author=author)
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


class AppUserProfileView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        device_id = request.query_params.get("device_id")
        if not device_id:
            return Response({})
        profile = AppUserProfile.objects.filter(device_id=device_id).first()
        if not profile:
            return Response({})
        return Response(AppUserProfileSerializer(profile).data)

    def post(self, request):
        device_id = request.data.get("device_id")
        if not device_id:
            return Response({"device_id": ["This field is required."]}, status=400)
        profile, _created = AppUserProfile.objects.get_or_create(device_id=device_id)
        serializer = AppUserProfileSerializer(profile, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


class AppRatingView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        device_id = request.query_params.get("device_id")
        if not device_id:
            return Response({})
        rating = AppRating.objects.filter(device_id=device_id).first()
        if not rating:
            return Response({})
        return Response(AppRatingSerializer(rating).data)

    def post(self, request):
        device_id = request.data.get("device_id")
        if not device_id:
            return Response({"device_id": ["This field is required."]}, status=400)
        rating, _created = AppRating.objects.get_or_create(device_id=device_id)
        serializer = AppRatingSerializer(rating, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


class ContactMessageView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        device_id = request.query_params.get("device_id")
        queryset = ContactMessage.objects.all()
        if device_id:
            queryset = queryset.filter(device_id=device_id)
        messages = queryset[:10]
        latest = messages[0] if messages else None
        return Response(
            {
                "latest": ContactMessageSerializer(latest).data if latest else None,
                "results": ContactMessageSerializer(messages, many=True).data,
            }
        )

    def post(self, request):
        serializer = ContactMessageSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        message = serializer.save()
        if message.device_id:
            AppUserProfile.objects.update_or_create(
                device_id=message.device_id,
                defaults={
                    "name": message.name,
                    "mobile": message.mobile,
                    "email": message.email,
                },
            )
        return Response(ContactMessageSerializer(message).data, status=201)


class SocialLinkListView(generics.ListAPIView):
    permission_classes = [permissions.AllowAny]
    serializer_class = SocialLinkSerializer

    def get_queryset(self):
        return SocialLink.objects.filter(is_active=True)


class SideMenuItemListView(generics.ListAPIView):
    permission_classes = [permissions.AllowAny]
    serializer_class = SideMenuItemSerializer

    def get_queryset(self):
        return SideMenuItem.objects.filter(is_active=True)


class LatestContentView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        # Home ke "Naveenatam" tab ke liye sabhi latest sections ek response me bhejta hai.
        sections = [
            self.get_books_section(request),
            *self.get_magazine_sections(request),
            self.get_audio_section(request, "ऑडियो", None, "audio"),
            self.get_audio_section(request, "प्रवचन", "pravachan", "pravachan"),
            self.get_audio_section(request, "दैनिक सत्संग", "dainik-satsang", "satsang"),
            self.get_video_section(),
            self.get_amrit_vachan_section(request),
        ]
        return Response({"sections": [section for section in sections if section and section["items"]]})

    def get_books_section(self, request):
        queryset = (
            Book.objects.filter(is_published=True, magazine_issue__isnull=True)
            .exclude(category__slug__in=["patrika", "magazine"])
            .select_related("category")
            .order_by("-updated_at", "-id")
        )
        return {
            "key": "books",
            "title": "ई-पुस्तकें",
            "total": queryset.count(),
            "action": "books",
            "button_label": "पुस्तकें देखें",
            "items": BookListSerializer(queryset[:8], many=True, context={"request": request}).data,
        }

    def get_magazine_sections(self, request):
        sections = []
        magazines = Magazine.objects.filter(is_published=True).prefetch_related("issues").order_by("order", "title")
        for magazine in magazines[:4]:
            issues = (
                MagazineIssue.objects.filter(magazine=magazine, is_published=True)
                .select_related("magazine", "book", "book__category")
                .order_by("-updated_at", "order", "-year", "-issue_number")[:8]
            )
            sections.append(
                {
                    "key": f"magazine-{magazine.slug}",
                    "title": magazine.title,
                    "total": magazine.issues.filter(is_published=True).count(),
                    "action": "patrika",
                    "button_label": "पत्रिकाएं देखें",
                    "items": MagazineIssueSerializer(issues, many=True, context={"request": request}).data,
                }
            )
        return sections

    def get_audio_section(self, request, title, category_slug, action):
        queryset = AudioTrack.objects.filter(is_published=True).select_related("category", "speaker_ref")
        if category_slug:
            queryset = queryset.filter(category__slug=category_slug)
        else:
            queryset = queryset.exclude(category__slug__in=["pravachan", "dainik-satsang"])
        queryset = queryset.order_by("-created_at", "-id")
        return {
            "key": action,
            "title": title,
            "total": queryset.count(),
            "action": action,
            "button_label": f"{title} देखें",
            "items": AudioTrackSerializer(queryset[:8], many=True, context={"request": request}).data,
        }

    def get_video_section(self):
        try:
            feed = get_channel_videos(force_refresh=False)
            videos = (feed.get("videos") or [])[:6]
        except Exception:
            videos = []
        return {
            "key": "video",
            "title": "वीडियो",
            "total": len(videos),
            "action": "video",
            "button_label": "वीडियो देखें",
            "items": videos,
        }

    def get_amrit_vachan_section(self, request):
        queryset = AmritVachan.objects.filter(is_published=True).order_by("-quote_date", "-quote_number", "-id")
        return {
            "key": "amritVachan",
            "title": "अमृत वचन",
            "total": queryset.count(),
            "action": "amritVachan",
            "button_label": "अमृत वचन देखें",
            "items": AmritVachanSerializer(queryset[:8], many=True, context={"request": request}).data,
        }


class AuthorMenuView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        # Top "Lekhak" tab ke liye real backend authors/speakers ko group karke bhejta hai.
        sections = [
            self.get_book_authors(),
            self.get_audio_speakers("ऑडियो", "audio", exclude_special=True),
            self.get_audio_speakers("प्रवचन", "pravachan", category_slug="pravachan"),
        ]
        return Response(
            {
                "sections": [section for section in sections if section["items"]]
            }
        )

    def get_book_authors(self):
        rows = (
            Book.objects.filter(is_published=True, magazine_issue__isnull=True)
            .exclude(author="")
            .exclude(category__slug__in=["patrika", "magazine"])
            .values("author")
            .order_by("author")
            .distinct()
        )
        items = []
        for row in rows:
            author = row["author"]
            items.append(
                {
                    "id": author,
                    "name": author,
                    "count": Book.objects.filter(is_published=True, author=author).count(),
                    "type": "book",
                }
            )
        return {"key": "books", "title": "ई-पुस्तकें", "items": items}

    def get_audio_speakers(self, title, key, category_slug=None, exclude_special=False):
        queryset = AudioTrack.objects.filter(is_published=True).select_related("category", "speaker_ref")
        if category_slug:
            queryset = queryset.filter(category__slug=category_slug)
        if exclude_special:
            queryset = queryset.exclude(category__slug__in=["pravachan", "dainik-satsang"])

        speaker_rows = (
            queryset.exclude(speaker_ref=None)
            .values("speaker_ref_id", "speaker_ref__name")
            .distinct()
            .order_by("speaker_ref__name")
        )
        items = []
        used_names = set()
        for row in speaker_rows:
            speaker_name = row["speaker_ref__name"]
            used_names.add(speaker_name)
            items.append(
                {
                    "id": row["speaker_ref_id"],
                    "name": speaker_name,
                    "count": queryset.filter(speaker_ref_id=row["speaker_ref_id"]).count(),
                    "type": "audio",
                    "category_slug": category_slug or "",
                }
            )

        text_speakers = queryset.exclude(speaker="").values_list("speaker", flat=True).distinct().order_by("speaker")
        for speaker in text_speakers:
            if speaker in used_names:
                continue
            items.append(
                {
                    "id": speaker,
                    "name": speaker,
                    "count": queryset.filter(speaker=speaker).count(),
                    "type": "audio",
                    "category_slug": category_slug or "",
                }
            )
        return {"key": key, "title": title, "items": items}
