from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="Banner",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("title", models.CharField(max_length=220)),
                ("slug", models.SlugField(blank=True, max_length=240, unique=True)),
                ("mobile_image", models.ImageField(blank=True, null=True, upload_to="banners/mobile/")),
                ("desktop_image", models.ImageField(blank=True, null=True, upload_to="banners/desktop/")),
                (
                    "device",
                    models.CharField(
                        choices=[
                            ("all", "Mobile and desktop"),
                            ("mobile", "Mobile only"),
                            ("desktop", "Desktop only"),
                        ],
                        default="all",
                        max_length=20,
                    ),
                ),
                ("link_url", models.URLField(blank=True)),
                ("is_published", models.BooleanField(default=True)),
                ("order", models.PositiveIntegerField(default=0)),
                ("starts_at", models.DateTimeField(blank=True, null=True)),
                ("ends_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "verbose_name": "Banner ad",
                "verbose_name_plural": "Banner ads",
                "ordering": ("order", "-id"),
            },
        ),
    ]
