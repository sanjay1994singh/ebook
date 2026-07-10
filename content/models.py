from django.db import models
from django.utils.text import slugify


class AmritVachan(models.Model):
    title = models.CharField(max_length=220)
    slug = models.SlugField(max_length=240, unique=True, blank=True)
    quote_number = models.PositiveIntegerField(default=0, help_text="Example: 2151")
    quote_date = models.DateField(blank=True, null=True)
    image = models.ImageField(upload_to="amrit_vachan/")
    hindi_text = models.TextField(blank=True)
    english_text = models.TextField(blank=True)
    is_published = models.BooleanField(default=True)
    order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("order", "-quote_date", "-quote_number", "-id")
        verbose_name = "Amrit vachan"
        verbose_name_plural = "Amrit vachan"

    def save(self, *args, **kwargs):
        if not self.slug:
            base_slug = f"{self.title}-{self.quote_number}".strip("-")
            self.slug = slugify(base_slug, allow_unicode=True)[:220] or "amrit-vachan"
        super().save(*args, **kwargs)

    def __str__(self):
        return self.title
