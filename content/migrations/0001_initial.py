from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="AmritVachan",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("title", models.CharField(max_length=220)),
                ("slug", models.SlugField(blank=True, max_length=240, unique=True)),
                ("quote_number", models.PositiveIntegerField(default=0, help_text="Example: 2151")),
                ("quote_date", models.DateField(blank=True, null=True)),
                ("image", models.ImageField(upload_to="amrit_vachan/")),
                ("hindi_text", models.TextField(blank=True)),
                ("english_text", models.TextField(blank=True)),
                ("is_published", models.BooleanField(default=True)),
                ("order", models.PositiveIntegerField(default=0)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "verbose_name": "Amrit vachan",
                "verbose_name_plural": "Amrit vachan",
                "ordering": ("order", "-quote_date", "-quote_number", "-id"),
            },
        ),
    ]
