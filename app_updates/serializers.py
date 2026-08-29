from rest_framework import serializers

from .models import AppBuildRelease


class AppBuildReleaseSerializer(serializers.ModelSerializer):
    update_url = serializers.SerializerMethodField()

    class Meta:
        model = AppBuildRelease
        fields = (
            "id",
            "platform",
            "channel",
            "version_name",
            "version_code",
            "title",
            "release_notes",
            "update_url",
            "play_store_url",
            "is_required",
            "rollout_percent",
            "created_at",
        )

    def get_update_url(self, obj):
        request = self.context.get("request")
        if obj.channel == AppBuildRelease.CHANNEL_PLAY_STORE and obj.play_store_url:
            return obj.play_store_url
        if obj.artifact_file and request:
            return request.build_absolute_uri(obj.artifact_file.url)
        return obj.artifact_url or obj.play_store_url
