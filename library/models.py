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
