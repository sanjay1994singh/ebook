from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("library", "0002_book_auto_extract_pdf_book_pdf_file_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="bookpage",
            name="page_image",
            field=models.ImageField(blank=True, null=True, upload_to="book_page_images/"),
        ),
    ]
