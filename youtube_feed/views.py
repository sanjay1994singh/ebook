from rest_framework.response import Response
from rest_framework.views import APIView

from .services import get_channel_videos


class YoutubeFeedView(APIView):
    def get(self, request):
        # kind=all|shorts|videos ke hisab se response deta hai.
        force_refresh = request.query_params.get("refresh") == "1"
        payload = get_channel_videos(force_refresh=force_refresh)
        kind = request.query_params.get("kind", "all")
        if kind == "shorts":
            return Response({"channel": payload["channel"], "results": payload["shorts"]})
        if kind in {"videos", "long"}:
            return Response({"channel": payload["channel"], "results": payload["videos"]})
        return Response(payload)
