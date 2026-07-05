from django.db import migrations, models
import django.db.models.deletion
from django.utils.text import slugify


def copy_text_speakers_to_model(apps, schema_editor):
    AudioSpeaker = apps.get_model("library", "AudioSpeaker")
    AudioTrack = apps.get_model("library", "AudioTrack")

    for speaker_name in AudioTrack.objects.exclude(speaker="").values_list("speaker", flat=True).distinct():
        slug = slugify(speaker_name, allow_unicode=True)[:200] or "speaker"
        base_slug = slug
        counter = 2
        while AudioSpeaker.objects.filter(slug=slug).exists():
            slug = f"{base_slug}-{counter}"[:200]
            counter += 1

        speaker, _created = AudioSpeaker.objects.get_or_create(
            name=speaker_name,
            defaults={"slug": slug},
        )
        AudioTrack.objects.filter(speaker=speaker_name, speaker_ref__isnull=True).update(speaker_ref=speaker)


class Migration(migrations.Migration):

    dependencies = [
        ("library", "0007_magazine_magazineissue"),
    ]

    operations = [
        migrations.CreateModel(
            name="AudioSpeaker",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=180)),
                ("slug", models.SlugField(blank=True, max_length=200, unique=True)),
                ("order", models.PositiveIntegerField(default=0)),
            ],
            options={
                "ordering": ("order", "name"),
                "verbose_name_plural": "Audio speakers",
            },
        ),
        migrations.AddField(
            model_name="audiotrack",
            name="speaker_ref",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="tracks",
                to="library.audiospeaker",
            ),
        ),
        migrations.RunPython(copy_text_speakers_to_model, migrations.RunPython.noop),
    ]
