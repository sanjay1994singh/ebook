"""Isolated local pilot: never changes the application's existing database/media."""
from .settings import *  # noqa: F403

PILOT_ROOT = BASE_DIR.parent / "tmp" / "content-pilot"  # noqa: F405
PILOT_ROOT.mkdir(parents=True, exist_ok=True)
DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": PILOT_ROOT / "pilot.sqlite3"}}
MEDIA_ROOT = PILOT_ROOT / "media"
MEDIA_URL = "/media/"
DEBUG = True
ALLOWED_HOSTS = ["127.0.0.1", "localhost", "testserver"]
CELERY_TASK_ALWAYS_EAGER = True
EBOOK_READER_ASYNC_PROCESSING = False
EBOOK_TESSERACT_CMD = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
EBOOK_TESSDATA_DIR = str(BASE_DIR.parent / "tmp" / "tessdata")  # noqa: F405
os.environ["TESSDATA_PREFIX"] = EBOOK_TESSDATA_DIR  # noqa: F405
EBOOK_LEGACY_OCR_LANGUAGES = "hin"
EBOOK_OCR_LANGUAGES = "hin"
EBOOK_OCR_TIMEOUT_SECONDS = 120
