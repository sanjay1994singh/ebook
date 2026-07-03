from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import User


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    list_display = ("username", "email", "phone", "preferred_language", "is_staff")
    fieldsets = UserAdmin.fieldsets + (
        ("Ebook Profile", {"fields": ("phone", "profile_image", "preferred_language")}),
    )
