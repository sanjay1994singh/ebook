from django import forms

from .models import AudioCategory, AudioSpeaker


class MultipleFileInput(forms.ClearableFileInput):
    allow_multiple_selected = True


class MultipleFileField(forms.FileField):
    def clean(self, data, initial=None):
        single_file_clean = super().clean
        if isinstance(data, (list, tuple)):
            return [single_file_clean(file_item, initial) for file_item in data]
        return [single_file_clean(data, initial)]


class AudioTrackBulkUploadForm(forms.Form):
    category = forms.ModelChoiceField(queryset=AudioCategory.objects.all())
    speaker = forms.ModelChoiceField(queryset=AudioSpeaker.objects.all())
    language = forms.CharField(initial="Hindi", max_length=80)
    audio_files = MultipleFileField(
        widget=MultipleFileInput(attrs={"multiple": True}),
        help_text="Admin upload is for small batches. Use VPS import_audio_folder command for 100+ files.",
    )
    is_free = forms.BooleanField(initial=True, required=False)
    is_published = forms.BooleanField(initial=True, required=False)
    compress = forms.BooleanField(initial=True, required=False, help_text="Compress to MP3 before saving.")
    bitrate = forms.CharField(initial="128k", max_length=20, help_text="Example: 64k, 96k, 128k")

    def clean(self):
        cleaned_data = super().clean()
        audio_files = cleaned_data.get("audio_files") or []
        compress = cleaned_data.get("compress")
        max_files = 3 if compress else 10

        if len(audio_files) > max_files:
            raise forms.ValidationError(
                f"Please upload maximum {max_files} files at once from admin. "
                "For large folders use: python manage.py import_audio_folder."
            )

        allowed_extensions = {".mp3", ".m4a", ".aac", ".wav", ".ogg"}
        for audio_file in audio_files:
            filename = audio_file.name.lower()
            if not any(filename.endswith(extension) for extension in allowed_extensions):
                raise forms.ValidationError("Only mp3, m4a, aac, wav, and ogg files are allowed.")

        return cleaned_data
