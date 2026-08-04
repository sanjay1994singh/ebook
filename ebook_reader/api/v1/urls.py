from django.urls import path

from .views import (
    EbookDetailAPIView,
    EbookDiagnosticsAPIView,
    EbookLessonsAPIView,
    EbookListAPIView,
    EbookPdfAccessAPIView,
    EbookProgressAPIView,
    EbookReaderConfigAPIView,
)

urlpatterns = [
    path("", EbookListAPIView.as_view(), name="ebook_v1_list"),
    path("<int:pk>/", EbookDetailAPIView.as_view(), name="ebook_v1_detail"),
    path("<int:pk>/lessons/", EbookLessonsAPIView.as_view(), name="ebook_v1_lessons"),
    path(
        "<int:pk>/reader-config/",
        EbookReaderConfigAPIView.as_view(),
        name="ebook_v1_reader_config",
    ),
    path(
        "<int:pk>/pdf-access/",
        EbookPdfAccessAPIView.as_view(),
        name="ebook_v1_pdf_access",
    ),
    path(
        "<int:pk>/progress/",
        EbookProgressAPIView.as_view(),
        name="ebook_v1_progress",
    ),
    path(
        "<int:pk>/diagnostics/",
        EbookDiagnosticsAPIView.as_view(),
        name="ebook_v1_diagnostics",
    ),
]
