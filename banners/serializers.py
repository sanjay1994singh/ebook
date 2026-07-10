from rest_framework import serializers

from .models import Banner


class BannerSerializer(serializers.ModelSerializer):
    image_url = serializers.SerializerMethodField()
    mobile_image_url = serializers.SerializerMethodField()
    desktop_image_url = serializers.SerializerMethodField()

    class Meta:
        model = Banner
        fields = (
            "id",
            "title",
            "slug",
            "device",
            "image_url",
            "mobile_image_url",
            "desktop_image_url",
            "link_url",
            "order",
        )

    def get_image_url(self, obj):
        request = self.context.get("request")
        device = (request.query_params.get("device") if request else "") or "mobile"
        image = obj.desktop_image if device == "desktop" else obj.mobile_image
        if not image:
            image = obj.mobile_image or obj.desktop_image
        if image and request:
            return request.build_absolute_uri(image.url)
        return None

    def get_mobile_image_url(self, obj):
        request = self.context.get("request")
        if obj.mobile_image and request:
            return request.build_absolute_uri(obj.mobile_image.url)
        return None

    def get_desktop_image_url(self, obj):
        request = self.context.get("request")
        if obj.desktop_image and request:
            return request.build_absolute_uri(obj.desktop_image.url)
        return None
