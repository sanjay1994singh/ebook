from django.urls import path

from .views import AudioCategoryListView, AudioTrackListView, FreeAudioTrackListView


urlpatterns = [
    path("categories/", AudioCategoryListView.as_view(), name="audio_category_list"),
    path("free/", FreeAudioTrackListView.as_view(), name="free_audio_track_list"),
    path("", AudioTrackListView.as_view(), name="audio_track_list"),
]
