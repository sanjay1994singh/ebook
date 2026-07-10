from django.contrib import admin

from .models import AmritVachan


@admin.register(AmritVachan)
class AmritVachanAdmin(admin.ModelAdmin):
    list_display = ("title", "quote_number", "quote_date", "is_published", "order")
    list_filter = ("is_published", "quote_date")
    search_fields = ("title", "hindi_text", "english_text")
    prepopulated_fields = {"slug": ("title",)}
    list_editable = ("is_published", "order")
