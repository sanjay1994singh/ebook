from pathlib import Path
import shutil
import subprocess
import tempfile

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
        parser.add_argument("--bitrate", default="128k", help="Compression bitrate. Default: 128k.")
        parser.add_argument("--no-compress", action="store_true", help="Import original files without ffmpeg compression.")

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

        should_compress = not options["no_compress"]
        if should_compress and not options["dry_run"] and not shutil.which("ffmpeg"):
            raise CommandError("ffmpeg not found. Install ffmpeg on VPS or use --no-compress.")

        created_count = 0
        skipped_count = 0
        failed_count = 0

        self._write_now(f"Category: {category.id} - {category.name}")
        self._write_now(f"Speaker: {speaker.id} - {speaker.name}")
        self._write_now(f"Files found: {len(audio_files)}")
        self._write_now(f"Compression: {'ON ' + options['bitrate'] if should_compress else 'OFF'}")

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_dir_path = Path(temp_dir)
            for index, audio_path in enumerate(audio_files, start=1):
                title = self._title_from_filename(audio_path.name)
                self._write_now(f"PROCESSING {index}/{len(audio_files)}: {audio_path.name}")
                if audio_path.stat().st_size == 0:
                    skipped_count += 1
                    self._write_now(self.style.WARNING(f"SKIP empty file: {audio_path.name}"))
                    continue

                if self._audio_already_exists(title, audio_path.name, category.id, speaker.id):
                    skipped_count += 1
                    self._write_now(self.style.WARNING(f"SKIP duplicate: {title}"))
                    continue

                if options["dry_run"]:
                    created_count += 1
                    self._write_now(self.style.SUCCESS(f"DRY RUN import: {title}"))
                    continue

                try:
                    import_path = audio_path
                    import_filename = audio_path.name
                    if should_compress:
                        self._write_now(f"COMPRESSING {index}/{len(audio_files)}: {audio_path.name}")
                        import_path = self._compress_audio(audio_path, temp_dir_path, options["bitrate"])
                        import_filename = f"{audio_path.stem}.mp3"

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

                    with import_path.open("rb") as audio_file:
                        audio_track.audio_file.save(import_filename, File(audio_file), save=True)

                    created_count += 1
                    original_size = self._format_size(audio_path.stat().st_size)
                    final_size = self._format_size(import_path.stat().st_size)
                    self._write_now(self.style.SUCCESS(f"IMPORTED: {title} ({original_size} -> {final_size})"))
                except Exception as error:
                    failed_count += 1
                    self._write_now(self.style.ERROR(f"FAILED: {audio_path.name} - {error}"))

        self._write_now(
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

    def _compress_audio(self, audio_path, temp_dir_path, bitrate):
        output_path = temp_dir_path / f"{audio_path.stem}.mp3"
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
            raise CommandError(result.stderr.strip() or f"ffmpeg failed for {audio_path.name}")
        return output_path

    def _format_size(self, size_bytes):
        size_mb = size_bytes / (1024 * 1024)
        return f"{size_mb:.2f} MB"

    def _write_now(self, message):
        self.stdout.write(message)
        self.stdout.flush()
