from rest_framework import generics
from rest_framework.response import Response
from rest_framework.views import APIView

from library.models import AudioTrack
from library.pagination import StandardResultsSetPagination
from library.serializers import AudioTrackSerializer

from .models import AmritVachan
from .serializers import AmritVachanSerializer


class AmritVachanListView(generics.ListAPIView):
    serializer_class = AmritVachanSerializer
    pagination_class = StandardResultsSetPagination

    def get_queryset(self):
        queryset = AmritVachan.objects.filter(is_published=True)
        ordering = self.request.query_params.get("ordering")
        if ordering == "oldest":
            return queryset.order_by("order", "quote_date", "quote_number", "id")
        return queryset


class CategoryAudioMixin:
    category_slug = None

    def get_base_queryset(self):
        return AudioTrack.objects.filter(
            is_published=True,
            category__slug=self.category_slug,
        ).select_related("category", "speaker_ref")


class CategoryAudioSpeakerListView(CategoryAudioMixin, APIView):
    def get(self, request):
        # Pravachan/Dainik Satsang ke liye speaker list return karta hai.
        queryset = self.get_base_queryset()
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

        text_speaker_names = queryset.exclude(speaker="").values_list("speaker", flat=True).distinct().order_by("speaker")
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


class CategoryAudioTrackListView(CategoryAudioMixin, generics.ListAPIView):
    serializer_class = AudioTrackSerializer
    pagination_class = StandardResultsSetPagination

    def get_queryset(self):
        queryset = self.get_base_queryset()
        speaker = self.request.query_params.get("speaker")
        if speaker:
            if str(speaker).isdigit():
                queryset = queryset.filter(speaker_ref_id=speaker)
            else:
                queryset = queryset.filter(speaker_ref__name=speaker) | queryset.filter(speaker=speaker)
        return queryset


class PravachanSpeakerListView(CategoryAudioSpeakerListView):
    category_slug = "pravachan"


class PravachanAudioListView(CategoryAudioTrackListView):
    category_slug = "pravachan"


class DainikSatsangSpeakerListView(CategoryAudioSpeakerListView):
    category_slug = "dainik-satsang"


class DainikSatsangAudioListView(CategoryAudioTrackListView):
    category_slug = "dainik-satsang"
