from django.urls import path

from .views import YoutubeFeedView


urlpatterns = [
    path("", YoutubeFeedView.as_view(), name="youtube_feed"),
]
