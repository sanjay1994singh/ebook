from pathlib import Path

from django.core.files import File
from django.core.management.base import BaseCommand, CommandError
from django.utils.text import slugify

from library.models import AudioCategory, AudioSpeaker, AudioTrack


SUPPORTED_AUDIO_EXTENSIONS = {".mp3", ".m4a", ".aac", ".wav", ".ogg"}


class Command(BaseCommand):
    help = "Import audio files from a local folder using category id and speaker id."

    def add_arguments(self, parser):
        parser.add_argument("folder_path", help="Local folder path containing audio files.")
        parser.add_argument("--category-id", type=int, required=True, help="AudioCategory id.")
        parser.add_argument("--speaker-id", type=int, required=True, help="AudioSpeaker id.")
        parser.add_argument("--language", default="Hindi", help="Language text to save on audio tracks.")
        parser.add_argument("--recursive", action="store_true", help="Import audio files from subfolders also.")
        parser.add_argument("--dry-run", action="store_true", help="Show what will import without saving.")
        parser.add_argument("--unpublished", action="store_true", help="Save imported audio as unpublished.")
        parser.add_argument("--not-free", action="store_true", help="Save imported audio as paid/not free.")

    def handle(self, *args, **options):
        folder_path = Path(options["folder_path"])
        if not folder_path.exists() or not folder_path.is_dir():
            raise CommandError(f"Folder not found: {folder_path}")

        try:
            category = AudioCategory.objects.get(id=options["category_id"])
        except AudioCategory.DoesNotExist as error:
            raise CommandError(f"AudioCategory id not found: {options['category_id']}") from error

        try:
            speaker = AudioSpeaker.objects.get(id=options["speaker_id"])
        except AudioSpeaker.DoesNotExist as error:
            raise CommandError(f"AudioSpeaker id not found: {options['speaker_id']}") from error

        audio_files = self._get_audio_files(folder_path, options["recursive"])
        if not audio_files:
            self.stdout.write(self.style.WARNING("No audio files found."))
            return

        created_count = 0
        skipped_count = 0
        failed_count = 0

        self.stdout.write(f"Category: {category.id} - {category.name}")
        self.stdout.write(f"Speaker: {speaker.id} - {speaker.name}")
        self.stdout.write(f"Files found: {len(audio_files)}")

        for index, audio_path in enumerate(audio_files, start=1):
            title = self._title_from_filename(audio_path.name)
            if audio_path.stat().st_size == 0:
                skipped_count += 1
                self.stdout.write(self.style.WARNING(f"SKIP empty file: {audio_path.name}"))
                continue

            if self._audio_already_exists(title, audio_path.name, category.id, speaker.id):
                skipped_count += 1
                self.stdout.write(self.style.WARNING(f"SKIP duplicate: {title}"))
                continue

            if options["dry_run"]:
                created_count += 1
                self.stdout.write(self.style.SUCCESS(f"DRY RUN import: {title}"))
                continue

            try:
                audio_track = AudioTrack(
                    category=category,
                    speaker_ref=speaker,
                    speaker=speaker.name,
                    title=title,
                    slug=self._unique_slug(title),
                    language=options["language"],
                    is_free=not options["not_free"],
                    is_published=not options["unpublished"],
                    order=index,
                )

                with audio_path.open("rb") as audio_file:
                    audio_track.audio_file.save(audio_path.name, File(audio_file), save=True)

                created_count += 1
                self.stdout.write(self.style.SUCCESS(f"IMPORTED: {title}"))
            except Exception as error:
                failed_count += 1
                self.stdout.write(self.style.ERROR(f"FAILED: {audio_path.name} - {error}"))

        self.stdout.write(
            self.style.SUCCESS(
                f"Done. created={created_count}, skipped={skipped_count}, failed={failed_count}"
            )
        )

    def _get_audio_files(self, folder_path, recursive):
        pattern = "**/*" if recursive else "*"
        return sorted(
            [
                item
                for item in folder_path.glob(pattern)
                if item.is_file() and item.suffix.lower() in SUPPORTED_AUDIO_EXTENSIONS
            ],
            key=lambda item: str(item).lower(),
        )

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
