# PDF content reader: implementation and rollout

This implementation stores actual Unicode text and layout in `ContentPage` rows.
The public reader does not render PDF pages or whole-page screenshots. Its SVG
text nodes use extracted positions, sizes and style; a separate decoration layer
contains borders/drawings. The same HTML reader runs in Django web and React
Native WebView. A reflow mode keeps relative heading sizes while wrapping text.

## Pilot result and limits

- Source: `Charandas Ji Vani Pdf.pdf`, 99 pages, primarily Kruti Dev 021 with some
  Kruti Dev 010. This is legacy-encoded text, not clean Unicode.
- Direct legacy mapping resolves supported character codes on 98 of 99 pages.
  This is **mapping coverage, not 98/99 accuracy**. Page 94 falls back to OCR.
- Hindi OCR cross-checks mapped text and recovers text inside cover images.
  Raw source runs and OCR alternatives are retained for editorial comparison.
- Original font sizes and coordinates are retained. Kruti Dev glyphs are currently
  replaced by bundled Noto Serif Devanagari. Therefore this is **not an exact
  original-font reproduction**. Reflow necessarily changes line wrapping.
- No page has been claimed as fully proofread. All pilot editions remain drafts.
  Every page needs editorial approval before publication; a validation pass or
  high OCR confidence cannot certify spelling, matras, verse numbers or completeness.
- Scans, tables, rotated text and illustrations need layout review. OCR and image
  separation are heuristic; complex layouts may need manual coordinate editing.
- There is no automatic 100% text/layout guarantee. To meet that requirement,
  compare and correct every page and validate typography on target devices.

## Upload and review

1. In the existing Library Book admin, upload the PDF with automatic extraction
   enabled, or select books and run **Extract styled content**.
2. Celery creates a private immutable PDF snapshot and a new `ContentEdition`.
   Existing library chapters/pages are preserved. Identical source+engine uploads
   are deduplicated unless a new version is explicitly requested.
3. Open **Content editions → Compare and edit pages**. Compare the source on the
   left with extracted content on the right. Edit text, sizes and emphasis;
   advanced JSON supports run positions. Save drafts freely. The review bar shows
   approved counts, a page map and the next unreviewed page. Synchronized scrolling
   keeps source and extracted content at the same relative position in fixed mode.
   Editing and page navigation pause during a save to prevent cross-page races.
4. Approve each page only after checking the entire page. Subsequent edits reset
   approval unless explicitly reapproved. Concurrent stale saves return 409.
5. Publish after all pages are approved. Publication atomically archives the prior
   edition. The Library Book must also be published for public access.

The app discovers published content through the manifest endpoint. Until an
edition is published (or while the backend still lacks the new endpoint), it uses
the existing reader. Network errors offer retry. The new reader currently requires
connectivity; a packaged offline edition/download feature is not implemented.

## Production setup

Install the updated backend requirements and the system Tesseract executable with
Hindi language data. The legacy converter is a bundled optional GPL-3.0 standalone
command; its complete modified source, attribution and license are in
`tools/kru2uni/`. Review the licenses of distributed dependencies and fonts.

Example server settings (adjust paths to the deployment):

```python
CONTENT_SOURCE_ROOT = "/srv/nikunj-private/content-sources"  # writable, outside public media
EBOOK_TESSERACT_CMD = "/usr/bin/tesseract"
EBOOK_LEGACY_OCR_LANGUAGES = "hin"
EBOOK_OCR_LANGUAGES = "hin+eng"
EBOOK_OCR_TESSERACT_CONFIG = '--psm 3 --tessdata-dir "/srv/tessdata"'
EBOOK_OCR_TIMEOUT_SECONDS = 120
EBOOK_MAX_PDF_PAGES = 2500
EBOOK_MAX_PDF_SIZE_MB = 500
# EBOOK_KRUTIDEV_COMMAND = []  # explicitly disable optional converter and use OCR
# CONTENT_READER_FRAME_ORIGINS = ["https://your-web-app.example"]
```

Use the existing broker/Celery configuration. Do not enable eager Celery in
production: OCR must run in a worker, not the admin upload HTTP request.

```sh
python -m pip install -r requirements.txt
python manage.py migrate
python manage.py collectstatic --noinput
celery -A ebook_backend worker --loglevel=INFO
```

Restart the Django service after deployment. Serve collected static files and
allow only the required web origin in CORS/frame settings. Back up the database
and private source directory together. The new private storage does not change
the existing Library Book's original PDF storage or its existing access policy.

Batch existing books using the admin action or:

```sh
python manage.py extract_content --book-id 123 --queue
python manage.py extract_content --book-id 123 --new-version --queue
```

Omitting `--queue` runs extraction synchronously, useful for diagnostics. Failed
jobs can be retried in admin and retain completed/corrected pages. For a killed
worker stuck in `processing`, first ensure its job is stopped, then create a new
draft version; automatic stale-job reclamation is not implemented. Never reset
a live job while it is writing pages.

## API and permissions

- `GET /ebooks/content/books/<book_id>/`: availability + published reader URL.
- `GET /ebooks/content/books/<book_id>/read/`: public reader, `?page=N` supported.
- `GET /ebooks/content/editions/<edition_id>/pages/<page>/`: text + layout JSON.
- `GET /ebooks/content/editions/<edition_id>/search/?q=...`: page text search.
- Staff review/preview URLs are linked in admin; draft page data requires the
  content-page view permission. Editing needs change-contentpage, publishing needs
  change-contentedition. Mutation requests require session authentication and CSRF.
- The source comparison PNG is staff-only. Snapshot storage has no public URL.
- Unpublished books and archived/draft editions are not exposed by public APIs.

## Local pilot

`ebook_backend.content_pilot_settings` uses a separate SQLite database and media
under `../tmp/content-pilot`; it does not migrate the existing application DB.
It contains this workstation's Tesseract paths and is not a production settings file.

```powershell
.\.venv\Scripts\python.exe manage.py migrate --settings=ebook_backend.content_pilot_settings
.\.venv\Scripts\python.exe manage.py runserver 127.0.0.1:8773 --settings=ebook_backend.content_pilot_settings --noreload
```

The local sample is Book 1. Use the latest complete draft edition in admin.
The APK's API still points at the configured live server; local pilot content does
not become available there until backend deployment, review and publication.

## Verification

The earlier combined reader/API suite passed 57 tests. After the final conversion
and chapter fixes, all 18 structured-content tests passed, covering source
snapshots, publication gates, draft privacy, retry preservation, optimistic edits,
CSRF, invalid geometry, legacy conversion and chapter navigation.

Web export and Android release builds were exercised. Browser checks at 390 px
covered fixed layout, reflow, night mode and page navigation. This is not a
physical-device typography audit or full-book proofreading. The updated review UI
was also checked in-browser: all 99 page buttons, next-pending navigation, draft
save, and synchronized source/content scrolling worked. The book remains unapproved.
