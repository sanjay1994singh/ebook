from django.urls import path

from .views import (
    AmritVachanListView,
    DainikSatsangAudioListView,
    DainikSatsangSpeakerListView,
    PravachanAudioListView,
    PravachanSpeakerListView,
)


urlpatterns = [
    path("amrit-vachan/", AmritVachanListView.as_view(), name="amrit_vachan_list"),
    path("pravachan/speakers/", PravachanSpeakerListView.as_view(), name="pravachan_speakers"),
    path("pravachan/audios/", PravachanAudioListView.as_view(), name="pravachan_audios"),
    path("dainik-satsang/speakers/", DainikSatsangSpeakerListView.as_view(), name="dainik_satsang_speakers"),
    path("dainik-satsang/audios/", DainikSatsangAudioListView.as_view(), name="dainik_satsang_audios"),
]
