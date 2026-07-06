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
        help_text="Select multiple audio files: mp3, m4a, aac, wav, ogg.",
    )
    is_free = forms.BooleanField(initial=True, required=False)
    is_published = forms.BooleanField(initial=True, required=False)
    compress = forms.BooleanField(initial=True, required=False, help_text="Compress to MP3 before saving.")
    bitrate = forms.CharField(initial="128k", max_length=20, help_text="Example: 64k, 96k, 128k")
