from django.db.models import Q
from django.utils import timezone
from rest_framework import generics

from .models import Banner
from .serializers import BannerSerializer


class BannerListView(generics.ListAPIView):
    serializer_class = BannerSerializer

    def get_queryset(self):
        now = timezone.now()
        device = self.request.query_params.get("device", "mobile")
        device_filter = [Banner.DEVICE_ALL]
        if device == Banner.DEVICE_DESKTOP:
            device_filter.append(Banner.DEVICE_DESKTOP)
        else:
            device_filter.append(Banner.DEVICE_MOBILE)

        return (
            Banner.objects.filter(is_published=True, device__in=device_filter)
            .filter(Q(starts_at__isnull=True) | Q(starts_at__lte=now))
            .filter(Q(ends_at__isnull=True) | Q(ends_at__gte=now))
            .exclude(mobile_image="", desktop_image="")
            .order_by("order", "-id")
        )
