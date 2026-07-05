from django.contrib import admin

from .models import (
    AudioCategory,
    AudioSpeaker,
    AudioTrack,
    Book,
    BookPage,
    Category,
    Chapter,
    FavoriteBook,
    Magazine,
    MagazineIssue,
    ReadingProgress,
)
from .pdf_importer import extract_pdf_to_book


class ChapterInline(admin.TabularInline):
    model = Chapter
    extra = 1


class BookPageInline(admin.TabularInline):
    model = BookPage
    extra = 1


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "order")
    prepopulated_fields = {"slug": ("name",)}


@admin.register(AudioCategory)
class AudioCategoryAdmin(admin.ModelAdmin):
    list_display = ("id","name", "slug", "order")
    prepopulated_fields = {"slug": ("name",)}


@admin.register(AudioSpeaker)
class AudioSpeakerAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "slug", "order")
    search_fields = ("name",)
    prepopulated_fields = {"slug": ("name",)}


@admin.register(AudioTrack)
class AudioTrackAdmin(admin.ModelAdmin):
    list_display = ("title", "speaker_name", "category", "duration", "is_free", "is_published", "order")
    list_filter = ("category", "speaker_ref", "language", "is_free", "is_published")
    search_fields = ("title", "speaker", "speaker_ref__name", "description")
    prepopulated_fields = {"slug": ("title",)}

    def speaker_name(self, obj):
        return obj.speaker_ref.name if obj.speaker_ref else obj.speaker


class MagazineIssueInline(admin.TabularInline):
    model = MagazineIssue
    extra = 1
    fields = ("title", "year", "month", "issue_number", "is_published", "order")


@admin.register(Magazine)
class MagazineAdmin(admin.ModelAdmin):
    list_display = ("title", "language", "is_published", "order")
    list_filter = ("language", "is_published")
    search_fields = ("title", "subtitle")
    prepopulated_fields = {"slug": ("title",)}
    inlines = [MagazineIssueInline]


@admin.register(MagazineIssue)
class MagazineIssueAdmin(admin.ModelAdmin):
    list_display = ("title", "magazine", "year", "month", "issue_number", "is_published", "order")
    list_filter = ("magazine", "language", "is_published")
    search_fields = ("title", "magazine__title")
    prepopulated_fields = {"slug": ("title",)}
    actions = ["extract_selected_issue_pdfs"]

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        book = self._sync_issue_book(obj)
        if obj.pdf_file and obj.auto_extract_pdf and ("pdf_file" in form.changed_data or not change):
            pages = extract_pdf_to_book(book)
            self.message_user(request, f"Magazine issue PDF imported successfully. {pages} pages created.")

    def _sync_issue_book(self, issue):
        category, _created = Category.objects.get_or_create(
            slug="patrika",
            defaults={"name": "पत्रिकाएं", "order": 50},
        )
        book = issue.book or Book()
        book.title = issue.title
        book.slug = f"patrika-{issue.slug}"[:240]
        book.category = category
        book.language = issue.language
        book.is_published = issue.is_published
        book.order = issue.order
        if issue.pdf_file:
            book.pdf_file = issue.pdf_file
        if issue.cover_image:
            book.cover_image = issue.cover_image
        book.auto_extract_pdf = False
        book.save()
        if issue.book_id != book.id:
            issue.book = book
            issue.save(update_fields=["book", "updated_at"])
        return book

    @admin.action(description="Extract PDF pages for selected patrika issues")
    def extract_selected_issue_pdfs(self, request, queryset):
        total_pages = 0
        total_issues = 0
        for issue in queryset:
            if not issue.pdf_file:
                continue
            book = self._sync_issue_book(issue)
            total_pages += extract_pdf_to_book(book)
            total_issues += 1
        self.message_user(request, f"Imported {total_pages} pages from {total_issues} patrika issues.")


@admin.register(Book)
class BookAdmin(admin.ModelAdmin):
    list_display = ("title", "category", "language", "pdf_import_status", "pdf_page_count", "is_published", "order")
    list_filter = ("category", "language", "pdf_import_status", "is_published")
    search_fields = ("title", "author", "description")
    prepopulated_fields = {"slug": ("title",)}
    inlines = [ChapterInline]
    actions = ["extract_selected_pdfs"]

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        if obj.pdf_file and obj.auto_extract_pdf and "pdf_file" in form.changed_data:
            pages = extract_pdf_to_book(obj)
            self.message_user(request, f"PDF imported successfully. {pages} pages created.")

    @admin.action(description="Extract PDF pages for selected books")
    def extract_selected_pdfs(self, request, queryset):
        total_pages = 0
        total_books = 0
        for book in queryset:
            if not book.pdf_file:
                continue
            total_pages += extract_pdf_to_book(book)
            total_books += 1
        self.message_user(request, f"Imported {total_pages} pages from {total_books} books.")


@admin.register(Chapter)
class ChapterAdmin(admin.ModelAdmin):
    list_display = ("title", "book", "order")
    list_filter = ("book",)
    inlines = [BookPageInline]


@admin.register(BookPage)
class BookPageAdmin(admin.ModelAdmin):
    list_display = ("title", "chapter", "page_number")
    list_filter = ("chapter__book", "chapter")
    search_fields = ("title", "content")


@admin.register(FavoriteBook)
class FavoriteBookAdmin(admin.ModelAdmin):
    list_display = ("user", "book", "created_at")


@admin.register(ReadingProgress)
class ReadingProgressAdmin(admin.ModelAdmin):
    list_display = ("user", "book", "chapter", "page", "progress_percent", "updated_at")
