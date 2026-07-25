# Ebook Django Backend

This backend handles:

- user register and login
- users/profile
- books/categories/chapters/pages
- favorite books
- reading progress
- Django admin panel for managing book data

## Setup

Use the bundled Python path if normal `python` is not available on this Windows machine.

```powershell
cd C:\Users\sanja\OneDrive\Documents\ebook\backend
& "C:\Users\sanja\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe manage.py migrate
.\.venv\Scripts\python.exe manage.py createsuperuser
.\.venv\Scripts\python.exe manage.py runserver 0.0.0.0:8000
```

Your database is controlled from `backend/.env`.

For MySQL use:

```text
DB_ENGINE=mysql
DB_NAME=ebook
DB_USER=your_mysql_user
DB_PASSWORD=your_mysql_password
DB_HOST=127.0.0.1
DB_PORT=3306
```

For easy local testing without MySQL, use:

```text
DB_ENGINE=sqlite
```

This backend saves users, uploaded books, PDF files, chapters, pages, favorites, and reading progress in the selected database.

Local API:

```text
http://localhost:8000/api/books/
```

Android phone API on the same Wi-Fi:

```text
http://10.132.240.73:8000/api/books/
```

## Web App URLs

Laptop:

```text
http://localhost:8000/
http://localhost:8000/web/books/
```

Mobile browser on same Wi-Fi:

```text
http://10.132.240.73:8000/
http://10.132.240.73:8000/web/books/
```

## API URLs

- `POST /api/auth/register/`
- `POST /api/auth/login/`
- `POST /api/auth/token/refresh/`
- `GET /api/auth/me/`
- `GET /api/books/categories/`
- `GET /api/books/`
- `GET /api/books/<slug>/`
- `GET /api/books/<slug>/chapters/`
- `GET /api/books/pages/<id>/`
- `GET /api/books/favorites/`
- `POST /api/books/favorites/`
- `DELETE /api/books/favorites/<book_id>/`
- `GET /api/books/progress/`
- `POST /api/books/progress/`

## Upload PDF And Show In App

1. Start backend:

```powershell
.\.venv\Scripts\python.exe manage.py runserver 0.0.0.0:8000
```

2. Open admin:

```text
http://localhost:8000/admin/
```

3. Login with local test admin:

```text
username: admin
password: admin12345
```

4. Add or edit a book in `Library > Books`.
5. Fill title/category/language.
6. Upload PDF in `Pdf file`.
7. Keep `Auto extract pdf` checked.
8. Click Save.

The backend will extract readable PDF text and create:

- chapters from PDF bookmarks if available
- one fallback chapter named `पूर्ण पुस्तक` if PDF has no bookmarks
- book pages from the PDF text

Then both the React Native app and Django web app can load books, chapters, and page text from the same backend.

Note: scanned image PDFs may not have readable text. Those need OCR before text can appear in the reader.

## Web App

The web app uses the same backend uploaded content. No sample books are shown.

- Home page: `http://localhost:8000/`
- Book list: `http://localhost:8000/web/books/`
- Book detail: click any book
- Reader: click `प्रारंभ से पढ़ें` or any chapter in `विषय सूची`

## MySQL

After changing `.env`, run migrations again:

```powershell
.\.venv\Scripts\python.exe manage.py migrate
```

React Native should call this backend API. The app should never connect directly to MySQL.

## Ebook Reader Background Worker

The new `ebook_reader` app uses Celery with Redis for explicit background PDF inspection.
This does not run automatically when a book is saved.

Start Redis first:

```powershell
redis-server
```

Start the Django server:

```powershell
.\.venv\Scripts\python.exe manage.py runserver 0.0.0.0:8000
```

Start the Celery worker in a second terminal:

```powershell
.\.venv\Scripts\celery.exe -A ebook_backend worker -l info
```

Queue inspection from Django admin:

```text
Admin > Ebook reader > Ebook documents > select rows > Inspect selected ebook PDFs
```

Inspection status rule:

- `review_required`: PDF has embedded text or bookmarks, so it is ready for admin review in the new ebook workflow.
- `pending`: PDF is readable but has no embedded text/bookmarks, so it waits for a later OCR phase.
- `failed`: PDF is missing, corrupt, encrypted, empty, or could not be inspected.

Inspect one ebook PDF synchronously from terminal:

```powershell
.\.venv\Scripts\python.exe manage.py inspect_ebook_pdf <ebook_id>
```

Useful `.env` values:

```text
CELERY_BROKER_URL=redis://127.0.0.1:6379/0
CELERY_RESULT_BACKEND=redis://127.0.0.1:6379/0
CELERY_TASK_ALWAYS_EAGER=False
```

## New Ebook System Production Readiness

The new ebook system is a beta layer beside the old reader. Disabling it does not delete books, PDFs, lessons, progress, OCR data, or review data. The old reader remains the fallback.

### Required packages

Python packages are listed in `requirements.txt`:

- Django / Django REST Framework
- Celery
- redis
- PyMuPDF
- pypdf / pypdfium2
- Pillow
- pytesseract

System packages needed on the server:

- Redis server for Celery
- Tesseract OCR
- Hindi language data for Tesseract, usually `hin`

### Feature flags

Use these `.env` values for gradual rollout:

```text
EBOOK_SYSTEM_ENABLED=True
EBOOK_WEB_READER_ENABLED=True
EBOOK_MOBILE_READER_ENABLED=True
EBOOK_READER_STAFF_ONLY=True
EBOOK_PROCESSING_ENABLED=True
EBOOK_READER_TOC_SCAN_PAGE_LIMIT=40
EBOOK_MAX_PDF_PAGES=2500
EBOOK_MAX_PDF_SIZE_MB=500
EBOOK_SIGNED_URL_EXPIRES_SECONDS=900
```

Rules:

- `EBOOK_SYSTEM_ENABLED=False` disables web/mobile/processing access.
- `EBOOK_READER_STAFF_ONLY=True` keeps the beta reader staff-only.
- Each `EbookDocument` must also be enabled in admin using:
  - `new_ebook_reader_enabled`
  - `new_ebook_reader_web_enabled`
  - `new_ebook_reader_mobile_enabled`
- Non-ready ebooks never open in the new reader.
- Old reader links are not redirected.

### Local setup

```powershell
.\.venv\Scripts\python.exe manage.py migrate
.\.venv\Scripts\python.exe manage.py check
.\.venv\Scripts\python.exe manage.py runserver 0.0.0.0:8000
```

Worker:

```powershell
redis-server
.\.venv\Scripts\celery.exe -A ebook_backend worker -l info
```

### Processing one ebook

```powershell
.\.venv\Scripts\python.exe manage.py onboard_ebooks --book-id 12 --dry-run
.\.venv\Scripts\python.exe manage.py onboard_ebooks --book-id 12
.\.venv\Scripts\python.exe manage.py inspect_ebook_pdf <ebook_id>
.\.venv\Scripts\python.exe manage.py detect_ebook_toc <ebook_id>
.\.venv\Scripts\python.exe manage.py process_ebook_toc <ebook_id> --dry-run
```

### Batch onboarding

Start small:

```powershell
.\.venv\Scripts\python.exe manage.py onboard_ebooks --all-with-pdf --missing-only --batch-size 10 --dry-run
.\.venv\Scripts\python.exe manage.py onboard_ebooks --all-with-pdf --missing-only --batch-size 10
```

Queue inspection only when the worker is running:

```powershell
.\.venv\Scripts\python.exe manage.py onboard_ebooks --all-with-pdf --missing-only --batch-size 25 --queue-inspection
```

### Reviewing TOCs

Admin path:

```text
Admin > Ebook reader > Ebook documents > Review TOC
```

Review steps:

1. Confirm PDF inspection succeeded.
2. Confirm TOC mode: auto, manual, or none.
3. Accept detected range or enter manual range.
4. Confirm page mapping.
5. Process TOC.
6. Fix invalid or low-confidence rows.
7. Verify lessons.
8. Mark document ready only after review.
9. Enable web/mobile per-book beta flags only when ready for testing.

### React Native requirements

The current mobile beta integration can call the API and open the secure web reader. A fully embedded native PDF reader will need native package installation and a new app build, for example a maintained PDF component compatible with the installed React Native/Expo version.

### Manual QA checklist

Web:

- Auto TOC range
- Manual TOC range
- No TOC
- One-page TOC
- Multi-page TOC
- Lesson navigation
- Secure PDF loading
- Progress restore
- Access denied
- Feature disabled

Android:

- Open ebook
- Lesson navigation
- Progress update
- Expired PDF URL or retry flow
- Background/foreground
- Large lesson list

iOS:

- Same scenarios as Android
- Native PDF compatibility after native library adoption
- Back navigation and return state

PDF types:

- Unicode text PDF
- Legacy Hindi text PDF
- Fully scanned PDF
- PDF bookmarks
- No TOC
- Unusual TOC page range
- Large PDF
- Corrupt/encrypted PDF

### Rollback

Fast rollback:

```text
EBOOK_SYSTEM_ENABLED=False
```

Partial rollback:

```text
EBOOK_WEB_READER_ENABLED=False
EBOOK_MOBILE_READER_ENABLED=False
EBOOK_PROCESSING_ENABLED=False
```

Expected rollback behavior:

- Users continue using the old reader.
- No migration rollback is required.
- Ebook data remains in the database.
- Celery workers can be paused.
- New APIs become inaccessible or hidden.
- Old `/web/reader/<page_id>/` URLs remain unchanged.

### Troubleshooting

- Run `manage.py check` after deployment.
- If scanned TOC detection fails, verify Tesseract and Hindi language data.
- If PDF access fails, verify `MEDIA_ROOT` and file storage permissions.
- If queued jobs do not run, check Redis and Celery worker logs.
- Keep `EBOOK_READER_TOC_SCAN_PAGE_LIMIT` modest for large scanned PDFs.
