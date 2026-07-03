from django.contrib import admin

from .models import Book, BookPage, Category, Chapter, FavoriteBook, ReadingProgress
from .pdf_importer import extract_pdf_to_book


class ChapterInline(admin.TabularInline):
    model = Chapter
    extra = 1


class BookPageInline(admin.TabularInline):
    model = BookPage
    extra = 1


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "order")
    prepopulated_fields = {"slug": ("name",)}


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
