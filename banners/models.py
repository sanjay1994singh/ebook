from pathlib import Path

from django.db import models
from django.utils.text import slugify
from PIL import Image


class Banner(models.Model):
    DEVICE_ALL = "all"
    DEVICE_MOBILE = "mobile"
    DEVICE_DESKTOP = "desktop"
    DEVICE_CHOICES = (
        (DEVICE_ALL, "Mobile and desktop"),
        (DEVICE_MOBILE, "Mobile only"),
        (DEVICE_DESKTOP, "Desktop only"),
    )

    title = models.CharField(max_length=220)
    slug = models.SlugField(max_length=240, unique=True, blank=True)
    mobile_image = models.ImageField(upload_to="banners/mobile/", blank=True, null=True)
    desktop_image = models.ImageField(upload_to="banners/desktop/", blank=True, null=True)
    device = models.CharField(max_length=20, choices=DEVICE_CHOICES, default=DEVICE_ALL)
    link_url = models.URLField(blank=True)
    is_published = models.BooleanField(default=True)
    order = models.PositiveIntegerField(default=0)
    starts_at = models.DateTimeField(blank=True, null=True)
    ends_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("order", "-id")
        verbose_name = "Banner ad"
        verbose_name_plural = "Banner ads"

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.title, allow_unicode=True)[:220] or "banner"
        super().save(*args, **kwargs)
        self.compress_uploaded_images()

    def compress_uploaded_images(self):
        # Admin se upload image ko lightweight banata hai, taaki app fast load ho.
        self.compress_image_file(self.mobile_image, max_width=900, quality=78)
        self.compress_image_file(self.desktop_image, max_width=1600, quality=80)

    @staticmethod
    def compress_image_file(image_field, max_width, quality):
        if not image_field:
            return

        image_path = Path(image_field.path)
        if not image_path.exists():
            return

        with Image.open(image_path) as image:
            image_format = image.format or "JPEG"
            if image.mode not in ("RGB", "RGBA"):
                image = image.convert("RGB")

            if image.width > max_width:
                new_height = int((max_width / image.width) * image.height)
                image = image.resize((max_width, new_height), Image.Resampling.LANCZOS)

            save_kwargs = {"optimize": True}
            if image_format.upper() in {"JPEG", "JPG", "WEBP"}:
                if image.mode == "RGBA":
                    image = image.convert("RGB")
                save_kwargs["quality"] = quality

            image.save(image_path, format=image_format, **save_kwargs)

    def __str__(self):
        return self.title
