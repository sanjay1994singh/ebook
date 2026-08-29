from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("library", "0014_remove_appbuildrelease_state"),
    ]

    operations = [
        migrations.AddField(
            model_name="chapter",
            name="end_page",
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="chapter",
            name="start_page",
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
        migrations.AddIndex(
            model_name="chapter",
            index=models.Index(fields=["book", "start_page", "end_page"], name="chap_book_page_range_idx"),
        ),
    ]
