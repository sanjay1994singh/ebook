from pathlib import Path

from django.core.files.base import ContentFile
from pypdf import PdfReader

from .models import BookPage, Chapter


def _clean_text(text):
    # PDF text often has extra blank lines. This keeps reader pages cleaner.
    lines = [line.strip() for line in (text or "").splitlines()]
    clean_lines = [line for line in lines if line]
    return "\n".join(clean_lines)


def _page_number_for_destination(reader, destination):
    try:
        return reader.get_destination_page_number(destination)
    except Exception:
        return None


def _read_pdf_outline(reader):
    # PDF bookmarks/outlines ko simple chapter list me convert karta hai.
    chapters = []

    def walk(items):
        for item in items:
            if isinstance(item, list):
                walk(item)
                continue

            page_index = _page_number_for_destination(reader, item)
            title = getattr(item, "title", "").strip()
            if title and page_index is not None:
                chapters.append({"title": title, "start_page": page_index + 1})

    try:
        walk(reader.outline)
    except Exception:
        return []

    unique_chapters = []
    seen_pages = set()
    for chapter in sorted(chapters, key=lambda value: value["start_page"]):
        if chapter["start_page"] in seen_pages:
            continue
        seen_pages.add(chapter["start_page"])
        unique_chapters.append(chapter)
    return unique_chapters


def _fallback_chapters(total_pages):
    if total_pages <= 0:
        return []
    return [{"title": "पूर्ण पुस्तक", "start_page": 1}]


def _render_pdf_page_to_png(pdf_document, page_number):
    # Legacy Hindi fonts text-extract me unreadable ho sakte hain.
    # Page image original PDF font, border aur layout ko same rakhti hai.
    pdf_page = pdf_document[page_number - 1]
    pil_image = pdf_page.render(scale=2).to_pil()
    image_path = Path(f"page-{page_number:04d}.png")

    from io import BytesIO

    image_buffer = BytesIO()
    pil_image.save(image_buffer, format="PNG", optimize=True)
    return image_path.name, ContentFile(image_buffer.getvalue())


def extract_pdf_to_book(book):
    # Admin PDF upload ke baad ye function chapters, text aur page images banata hai.
    if not book.pdf_file:
        return 0

    import pypdfium2 as pdfium

    reader = PdfReader(book.pdf_file.path)
    pdf_document = pdfium.PdfDocument(book.pdf_file.path)
    total_pages = len(reader.pages)
    chapters = _read_pdf_outline(reader) or _fallback_chapters(total_pages)

    Chapter.objects.filter(book=book).delete()

    imported_pages = 0
    for index, chapter_data in enumerate(chapters):
        next_chapter = chapters[index + 1] if index + 1 < len(chapters) else None
        start_page = chapter_data["start_page"]
        end_page = (next_chapter["start_page"] - 1) if next_chapter else total_pages

        chapter = Chapter.objects.create(
            book=book,
            title=chapter_data["title"],
            order=index + 1,
        )

        for page_number in range(start_page, end_page + 1):
            page = reader.pages[page_number - 1]
            content = _clean_text(page.extract_text())
            if not content:
                content = "[No readable text found on this PDF page]"

            book_page = BookPage.objects.create(
                chapter=chapter,
                title=f"Page {page_number}",
                page_number=page_number,
                content=content,
            )

            image_name, image_file = _render_pdf_page_to_png(pdf_document, page_number)
            book_page.page_image.save(
                f"{book.slug}/{image_name}",
                image_file,
                save=True,
            )
            imported_pages += 1

    book.pdf_import_status = "imported"
    book.pdf_page_count = imported_pages
    book.save(update_fields=["pdf_import_status", "pdf_page_count", "updated_at"])
    return imported_pages
