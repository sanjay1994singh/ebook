# Generated manually for the line-oriented ebook reader.
import ckeditor.fields
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("ebook_reader", "0007_ebookdocument_new_ebook_reader_enabled_and_more"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="Book",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("title", models.CharField(max_length=255)),
                ("author", models.CharField(blank=True, max_length=255)),
                ("pdf_file", models.FileField(upload_to="ebooks/pdfs/")),
                ("uploaded_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={"ordering": ("title", "id")},
        ),
        migrations.CreateModel(
            name="BookPage",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("page_number", models.PositiveIntegerField()),
                ("content", ckeditor.fields.RichTextField()),
                ("book", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="pages", to="ebook_reader.book")),
            ],
            options={"ordering": ("page_number",)},
        ),
        migrations.CreateModel(
            name="IndexItem",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("title", models.CharField(max_length=255)),
                ("start_page", models.PositiveIntegerField()),
                ("end_page", models.PositiveIntegerField()),
                ("book", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="index_items", to="ebook_reader.book")),
            ],
            options={"ordering": ("start_page",)},
        ),
        migrations.CreateModel(
            name="Highlight",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("selected_text", models.TextField()),
                ("color", models.CharField(default="yellow", max_length=20)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("page", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="highlights", to="ebook_reader.bookpage")),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="ebook_highlights", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ("-created_at", "-id")},
        ),
        migrations.AddConstraint(
            model_name="bookpage",
            constraint=models.UniqueConstraint(fields=("book", "page_number"), name="ebook_reader_unique_book_page"),
        ),
        migrations.AddConstraint(
            model_name="indexitem",
            constraint=models.CheckConstraint(check=models.Q(("end_page__gte", models.F("start_page"))), name="ebook_reader_index_end_gte_start"),
        ),
        migrations.AddIndex(
            model_name="highlight",
            index=models.Index(fields=["user", "page"], name="ebook_highlight_user_page_idx"),
        ),
    ]
