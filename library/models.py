from django.conf import settings
from django.db import models
from django.utils.text import slugify


class Category(models.Model):
    name = models.CharField(max_length=160)
    slug = models.SlugField(max_length=180, unique=True, blank=True)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ("order", "name")
        verbose_name_plural = "Categories"

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name, allow_unicode=True)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class AudioCategory(models.Model):
    name = models.CharField(max_length=160)
    slug = models.SlugField(max_length=180, unique=True, blank=True)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ("order", "name")
        verbose_name_plural = "Audio categories"

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name, allow_unicode=True)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class AudioSpeaker(models.Model):
    name = models.CharField(max_length=180)
    slug = models.SlugField(max_length=200, unique=True, blank=True)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ("order", "name")
        verbose_name_plural = "Audio speakers"

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name, allow_unicode=True)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class AudioTrack(models.Model):
    category = models.ForeignKey(
        AudioCategory,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="tracks",
    )
    title = models.CharField(max_length=240)
    slug = models.SlugField(max_length=240, unique=True, blank=True)
    speaker_ref = models.ForeignKey(
        AudioSpeaker,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="tracks",
    )
    speaker = models.CharField(max_length=180, blank=True)
    language = models.CharField(max_length=80, default="हिन्दी")
    duration = models.CharField(max_length=20, blank=True, help_text="Example: 00:15:39")
    audio_file = models.FileField(upload_to="audio_tracks/", blank=True, null=True)
    external_url = models.URLField(blank=True)
    description = models.TextField(blank=True)
    is_free = models.BooleanField(default=True)
    is_published = models.BooleanField(default=True)
    order = models.PositiveIntegerField(default=0)
    play_count = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("order", "title")
        indexes = [
            models.Index(fields=["is_published", "is_free", "order"], name="audio_free_order_idx"),
        ]

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.title, allow_unicode=True)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.title


class Magazine(models.Model):
    title = models.CharField(max_length=180)
    slug = models.SlugField(max_length=200, unique=True, blank=True)
    subtitle = models.CharField(max_length=180, blank=True)
    language = models.CharField(max_length=80, default="हिन्दी")
    cover_image = models.ImageField(upload_to="magazine_covers/", blank=True, null=True)
    cover_text = models.CharField(max_length=80, blank=True)
    is_published = models.BooleanField(default=True)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ("order", "title")

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.title, allow_unicode=True)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.title


class MagazineIssue(models.Model):
    magazine = models.ForeignKey(Magazine, on_delete=models.CASCADE, related_name="issues")
    title = models.CharField(max_length=220)
    slug = models.SlugField(max_length=240, unique=True, blank=True)
    year = models.CharField(max_length=20, blank=True)
    month = models.CharField(max_length=40, blank=True)
    issue_number = models.CharField(max_length=30, blank=True)
    language = models.CharField(max_length=80, default="हिन्दी")
    cover_image = models.ImageField(upload_to="magazine_issue_covers/", blank=True, null=True)
    pdf_file = models.FileField(upload_to="magazine_issue_pdfs/", blank=True, null=True)
    book = models.OneToOneField("Book", on_delete=models.SET_NULL, null=True, blank=True, related_name="magazine_issue")
    auto_extract_pdf = models.BooleanField(default=True)
    is_published = models.BooleanField(default=True)
    order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("order", "-year", "-issue_number", "title")

    def save(self, *args, **kwargs):
        if not self.slug:
            base_slug = f"{self.magazine.title}-{self.year}-{self.issue_number}".strip("-")
            self.slug = slugify(base_slug or self.title, allow_unicode=True)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.title


class Book(models.Model):
    title = models.CharField(max_length=220)
    slug = models.SlugField(max_length=240, unique=True, blank=True)
    category = models.ForeignKey(Category, on_delete=models.SET_NULL, null=True, related_name="books")
    language = models.CharField(max_length=80, default="हिन्दी")
    author = models.CharField(max_length=160, blank=True)
    description = models.TextField(blank=True)
    cover_image = models.ImageField(upload_to="book_covers/", blank=True, null=True)
    pdf_file = models.FileField(upload_to="book_pdfs/", blank=True, null=True)
    auto_extract_pdf = models.BooleanField(default=True)
    pdf_import_status = models.CharField(max_length=40, default="not_uploaded")
    pdf_page_count = models.PositiveIntegerField(default=0)
    is_published = models.BooleanField(default=True)
    order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("order", "title")

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.title, allow_unicode=True)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.title


class Chapter(models.Model):
    book = models.ForeignKey(Book, on_delete=models.CASCADE, related_name="chapters")
    title = models.CharField(max_length=220)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ("order", "id")
        indexes = [
            models.Index(fields=["book", "order", "id"], name="chap_book_order_idx"),
        ]

    def __str__(self):
        return f"{self.book.title} - {self.title}"


class BookPage(models.Model):
    chapter = models.ForeignKey(Chapter, on_delete=models.CASCADE, related_name="pages")
    title = models.CharField(max_length=220, blank=True)
    page_number = models.PositiveIntegerField(default=1)
    content = models.TextField()
    page_image = models.ImageField(upload_to="book_page_images/", blank=True, null=True)

    class Meta:
        ordering = ("page_number", "id")
        unique_together = ("chapter", "page_number")
        indexes = [
            models.Index(fields=["chapter", "page_number", "id"], name="page_chapter_num_idx"),
        ]

    def __str__(self):
        return f"{self.chapter.title} - Page {self.page_number}"


class FavoriteBook(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="favorite_books")
    book = models.ForeignKey(Book, on_delete=models.CASCADE, related_name="favorite_users")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("user", "book")

    def __str__(self):
        return f"{self.user} likes {self.book}"


class ReadingProgress(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="reading_progress")
    book = models.ForeignKey(Book, on_delete=models.CASCADE, related_name="reading_progress")
    chapter = models.ForeignKey(Chapter, on_delete=models.SET_NULL, null=True, blank=True)
    page = models.ForeignKey(BookPage, on_delete=models.SET_NULL, null=True, blank=True)
    progress_percent = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("user", "book")

    def __str__(self):
        return f"{self.user} - {self.book} - {self.progress_percent}%"


class AppUserProfile(models.Model):
    device_id = models.CharField(max_length=120, unique=True)
    name = models.CharField(max_length=160, blank=True)
    mobile = models.CharField(max_length=30, blank=True)
    email = models.EmailField(blank=True)
    language = models.CharField(max_length=60, default="Hindi")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-updated_at",)

    def __str__(self):
        return self.name or self.mobile or self.device_id


class AppRating(models.Model):
    device_id = models.CharField(max_length=120, unique=True)
    rating = models.PositiveSmallIntegerField(default=0)
    title = models.CharField(max_length=180, blank=True)
    review = models.TextField(blank=True)
    nickname = models.CharField(max_length=120, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-updated_at",)

    def __str__(self):
        return f"{self.device_id} - {self.rating}"


class ContactMessage(models.Model):
    device_id = models.CharField(max_length=120, blank=True)
    service_type = models.CharField(max_length=120, default="General Query")
    name = models.CharField(max_length=160)
    mobile = models.CharField(max_length=30)
    email = models.EmailField(blank=True)
    message = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self):
        return f"{self.name} - {self.service_type}"


class SocialLink(models.Model):
    name = models.CharField(max_length=80)
    label = models.CharField(max_length=120)
    icon = models.CharField(max_length=20, blank=True)
    url = models.URLField()
    color = models.CharField(max_length=20, default="#ff7a1a")
    order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ("order", "name")

    def __str__(self):
        return self.label
