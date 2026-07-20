from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("auth/", include("social_django.urls", namespace="social")),
    path("", include("library.web_urls")),
    path("api/auth/", include("accounts.urls")),
    path("api/audio/", include("library.audio_urls")),
    path("api/banners/", include("banners.urls")),
    path("api/books/", include("library.urls")),
    path("api/content/", include("content.urls")),
    path("api/youtube/", include("youtube_feed.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
