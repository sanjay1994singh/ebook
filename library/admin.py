from pathlib import Path
import shutil
import subprocess
import tempfile

from django.contrib import admin
from django.contrib import messages
from django.core.files import File
from django.shortcuts import redirect, render
from django.urls import path, reverse
from django.utils.html import format_html
from django.utils.text import slugify

from .forms import AudioTrackBulkUploadForm
from .models import (
    AudioCategory,
    AudioSpeaker,
    AudioTrack,
    AppRating,
    AppUserProfile,
    Book,
    BookPage,
    Category,
    Chapter,
    ContactMessage,
    FavoriteBook,
    Magazine,
    MagazineIssue,
    ReadingProgress,
    SocialLink,
    SideMenuItem,
    Subject,
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


@admin.register(Subject)
class SubjectAdmin(admin.ModelAdmin):
    list_display = ("name", "order", "is_active")
    list_filter = ("is_active",)
    search_fields = ("name",)
    prepopulated_fields = {"slug": ("name",)}


@admin.register(AudioCategory)
class AudioCategoryAdmin(admin.ModelAdmin):
    list_display = ("id","name", "order")
    prepopulated_fields = {"slug": ("name",)}


@admin.register(AudioSpeaker)
class AudioSpeakerAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "slug", "order")
    search_fields = ("name",)
    prepopulated_fields = {"slug": ("name",)}


@admin.register(AudioTrack)
class AudioTrackAdmin(admin.ModelAdmin):
    change_list_template = "admin/library/audiotrack/change_list.html"
    list_display = ("title", "speaker_name", "category", "duration", "is_free", "is_published", "order")
    list_filter = ("category", "speaker_ref", "language", "is_free", "is_published")
    search_fields = ("title", "speaker", "speaker_ref__name", "description")
    prepopulated_fields = {"slug": ("title",)}

    def speaker_name(self, obj):
        return obj.speaker_ref.name if obj.speaker_ref else obj.speaker

    def bulk_upload_link(self):
        url = reverse("admin:library_audiotrack_bulk_upload")
        return format_html('<a class="button" href="{}">Bulk upload audio</a>', url)

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                "bulk-upload/",
                self.admin_site.admin_view(self.bulk_upload_view),
                name="library_audiotrack_bulk_upload",
            )
        ]
        return custom_urls + urls

    def bulk_upload_view(self, request):
        if request.method == "POST":
            form = AudioTrackBulkUploadForm(request.POST, request.FILES)
            if form.is_valid():
                try:
                    created_count, skipped_count, failed_count = self._save_bulk_audio(form)
                    messages.success(
                        request,
                        f"Bulk upload complete. created={created_count}, skipped={skipped_count}, failed={failed_count}",
                    )
                    return redirect("admin:library_audiotrack_changelist")
                except Exception as error:
                    messages.error(request, str(error))
        else:
            form = AudioTrackBulkUploadForm()

        context = {
            **self.admin_site.each_context(request),
            "opts": self.model._meta,
            "title": "Bulk upload audio tracks",
            "form": form,
        }
        return render(request, "admin/library/audiotrack/bulk_upload.html", context)

    def _save_bulk_audio(self, form):
        category = form.cleaned_data["category"]
        speaker = form.cleaned_data["speaker"]
        language = form.cleaned_data["language"]
        audio_files = form.cleaned_data["audio_files"]
        should_compress = form.cleaned_data["compress"]
        bitrate = form.cleaned_data["bitrate"]
        is_free = form.cleaned_data["is_free"]
        is_published = form.cleaned_data["is_published"]

        if should_compress and not shutil.which("ffmpeg"):
            raise RuntimeError("ffmpeg not found. Install ffmpeg or uncheck compress.")

        created_count = 0
        skipped_count = 0
        failed_count = 0
        order_start = AudioTrack.objects.filter(category=category, speaker_ref=speaker).count()

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_dir_path = Path(temp_dir)
            for index, uploaded_file in enumerate(audio_files, start=1):
                title = self._title_from_filename(uploaded_file.name)
                if self._audio_already_exists(title, uploaded_file.name, category.id, speaker.id):
                    skipped_count += 1
                    continue

                try:
                    import_path = self._write_uploaded_file(uploaded_file, temp_dir_path)
                    import_filename = Path(uploaded_file.name).name
                    if should_compress:
                        import_path = self._compress_audio(import_path, temp_dir_path, bitrate)
                        import_filename = f"{Path(uploaded_file.name).stem}.mp3"

                    audio_track = AudioTrack(
                        category=category,
                        speaker_ref=speaker,
                        speaker=speaker.name,
                        title=title,
                        slug=self._unique_slug(title),
                        language=language,
                        is_free=is_free,
                        is_published=is_published,
                        order=order_start + index,
                    )

                    with import_path.open("rb") as audio_file:
                        audio_track.audio_file.save(import_filename, File(audio_file), save=True)
                    created_count += 1
                except Exception:
                    failed_count += 1

        return created_count, skipped_count, failed_count

    def _write_uploaded_file(self, uploaded_file, temp_dir_path):
        file_path = temp_dir_path / Path(uploaded_file.name).name
        with file_path.open("wb") as destination:
            for chunk in uploaded_file.chunks():
                destination.write(chunk)
        return file_path

    def _compress_audio(self, audio_path, temp_dir_path, bitrate):
        output_path = temp_dir_path / f"{audio_path.stem}-compressed.mp3"
        command = [
            "ffmpeg",
            "-y",
            "-i",
            str(audio_path),
            "-vn",
            "-codec:a",
            "libmp3lame",
            "-b:a",
            bitrate,
            str(output_path),
        ]
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or f"ffmpeg failed for {audio_path.name}")
        return output_path

    def _title_from_filename(self, filename):
        title = Path(filename).stem
        title = title.replace("_", " ").replace("-", " ")
        return " ".join(title.split())

    def _unique_slug(self, title):
        base_slug = slugify(title, allow_unicode=True)[:220] or "audio"
        slug = base_slug
        counter = 2
        while AudioTrack.objects.filter(slug=slug).exists():
            suffix = f"-{counter}"
            slug = f"{base_slug[: 240 - len(suffix)]}{suffix}"
            counter += 1
        return slug

    def _audio_already_exists(self, title, filename, category_id, speaker_id):
        if AudioTrack.objects.filter(
            title__iexact=title,
            category_id=category_id,
            speaker_ref_id=speaker_id,
        ).exists():
            return True

        new_file_key = self._normalize_duplicate_key(Path(filename).stem)
        existing_tracks = AudioTrack.objects.filter(category_id=category_id, speaker_ref_id=speaker_id).exclude(audio_file="")
        for track in existing_tracks:
            existing_name = Path(track.audio_file.name).stem
            keys = {
                self._normalize_duplicate_key(track.title),
                self._normalize_duplicate_key(track.slug),
                self._normalize_duplicate_key(existing_name),
            }
            if new_file_key in keys:
                return True
        return False

    def _normalize_duplicate_key(self, value):
        return "".join(character for character in str(value).lower() if character.isalnum())


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
    list_filter = ("category", "subjects", "language", "pdf_import_status", "is_published")
    search_fields = ("title", "author", "description")
    prepopulated_fields = {"slug": ("title",)}
    filter_horizontal = ("subjects",)
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


@admin.register(AppUserProfile)
class AppUserProfileAdmin(admin.ModelAdmin):
    list_display = ("device_id", "name", "mobile", "email", "language", "updated_at")
    search_fields = ("device_id", "name", "mobile", "email")


@admin.register(AppRating)
class AppRatingAdmin(admin.ModelAdmin):
    list_display = ("device_id", "rating", "nickname", "title", "updated_at")
    list_filter = ("rating",)
    search_fields = ("device_id", "nickname", "title", "review")


@admin.register(ContactMessage)
class ContactMessageAdmin(admin.ModelAdmin):
    list_display = ("name", "mobile", "service_type", "email", "created_at")
    list_filter = ("service_type",)
    search_fields = ("name", "mobile", "email", "message", "device_id")


@admin.register(SocialLink)
class SocialLinkAdmin(admin.ModelAdmin):
    list_display = ("label", "name", "url", "order", "is_active")
    list_filter = ("is_active",)
    search_fields = ("label", "name", "url")


@admin.register(SideMenuItem)
class SideMenuItemAdmin(admin.ModelAdmin):
    list_display = ("title", "section", "icon", "action", "order", "is_active")
    list_filter = ("section", "is_active")
    search_fields = ("title", "section", "action", "url")
