from django.db.models import Count, Prefetch, Q
from rest_framework.authentication import SessionAuthentication
from rest_framework import generics, permissions, views
from rest_framework.response import Response
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework.exceptions import NotFound

from ebook_reader.api.v1.permissions import CanAccessReadyEbook, StaffDiagnosticsPermission
from ebook_reader.api.v1.serializers import (
    EbookDetailSerializer,
    EbookDiagnosticsSerializer,
    EbookLessonPublicSerializer,
    EbookListSerializer,
    EbookProgressSerializer,
    EbookProgressUpdateSerializer,
    EbookReaderConfigSerializer,
    progress_response_for,
)
from ebook_reader.models import EbookDocument, EbookLesson, EbookReadingProgress
from ebook_reader.services.pdf_delivery import build_pdf_streaming_response
from ebook_reader.services.feature_flags import (
    ebook_system_enabled,
    is_staff_user,
    mobile_reader_globally_enabled,
    staff_only_enabled,
)
from library.pagination import StandardResultsSetPagination


class EbookQuerysetMixin:
    def base_queryset(self):
        if not ebook_system_enabled() or not mobile_reader_globally_enabled():
            return EbookDocument.objects.none()
        queryset = (
            EbookDocument.objects.select_related("book", "book__category")
            .annotate(
                lesson_count=Count(
                    "lessons",
                    filter=Q(
                        lessons__is_verified=True,
                        lessons__start_page__isnull=False,
                    ),
                    distinct=True,
                )
            )
            .prefetch_related(
                Prefetch(
                    "lessons",
                    queryset=EbookLesson.objects.filter(
                        is_verified=True,
                        start_page__isnull=False,
                    ).order_by("order", "id"),
                )
            )
        )
        user = self.request.user
        if staff_only_enabled() and not is_staff_user(user):
            return EbookDocument.objects.none()
        if not (user and user.is_staff):
            queryset = queryset.filter(
                status=EbookDocument.Status.READY,
                book__is_published=True,
            )
        queryset = queryset.filter(
            new_ebook_reader_enabled=True,
            new_ebook_reader_mobile_enabled=True,
        ).exclude(book__pdf_file="")
        return queryset

    def with_user_progress(self, queryset):
        user = self.request.user
        if not (user and user.is_authenticated):
            return queryset
        items = list(queryset)
        ebook_ids = [ebook.id for ebook in items]
        progress_map = {
            progress.ebook_document_id: progress
            for progress in EbookReadingProgress.objects.filter(
                user=user,
                ebook_document_id__in=ebook_ids,
            ).select_related("current_lesson")
        }
        for ebook in items:
            ebook._user_progress = progress_map.get(ebook.id)
        return queryset


class EbookListAPIView(EbookQuerysetMixin, generics.ListAPIView):
    serializer_class = EbookListSerializer
    pagination_class = StandardResultsSetPagination
    permission_classes = [permissions.AllowAny]

    def get_queryset(self):
        queryset = self.base_queryset().order_by("book__order", "book__title", "id")
        search = self.request.query_params.get("search")
        category = self.request.query_params.get("category")
        if search:
            queryset = queryset.filter(book__title__icontains=search)
        if category:
            queryset = queryset.filter(book__category__slug=category)
        return queryset

    def paginate_queryset(self, queryset):
        page = super().paginate_queryset(queryset)
        if page is not None:
            self.with_user_progress(page)
        return page


class EbookDetailAPIView(EbookQuerysetMixin, generics.RetrieveAPIView):
    serializer_class = EbookDetailSerializer
    permission_classes = [CanAccessReadyEbook]

    def get_queryset(self):
        return self.base_queryset()

    def get_object(self):
        obj = super().get_object()
        self.check_object_permissions(self.request, obj)
        self.with_user_progress([obj])
        return obj


class EbookLessonsAPIView(EbookQuerysetMixin, generics.ListAPIView):
    serializer_class = EbookLessonPublicSerializer
    pagination_class = None
    permission_classes = [CanAccessReadyEbook]

    def get_ebook(self):
        ebook = self.base_queryset().filter(id=self.kwargs["pk"]).first()
        if not ebook:
            raise NotFound()
        self.check_object_permissions(self.request, ebook)
        return ebook

    def get_queryset(self):
        return self.get_ebook().lessons.filter(
            is_verified=True,
            start_page__isnull=False,
        ).order_by("order", "id")


class EbookReaderConfigAPIView(EbookQuerysetMixin, generics.RetrieveAPIView):
    serializer_class = EbookReaderConfigSerializer
    permission_classes = [CanAccessReadyEbook]

    def get_queryset(self):
        return self.base_queryset()

    def get_object(self):
        obj = super().get_object()
        self.check_object_permissions(self.request, obj)
        return obj


class EbookPdfAccessAPIView(EbookQuerysetMixin, views.APIView):
    permission_classes = [CanAccessReadyEbook]

    def get_ebook(self):
        ebook = self.base_queryset().filter(id=self.kwargs["pk"]).first()
        if not ebook:
            raise NotFound()
        self.check_object_permissions(self.request, ebook)
        return ebook

    def get(self, request, *args, **kwargs):
        return build_pdf_streaming_response(self.get_ebook(), request)

    def head(self, request, *args, **kwargs):
        return build_pdf_streaming_response(self.get_ebook(), request, head_only=True)


class EbookProgressAPIView(EbookQuerysetMixin, views.APIView):
    authentication_classes = [JWTAuthentication, SessionAuthentication]
    permission_classes = [permissions.IsAuthenticated, CanAccessReadyEbook]

    def get_ebook(self):
        ebook = self.base_queryset().filter(id=self.kwargs["pk"]).first()
        if not ebook:
            raise NotFound()
        self.check_object_permissions(self.request, ebook)
        return ebook

    def get(self, request, *args, **kwargs):
        ebook = self.get_ebook()
        serializer = EbookProgressSerializer(progress_response_for(ebook, request.user))
        return Response(serializer.data)

    def patch(self, request, *args, **kwargs):
        return self._update_progress(request)

    def put(self, request, *args, **kwargs):
        return self._update_progress(request)

    def _update_progress(self, request):
        ebook = self.get_ebook()
        serializer = EbookProgressUpdateSerializer(
            data=request.data,
            context={"request": request, "ebook": ebook},
        )
        serializer.is_valid(raise_exception=True)
        progress = serializer.save()
        return Response(EbookProgressSerializer(progress).data)


class EbookDiagnosticsAPIView(EbookQuerysetMixin, generics.RetrieveAPIView):
    serializer_class = EbookDiagnosticsSerializer
    permission_classes = [StaffDiagnosticsPermission]

    def get_queryset(self):
        return self.base_queryset()
