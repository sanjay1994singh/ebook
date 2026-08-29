from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import AppBuildRelease
from .serializers import AppBuildReleaseSerializer


class AppLatestBuildView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        platform = request.query_params.get("platform") or AppBuildRelease.PLATFORM_ANDROID
        channel = request.query_params.get("channel") or AppBuildRelease.CHANNEL_PLAY_STORE
        try:
            current_version_code = int(request.query_params.get("version_code") or 0)
        except (TypeError, ValueError):
            current_version_code = 0

        latest = (
            AppBuildRelease.objects.filter(platform=platform, channel=channel, is_active=True)
            .filter(rollout_percent__gt=0)
            .order_by("-version_code", "-created_at")
            .first()
        )
        if not latest:
            return Response(
                {
                    "update_available": False,
                    "current_version_code": current_version_code,
                    "latest": None,
                }
            )

        return Response(
            {
                "update_available": latest.version_code > current_version_code,
                "current_version_code": current_version_code,
                "latest": AppBuildReleaseSerializer(latest, context={"request": request}).data,
            }
        )
