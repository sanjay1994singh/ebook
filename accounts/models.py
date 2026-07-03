from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    # Extra fields for mobile app users.
    phone = models.CharField(max_length=20, blank=True)
    profile_image = models.ImageField(upload_to="profiles/", blank=True, null=True)
    preferred_language = models.CharField(max_length=50, default="हिन्दी")

    def __str__(self):
        return self.get_full_name() or self.username
