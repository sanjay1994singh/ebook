from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("library", "0003_bookpage_page_image"),
    ]

    operations = [
        migrations.AddIndex(
            model_name="chapter",
            index=models.Index(fields=["book", "order", "id"], name="chap_book_order_idx"),
        ),
        migrations.AddIndex(
            model_name="bookpage",
            index=models.Index(fields=["chapter", "page_number", "id"], name="page_chapter_num_idx"),
        ),
    ]
