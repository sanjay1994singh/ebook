import os
from pathlib import Path
from django.conf import settings
from django.core.files.storage import FileSystemStorage
from django.utils.deconstruct import deconstructible


@deconstructible
class ContentSourceStorage(FileSystemStorage):
    """Draft snapshots are never placed in the publicly served media directory."""
    @property
    def base_location(self):
        return str(getattr(settings, "CONTENT_SOURCE_ROOT", Path(settings.MEDIA_ROOT).parent / "private_content_sources"))

    @property
    def location(self):
        return os.path.abspath(self.base_location)

    def url(self, name):
        raise ValueError("Content source PDFs have no public URL.")
