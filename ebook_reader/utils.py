import logging
import re
import statistics
import unicodedata
from dataclasses import dataclass
from html import escape
from io import BytesIO

from django.conf import settings
from django.db import transaction
from django.utils.module_loading import import_string
from django.utils import timezone
from pypdf import PdfReader

from .models import Book, BookPage

logger = logging.getLogger(__name__)

# Common signatures produced when KrutiDev/DevLys glyph codes are interpreted as
# Latin text. This is deliberately conservative so ordinary English is not OCRed.
LEGACY_FONT_MARKERS = frozenset("¼½¾¿ÀÁÂÃÄÆÇÈÉÊËÌÍÎÏÐÑÒÓÔÕÖ×ØÙÚÛÜÝÞß")
LEGACY_HINDI_TOKEN_RE = re.compile(
    r"\b(?:dq|dks|dj|ds|fd|fn|ft|gS|jh|iz|izk|vk|vks|vkSj|dks|dks|esa|"
    r"Hkk|Hkh|jkt|lkFk|lq|ugha|eq)[A-Za-z]*\b",
    re.IGNORECASE,
)


class PdfOcrError(RuntimeError):
    """Raised internally when a PDF page cannot be rendered or OCRed."""


@dataclass
class PageLayoutResult:
    """Safe rich text plus its reading-order plain-text representation."""

    plain_text: str
    html: str
    line_count: int


@dataclass
class _LayoutFragment:
    text: str
    left: float
    top: float
    right: float
    bottom: float
    confidence: float = 100.0
    font_size: float | None = None
    bold: bool = False
    italic: bool = False
    ink_density: float = 0.0

    @property
    def width(self):
        return max(1.0, self.right - self.left)

    @property
    def height(self):
        return max(1.0, self.bottom - self.top)

    @property
    def center_y(self):
        return (self.top + self.bottom) / 2


def normalize_extracted_text(value):
    """Return NFC Unicode text and apply an optional legacy-font converter."""
    text = _normalize_unicode(value)
    converter_path = getattr(settings, "EBOOK_READER_LEGACY_TEXT_CONVERTER", "")
    if converter_path:
        text = import_string(converter_path)(text)
        if not isinstance(text, str):
            raise TypeError("The legacy text converter must return a string.")
        text = unicodedata.normalize("NFC", text)
    return text


def _normalize_unicode(value):
    return unicodedata.normalize("NFC", value or "").replace("\x00", "")


def is_garbled_text(value):
    """Detect empty, corrupt, private-use, or likely legacy Hindi font output."""
    text = unicodedata.normalize("NFC", value or "").strip()
    if not text:
        return True
    if "\ufffd" in text or any(character in LEGACY_FONT_MARKERS for character in text):
        return True

    meaningful = [character for character in text if not character.isspace()]
    if not meaningful:
        return True
    private_or_control = sum(
        unicodedata.category(character) == "Co"
        or (unicodedata.category(character).startswith("C") and character not in "\n\r\t")
        for character in meaningful
    )
    if private_or_control / len(meaningful) > 0.01:
        return True

    latin_words = re.findall(r"[A-Za-z]+", text)
    legacy_tokens = LEGACY_HINDI_TOKEN_RE.findall(text)
    # Two known glyph-code tokens are a strong signal. One is sufficient when
    # the line also contains dense punctuation/digits typical of mapped PDFs.
    if len(legacy_tokens) >= 2:
        return True
    punctuation = sum(not character.isalnum() and not character.isspace() for character in text)
    if legacy_tokens and latin_words and punctuation / len(meaningful) > 0.08:
        return True
    return False


def split_text_lines(text, *, apply_legacy_converter=True):
    """Return normalized non-empty lines without losing their reading order."""
    lines = []
    normalizer = normalize_extracted_text if apply_legacy_converter else _normalize_unicode
    normalized = normalizer(text).replace("\r\n", "\n").replace("\r", "\n")
    for raw_line in normalized.split("\n"):
        line = raw_line.strip().strip("\f")
        if line:
            lines.append(line)
    return lines


def lines_to_html(lines):
    return "\n".join(f'<p class="reader-line">{escape(line)}</p>' for line in lines)


def page_text_to_html(text, *, apply_legacy_converter=True):
    """Preserve OCR line boundaries as safe, editor-friendly paragraphs."""
    return lines_to_html(
        split_text_lines(text, apply_legacy_converter=apply_legacy_converter)
    )


def _plain_layout_result(text, *, apply_legacy_converter=False):
    lines = split_text_lines(text, apply_legacy_converter=apply_legacy_converter)
    return PageLayoutResult("\n".join(lines), lines_to_html(lines), len(lines))


def extract_book_pages(book, *, force_ocr=None):
    """Extract every PDF page, OCRing empty or font-mapped pages as needed.

    Page replacement remains atomic: an OCR/render failure cannot leave a partial
    set of BookPage rows. If OCR dependencies are unavailable, the best normalized
    pypdf text is retained and the failure is logged instead of breaking upload.
    """
    if not book.pdf_file:
        return 0

    if force_ocr is None:
        force_ocr = getattr(settings, "EBOOK_READER_FORCE_OCR", False)
    Book.objects.filter(pk=book.pk).update(
        processing_status=Book.ProcessingStatus.PROCESSING,
        processed_pages=0,
        processing_error="",
        processed_at=None,
    )
    try:
        pdf_bytes = _read_book_pdf(book)
        reader = PdfReader(BytesIO(pdf_bytes))
        total_pages = len(reader.pages)
        Book.objects.filter(pk=book.pk).update(total_pages=total_pages)
        pages = []
        page_lines = {}
        for number, pdf_page in enumerate(reader.pages, start=1):
            raw_text = ""
            try:
                raw_text = pdf_page.extract_text() or ""
                extracted_text = normalize_extracted_text(raw_text)
            except Exception as error:
                logger.warning(
                    "PDF text extraction failed for book=%s page=%s: %s",
                    book.pk,
                    number,
                    error,
                )
                extracted_text = ""

            raw_is_garbled = is_garbled_text(raw_text)
            converted_is_usable = raw_is_garbled and not is_garbled_text(extracted_text)
            use_ocr = force_ocr or (raw_is_garbled and not converted_is_usable)
            page_text = extracted_text
            page_layout = None
            method = (
                BookPage.ExtractionMethod.LEGACY_CONVERTER
                if converted_is_usable
                else BookPage.ExtractionMethod.EMBEDDED
            )
            if use_ocr:
                try:
                    ocr_languages = (
                        getattr(settings, "EBOOK_LEGACY_OCR_LANGUAGES", "hin")
                        if raw_is_garbled
                        else None
                    )
                    ocr_layout = ocr_pdf_page_layout(
                        pdf_bytes,
                        number,
                        languages=ocr_languages,
                    )
                    if ocr_layout.plain_text.strip():
                        page_layout = ocr_layout
                        page_text = ocr_layout.plain_text
                        method = BookPage.ExtractionMethod.OCR
                    else:
                        method = BookPage.ExtractionMethod.FALLBACK
                        logger.warning("OCR returned no text for book=%s page=%s", book.pk, number)
                except PdfOcrError as error:
                    method = BookPage.ExtractionMethod.FALLBACK
                    logger.warning(
                        "OCR unavailable for book=%s page=%s; retaining fallback text: %s",
                        book.pk,
                        number,
                        error,
                    )

            if page_layout is None and method == BookPage.ExtractionMethod.EMBEDDED:
                page_layout = embedded_pdf_page_layout(pdf_bytes, number)
            if page_layout is None:
                page_layout = _plain_layout_result(page_text)
            lines = split_text_lines(page_layout.plain_text, apply_legacy_converter=False)
            page_lines[number] = lines
            pages.append(
                BookPage(
                    book=book,
                    page_number=number,
                    content=page_layout.html,
                    plain_text=page_layout.plain_text,
                    line_count=page_layout.line_count,
                    extraction_method=method,
                )
            )
            if number % 10 == 0 or number == total_pages:
                Book.objects.filter(pk=book.pk).update(processed_pages=number)

        with transaction.atomic():
            existing_pages = {
                page.page_number: page
                for page in BookPage.objects.filter(book=book)
            }
            pages_to_create = []
            pages_to_update = []
            for extracted_page in pages:
                existing_page = existing_pages.get(extracted_page.page_number)
                if existing_page is None:
                    pages_to_create.append(extracted_page)
                    continue
                existing_page.content = extracted_page.content
                existing_page.plain_text = extracted_page.plain_text
                existing_page.line_count = extracted_page.line_count
                existing_page.extraction_method = extracted_page.extraction_method
                pages_to_update.append(existing_page)

            if pages_to_create:
                BookPage.objects.bulk_create(pages_to_create, batch_size=250)
            if pages_to_update:
                BookPage.objects.bulk_update(
                    pages_to_update,
                    fields=("content", "plain_text", "line_count", "extraction_method"),
                    batch_size=250,
                )
            stale_page_numbers = set(existing_pages) - set(page_lines)
            if stale_page_numbers:
                BookPage.objects.filter(
                    book=book,
                    page_number__in=stale_page_numbers,
                ).delete()
        Book.objects.filter(pk=book.pk).update(
            processing_status=Book.ProcessingStatus.READY,
            total_pages=total_pages,
            processed_pages=total_pages,
            processing_error="",
            processed_at=timezone.now(),
        )
        logger.info("Extracted %s page(s) for ebook_reader.Book pk=%s", len(pages), book.pk)
        return len(pages)
    except Exception as error:
        Book.objects.filter(pk=book.pk).update(
            processing_status=Book.ProcessingStatus.FAILED,
            processing_error=str(error)[:4000],
        )
        raise


def ocr_pdf_page(pdf_bytes, page_number, *, languages=None):
    """Render one PDF page and return Tesseract Hindi+English Unicode text."""
    image = _prepare_ocr_image(_render_pdf_page(pdf_bytes, page_number))
    try:
        import pytesseract
    except ImportError as error:
        raise PdfOcrError("pytesseract is not installed.") from error

    tesseract_cmd = getattr(settings, "EBOOK_TESSERACT_CMD", "")
    if tesseract_cmd:
        pytesseract.pytesseract.tesseract_cmd = tesseract_cmd
    languages = languages or getattr(settings, "EBOOK_OCR_LANGUAGES", "hin+eng") or "hin+eng"
    config = getattr(settings, "EBOOK_OCR_TESSERACT_CONFIG", "--psm 6")
    timeout = getattr(settings, "EBOOK_OCR_TIMEOUT_SECONDS", 60)
    try:
        text = pytesseract.image_to_string(
            image,
            lang=languages,
            config=config,
            timeout=timeout,
        )
    except Exception as error:
        # Covers TesseractNotFoundError, missing hin.traineddata, timeouts, and
        # subprocess failures without making the Book save fail.
        raise PdfOcrError(f"Tesseract OCR failed: {error}") from error
    return unicodedata.normalize("NFC", text or "")


def ocr_pdf_page_layout(pdf_bytes, page_number, *, languages=None):
    """OCR a full page and retain reading order, relative type size and alignment.

    Tesseract's plain-string API discards all layout information. The data API
    supplies word boxes; those boxes are combined with the PDF's font-span
    metadata (which remains useful even when its legacy glyph text is corrupt).
    """
    image = _prepare_ocr_image(
        _render_pdf_page(pdf_bytes, page_number),
        crop_margins=False,
    )
    try:
        import pytesseract
    except ImportError as error:
        raise PdfOcrError("pytesseract is not installed.") from error

    tesseract_cmd = getattr(settings, "EBOOK_TESSERACT_CMD", "")
    if tesseract_cmd:
        pytesseract.pytesseract.tesseract_cmd = tesseract_cmd
    languages = languages or getattr(settings, "EBOOK_OCR_LANGUAGES", "hin+eng") or "hin+eng"
    config = getattr(settings, "EBOOK_OCR_TESSERACT_CONFIG", "--psm 3")
    timeout = getattr(settings, "EBOOK_OCR_TIMEOUT_SECONDS", 60)
    try:
        data = pytesseract.image_to_data(
            image,
            lang=languages,
            config=config,
            output_type=pytesseract.Output.DICT,
            timeout=timeout,
        )
    except Exception as error:
        raise PdfOcrError(f"Tesseract layout OCR failed: {error}") from error

    fragments = _ocr_fragments_from_data(data, image)
    if not fragments:
        # Some Tesseract builds can return a useful string but no word records.
        try:
            text = pytesseract.image_to_string(
                image,
                lang=languages,
                config=config,
                timeout=timeout,
            )
        except Exception as error:
            raise PdfOcrError(f"Tesseract OCR failed: {error}") from error
        return _plain_layout_result(_normalize_unicode(text))

    _apply_pdf_style_hints(fragments, pdf_bytes, page_number, image.size)
    return _layout_result(fragments, image.size)


def embedded_pdf_page_layout(pdf_bytes, page_number):
    """Build rich HTML from Unicode PDF spans without flattening typography."""
    try:
        import fitz
    except ImportError:
        return None
    try:
        with fitz.open(stream=pdf_bytes, filetype="pdf") as document:
            page = document.load_page(page_number - 1)
            fragments = []
            for block in page.get_text("dict", sort=True).get("blocks", []):
                if block.get("type") != 0:
                    continue
                for line in block.get("lines", []):
                    spans = [span for span in line.get("spans", []) if span.get("text", "").strip()]
                    if not spans:
                        continue
                    text = "".join(span.get("text", "") for span in spans).strip()
                    if not text:
                        continue
                    x0, y0, x1, y1 = line.get("bbox")
                    font_size = max(float(span.get("size", 0)) for span in spans) or None
                    font_names = " ".join(str(span.get("font", "")) for span in spans).lower()
                    flags = 0
                    for span in spans:
                        flags |= int(span.get("flags", 0))
                    fragments.append(
                        _LayoutFragment(
                            text=_normalize_unicode(text),
                            left=x0,
                            top=y0,
                            right=x1,
                            bottom=y1,
                            font_size=font_size,
                            bold=bool(flags & 16) or "bold" in font_names,
                            italic=bool(flags & 2) or "italic" in font_names,
                        )
                    )
            if not fragments:
                return None
            return _layout_result(fragments, (page.rect.width, page.rect.height))
    except Exception as error:
        logger.warning("Embedded PDF layout extraction failed on page %s: %s", page_number, error)
        return None


def _ocr_fragments_from_data(data, image):
    required = ("text", "left", "top", "width", "height")
    if not data or any(key not in data for key in required):
        return []
    grouped = {}
    count = len(data.get("text", []))
    for index in range(count):
        text = _normalize_unicode(str(data["text"][index] or "")).strip()
        if not text:
            continue
        try:
            confidence = float(data.get("conf", [100] * count)[index])
            left = float(data["left"][index])
            top = float(data["top"][index])
            width = float(data["width"][index])
            height = float(data["height"][index])
        except (TypeError, ValueError, IndexError):
            continue
        # Keep low-confidence real script/numbers so running headers and printed
        # page numbers are not silently dropped. Reject only Tesseract sentinels.
        if (
            confidence < 0
            or width <= 0
            or height <= 0
            or height > image.height * 0.15
            or (width > image.width * 0.92 and len(text) <= 3)
        ):
            continue
        key = (
            data.get("block_num", [0] * count)[index],
            data.get("par_num", [0] * count)[index],
            data.get("line_num", list(range(count)))[index],
        )
        grouped.setdefault(key, []).append(
            (int(data.get("word_num", list(range(count)))[index]), text, left, top, width, height, confidence)
        )

    fragments = []
    grayscale = image.convert("L")
    for words in grouped.values():
        words.sort(key=lambda item: (item[0], item[2]))
        typical_height = statistics.median(item[5] for item in words)
        split_gap = max(image.width * 0.055, typical_height * 3.0)
        word_groups = [[]]
        previous_right = None
        for word in words:
            if previous_right is not None and word[2] - previous_right > split_gap:
                word_groups.append([])
            word_groups[-1].append(word)
            previous_right = word[2] + word[4]
        for word_group in word_groups:
            left = min(item[2] for item in word_group)
            top = min(item[3] for item in word_group)
            right = max(item[2] + item[4] for item in word_group)
            bottom = max(item[3] + item[5] for item in word_group)
            text = " ".join(item[1] for item in word_group)
            confidence = sum(item[6] for item in word_group) / len(word_group)
            # Remaining ornaments sometimes form one low-confidence pseudo-line
            # immediately below the last real row. Keep genuine page-edge text
            # when confidence is usable, but discard this border signature.
            if confidence < 45 and bottom >= image.height * 0.84:
                continue
            ink_density = _ink_density(grayscale, (left, top, right, bottom))
            fragments.append(
                _LayoutFragment(text, left, top, right, bottom, confidence, ink_density=ink_density)
            )
    return fragments


def _ink_density(grayscale, bbox):
    left, top, right, bottom = (int(round(value)) for value in bbox)
    left = max(0, min(grayscale.width, left))
    right = max(left + 1, min(grayscale.width, right))
    top = max(0, min(grayscale.height, top))
    bottom = max(top + 1, min(grayscale.height, bottom))
    histogram = grayscale.crop((left, top, right, bottom)).histogram()
    dark_pixels = sum(histogram[:180])
    return dark_pixels / max(1, (right - left) * (bottom - top))


def _apply_pdf_style_hints(fragments, pdf_bytes, page_number, image_size):
    """Match OCR lines to legacy PDF spans by geometry, never by corrupt text."""
    try:
        import fitz
        with fitz.open(stream=pdf_bytes, filetype="pdf") as document:
            page = document.load_page(page_number - 1)
            scale_x = image_size[0] / page.rect.width
            scale_y = image_size[1] / page.rect.height
            hints = []
            for block in page.get_text("dict", sort=True).get("blocks", []):
                if block.get("type") != 0:
                    continue
                for line in block.get("lines", []):
                    for span in line.get("spans", []):
                        if not span.get("text", "").strip():
                            continue
                        x0, y0, x1, y1 = span["bbox"]
                        name = str(span.get("font", "")).lower()
                        flags = int(span.get("flags", 0))
                        hints.append(
                            (
                                x0 * scale_x,
                                y0 * scale_y,
                                x1 * scale_x,
                                y1 * scale_y,
                                float(span.get("size", 0)),
                                bool(flags & 16) or "bold" in name,
                                bool(flags & 2) or "italic" in name,
                                str(span.get("text", "")).strip(),
                            )
                        )
            for fragment in fragments:
                # OCR boxes are measured in pixels while PDF spans use points.
                # Estimate point size for raster-only text before matching spans.
                fragment.font_size = fragment.height / max(scale_y, 0.01) * 0.82
                matches = []
                for hint in hints:
                    overlap_x = max(0.0, min(fragment.right, hint[2]) - max(fragment.left, hint[0]))
                    overlap_y = max(0.0, min(fragment.bottom, hint[3]) - max(fragment.top, hint[1]))
                    if overlap_x and overlap_y:
                        matches.append((overlap_x * overlap_y, hint))
                if matches:
                    _, best = max(matches, key=lambda item: item[0])
                    fragment.font_size = best[4] or None
                    fragment.bold = fragment.bold or best[5]
                    fragment.italic = fragment.italic or best[6]
                    if re.fullmatch(r"\d{1,4}", best[7]) and len(fragment.text) <= 4:
                        fragment.text = best[7].translate(
                            str.maketrans("0123456789", "०१२३४५६७८९")
                        )
    except Exception as error:
        logger.debug("PDF style hints unavailable for page %s: %s", page_number, error)


def _layout_result(fragments, page_size):
    fragments = [fragment for fragment in fragments if fragment.text.strip()]
    if not fragments:
        return PageLayoutResult("", "", 0)
    fragments.sort(key=lambda fragment: (fragment.top, fragment.left))
    rows = []
    for fragment in fragments:
        if rows:
            row_center = statistics.mean(item.center_y for item in rows[-1])
            tolerance = max(4.0, min(fragment.height, max(item.height for item in rows[-1])) * 0.55)
            previous_bottom = max(item.bottom for item in rows[-1])
            same_baseline = abs(fragment.bottom - previous_bottom) <= max(
                5.0,
                min(fragment.height, max(item.height for item in rows[-1])) * 0.55,
            )
            if abs(fragment.center_y - row_center) <= tolerance or same_baseline:
                rows[-1].append(fragment)
                rows[-1].sort(key=lambda item: item.left)
                continue
        rows.append([fragment])

    representative = [
        fragment
        for fragment in fragments
        if len(re.sub(r"\W", "", fragment.text, flags=re.UNICODE)) >= 3
    ] or fragments
    font_sizes = [fragment.font_size for fragment in representative if fragment.font_size]
    base_size = statistics.median(font_sizes) if font_sizes else statistics.median(
        fragment.height for fragment in representative
    )
    densities = [fragment.ink_density for fragment in representative if fragment.ink_density > 0]
    base_density = statistics.median(densities) if densities else 0
    page_width, _ = page_size
    html_rows = ['<div class="reader-layout" data-layout-version="2">']
    plain_rows = []
    previous_bottom = None
    for row in rows:
        row_top = min(fragment.top for fragment in row)
        row_bottom = max(fragment.bottom for fragment in row)
        gap_ratio = 0.0 if previous_bottom is None else max(0.0, row_top - previous_bottom) / max(1.0, base_size)
        gap_em = min(3.0, max(0.0, gap_ratio * 0.62))
        previous_bottom = max(previous_bottom or row_bottom, row_bottom)
        plain_rows.append("    ".join(fragment.text for fragment in row))
        if len(row) == 1:
            fragment = row[0]
            classes, scale = _fragment_classes(fragment, base_size, base_density)
            center = (fragment.left + fragment.right) / 2
            if abs(center - page_width / 2) <= page_width * 0.1 and fragment.width < page_width * 0.88:
                classes.append("reader-align-center")
            elif fragment.left >= page_width * 0.53:
                classes.append("reader-align-right")
            else:
                classes.append("reader-align-left")
            html_rows.append(
                f'<p class="reader-line {" ".join(classes)}" '
                f'style="--line-scale:{scale:.3f};--line-gap:{gap_em:.3f}em">'
                f'{escape(fragment.text)}</p>'
            )
            continue

        html_rows.append(
            f'<div class="reader-layout-row" style="--line-gap:{gap_em:.3f}em">'
        )
        previous_right = 0.0
        for fragment in row:
            classes, scale = _fragment_classes(fragment, base_size, base_density)
            margin = max(0.0, (fragment.left - previous_right) / page_width * 100)
            html_rows.append(
                f'<span class="reader-layout-fragment {" ".join(classes)}" '
                f'style="--line-scale:{scale:.3f};margin-left:{margin:.3f}%">'
                f'{escape(fragment.text)}</span>'
            )
            previous_right = fragment.right
        html_rows.append("</div>")
    html_rows.append("</div>")
    return PageLayoutResult("\n".join(plain_rows), "\n".join(html_rows), len(rows))


def _fragment_classes(fragment, base_size, base_density):
    measured_size = fragment.font_size or fragment.height
    scale = min(2.15, max(0.68, measured_size / max(1.0, base_size)))
    visually_bold = (
        scale >= 1.17
        or (base_density > 0 and fragment.ink_density >= base_density * 1.18 and scale >= 0.9)
    )
    classes = []
    if fragment.bold or visually_bold:
        classes.append("reader-bold")
    if fragment.italic:
        classes.append("reader-italic")
    return classes, scale


def _prepare_ocr_image(image, *, crop_margins=True):
    """Remove configured page furniture and improve text contrast for OCR."""
    try:
        from PIL import ImageOps
    except ImportError as error:
        raise PdfOcrError("Pillow is not installed.") from error

    raw_margins = (
        str(getattr(settings, "EBOOK_OCR_CROP_MARGINS", "0,0,0,0"))
        if crop_margins
        else "0,0,0,0"
    )
    try:
        left, top, right, bottom = [float(value.strip()) for value in raw_margins.split(",")]
    except (TypeError, ValueError):
        raise PdfOcrError(
            "EBOOK_OCR_CROP_MARGINS must contain left,top,right,bottom fractions."
        )
    if any(value < 0 or value >= 0.45 for value in (left, top, right, bottom)):
        raise PdfOcrError("OCR crop margins must be between 0 and 0.45.")
    width, height = image.size
    if any((left, top, right, bottom)):
        image = image.crop(
            (
                int(width * left),
                int(height * top),
                int(width * (1 - right)),
                int(height * (1 - bottom)),
            )
        )
    return ImageOps.autocontrast(ImageOps.grayscale(image))


def _render_pdf_page(pdf_bytes, page_number):
    """Prefer PyMuPDF image masking, falling back to pdf2image/Poppler."""
    try:
        return _render_with_pymupdf(pdf_bytes, page_number)
    except PdfOcrError as pymupdf_error:
        logger.info("PyMuPDF render unavailable; trying pdf2image: %s", pymupdf_error)
        try:
            return _render_with_pdf2image(pdf_bytes, page_number)
        except PdfOcrError as pdf2image_error:
            raise PdfOcrError(
                f"PDF page rendering failed (PyMuPDF: {pymupdf_error}; "
                f"pdf2image: {pdf2image_error})."
            ) from pdf2image_error


def _render_with_pdf2image(pdf_bytes, page_number):
    try:
        from pdf2image import convert_from_bytes
    except ImportError as error:
        raise PdfOcrError("pdf2image is not installed.") from error

    options = {
        "dpi": int(getattr(settings, "EBOOK_RENDER_DPI", 300)),
        "first_page": page_number,
        "last_page": page_number,
        "fmt": "png",
        "thread_count": 1,
    }
    poppler_path = getattr(settings, "EBOOK_PDF2IMAGE_POPPLER_PATH", "")
    if poppler_path:
        options["poppler_path"] = poppler_path
    try:
        images = convert_from_bytes(pdf_bytes, **options)
    except Exception as error:
        raise PdfOcrError(f"pdf2image/Poppler could not render the page: {error}") from error
    if not images:
        raise PdfOcrError("pdf2image returned no page image.")
    return images[0]


def _render_with_pymupdf(pdf_bytes, page_number):
    try:
        import fitz
        from PIL import Image, ImageDraw
    except ImportError as error:
        raise PdfOcrError("PyMuPDF or Pillow is not installed.") from error

    try:
        with fitz.open(stream=pdf_bytes, filetype="pdf") as document:
            if document.is_encrypted:
                raise PdfOcrError("The PDF is encrypted.")
            if not 1 <= page_number <= document.page_count:
                raise PdfOcrError("The requested page is outside the PDF page range.")
            page = document.load_page(page_number - 1)
            dpi = int(getattr(settings, "EBOOK_RENDER_DPI", 300))
            zoom = dpi / 72
            pixmap = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
            image = Image.open(BytesIO(pixmap.tobytes("png")))
            image.load()
            # Legacy Word/Print-to-PDF files retain usable text plus separate
            # decorative raster assets. Mask only small images; never mask a
            # full-page scan where the image itself contains the book text.
            if page.get_text("text").strip():
                draw = ImageDraw.Draw(image)
                page_area = max(1, page.rect.width * page.rect.height)
                for image_info in page.get_images(full=True):
                    xref = image_info[0]
                    for rect in page.get_image_rects(xref):
                        area_ratio = (rect.width * rect.height) / page_area
                        aspect_ratio = rect.width / max(rect.height, 0.01)
                        horizontal_border = (
                            aspect_ratio >= 8
                            and rect.height <= page.rect.height * 0.06
                            and (rect.y0 <= page.rect.height * 0.15 or rect.y1 >= page.rect.height * 0.85)
                        )
                        vertical_border = (
                            aspect_ratio <= 0.125
                            and rect.width <= page.rect.width * 0.06
                            and (rect.x0 <= page.rect.width * 0.15 or rect.x1 >= page.rect.width * 0.85)
                        )
                        # Preserve thin raster text strips and ornamental border
                        # text; remove edge border strips and picture/logo assets.
                        if (
                            not horizontal_border
                            and not vertical_border
                            and (
                                area_ratio >= 0.35
                                or min(rect.width, rect.height) < 36
                                or not 0.2 <= aspect_ratio <= 5
                            )
                        ):
                            continue
                        draw.rectangle(
                            (
                                int(rect.x0 * zoom),
                                int(rect.y0 * zoom),
                                int(rect.x1 * zoom),
                                int(rect.y1 * zoom),
                            ),
                            fill="white",
                        )
            return image
    except PdfOcrError:
        raise
    except Exception as error:
        raise PdfOcrError(f"PyMuPDF could not render the page: {error}") from error


def _read_book_pdf(book):
    try:
        book.pdf_file.open("rb")
        return b"".join(book.pdf_file.chunks())
    except (OSError, ValueError) as error:
        raise PdfOcrError(f"The uploaded PDF could not be read: {error}") from error
    finally:
        try:
            book.pdf_file.close()
        except Exception:
            pass
