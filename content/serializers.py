from rest_framework import serializers

from .models import AmritVachan


class AmritVachanSerializer(serializers.ModelSerializer):
    image_url = serializers.SerializerMethodField()

    class Meta:
        model = AmritVachan
        fields = (
            "id",
            "title",
            "slug",
            "quote_number",
            "quote_date",
            "image_url",
            "hindi_text",
            "english_text",
            "order",
        )

    def get_image_url(self, obj):
        request = self.context.get("request")
        if obj.image and request:
            return request.build_absolute_uri(obj.image.url)
        return None
