"""Extract actual Unicode runs and source geometry, never a whole-page text image.

OCR and typography confidence are deliberately separate. Every result is a draft.
"""
import base64
import io
import math
import copy
import re
import subprocess
import sys
from pathlib import Path
import statistics
import unicodedata
import xml.etree.ElementTree as ET

import fitz
from django.conf import settings

from ebook_reader.utils import is_garbled_text


def rounded(values):
    return [round(float(v), 3) for v in values]


def run_emphasis(span, fonts):
    # Legacy PDFs often omit bold/italic in the span flags while the embedded
    # font's own name table correctly identifies its face.
    font = fonts.get(span.get("font"), {})
    style = font.get("style", "").lower()
    return {
        "bold": bool(span.get("flags", 0) & 16) or bool(font.get("bold")) or any(word in style for word in ("bold", "black", "heavy")),
        "italic": bool(span.get("flags", 0) & 2) or bool(font.get("italic")) or any(word in style for word in ("italic", "oblique")),
    }


def font_catalog(document, page):
    fonts = {}
    for xref, ext, kind, base_name, *_ in page.get_fonts(full=True):
        info = {"source_name": base_name, "family": base_name, "legacy": False}
        try:
            from fontTools.ttLib import TTFont
            data = document.extract_font(xref)[3]
            font = TTFont(io.BytesIO(data))
            name = font["name"].getDebugName(1) or base_name
            info["family"] = name
            info["style"] = font["name"].getDebugName(2) or ""
            info["legacy"] = any(s in name.lower().replace(" ", "") for s in ("kruti", "devlys", "chanakya"))
            # Only explicitly permitted embedding; otherwise keep provenance and use reader font.
            fs_type = font["OS/2"].fsType if "OS/2" in font else 2
            if not info["legacy"] and fs_type == 0 and ext in ("ttf", "otf"):
                info["data"] = f"data:font/{ext};base64," + base64.b64encode(data).decode()
        except Exception:
            pass
        fonts[base_name] = info
    return fonts


def extract_pages(data, *, skip=()):
    with fitz.open(stream=data, filetype="pdf") as document:
        if document.needs_pass:
            raise ValueError("Password protected PDFs must be unlocked before upload.")
        total = len(document)
        if not total or total > getattr(settings, "EBOOK_MAX_PDF_PAGES", 2500):
            raise ValueError("Invalid or excessive page count.")
        yield total, None, None, None, None
        for number, page in enumerate(document, start=1):
            if number in skip:
                continue
            layout, method, issues = extract_page(document, page)
            yield total, number, layout, method, issues


def extract_page(document, page):
    # Normalize rotation consistently for text, OCR and decoration coordinates.
    original_rotation = page.rotation
    page.set_rotation(0)
    try:
        fonts = font_catalog(document, page)
        raw = page.get_text("dict", sort=True)
        source_lines = []
        for block in raw["blocks"]:
            for line in block.get("lines", []):
                runs = []
                for span in line["spans"]:
                    if not span["text"]:
                        continue
                    runs.append({
                        "text": unicodedata.normalize("NFC", span["text"]),
                        "bbox": rounded(span["bbox"]), "origin": rounded(span["origin"]),
                        "font": span["font"], "size": round(span["size"], 3),
                        **run_emphasis(span, fonts),
                        "color": f'#{span["color"]:06x}',
                    })
                if runs:
                    source_lines.append({"bbox": rounded(line["bbox"]), "dir": rounded(line["dir"]), "runs": runs})
        text = "\n".join("".join(r["text"] for r in line["runs"]) for line in source_lines)
        converted_lines, conversion_issues = convert_legacy_lines(source_lines, fonts)
        legacy = any(f["legacy"] for f in fonts.values())
        needs_ocr = legacy or is_garbled_text(text)
        issues = list(conversion_issues)
        if needs_ocr:
            lines, ocr_issues = ocr_lines(page, source_lines, raw)
            issues.extend(ocr_issues)
            method = "ocr_legacy" if source_lines else "ocr_scan"
            issues.append("OCR text must be proofread against the source, including matras and verse numbers.")
            if legacy:
                issues.append("Legacy font: Unicode reader font is substituted; exact glyph shapes are not guaranteed.")
        else:
            lines, method = source_lines, "embedded"
            # Unicode pages can still contain image-only text. OCR just those regions
            # when images exist; embedded Unicode runs remain the primary source.
            if any(b.get("type") == 1 and not border_image(b, page.rect) for b in raw["blocks"]):
                image_ocr, image_issues = ocr_lines(page, source_lines, raw)
                extra = [line for line in image_ocr if not any(overlap(line["bbox"], src["bbox"]) > .3 for src in source_lines)]
                if extra:
                    lines = source_lines + extra
                    method = "embedded+ocr"
                    issues.extend(image_issues)
                    issues.append("Image-only text was OCRed; review those regions for missing illustrations or false detections.")
        if converted_lines is not None:
            ocr_result = lines
            lines = converted_lines
            for line in lines:
                match = max(ocr_result, key=lambda other: overlap(line["bbox"], other["bbox"]), default=None)
                if match and overlap(line["bbox"], match["bbox"]) > .45:
                    line["ocr_alternative"] = "".join(r["text"] for r in match["runs"])
            # Retain OCR from small image-only text regions (e.g. four cover lines).
            for line in ocr_result:
                if not any(overlap(line["bbox"], source["bbox"]) > .3 for source in source_lines):
                    lines.append(line)
            lines.sort(key=lambda line: (round(line["bbox"][1] / 5), line["bbox"][0]))
            method = "legacy_unicode+ocr"
            issues.append("Kruti Dev mapping used for embedded text; compare with source and OCR alternative before approval.")
        if not lines and (source_lines or raw.get("blocks")):
            raise ValueError(f"No usable text recovered on source page {page.number + 1}.")
        # Whole-page raster text is intentionally excluded from the content renderer.
        large_images = [b for b in raw["blocks"] if b.get("type") == 1 and fitz.Rect(b["bbox"]).get_area() > page.rect.get_area() * .45]
        if large_images:
            issues.append("Large image regions require illustration/layout review; full-page scan is not used as content.")
        if original_rotation:
            issues.append(f"Source rotation {original_rotation} degrees normalized; verify reading orientation.")
        if any(abs(line.get("dir", [1, 0])[1]) > .01 for line in lines):
            issues.append("Rotated text requires layout review.")
        if not needs_ocr and any("data" not in fonts.get(r["font"], {}) for l in lines for r in l["runs"]):
            issues.append("One or more source fonts cannot be embedded; check substituted typography.")
        return {
            "schema_version": 1, "width": round(page.rect.width, 3), "height": round(page.rect.height, 3),
            "fonts": fonts, "lines": lines,
            "decoration": "",
        }, method, issues
    finally:
        page.set_rotation(original_rotation)


def convert_legacy_lines(source_lines, fonts):
    known = {key for key, font in fonts.items() if "kruti" in font["family"].lower().replace(" ", "")}
    if not known:
        return None, []
    command = getattr(settings, "EBOOK_KRUTIDEV_COMMAND", None)
    if command is None:
        command = [sys.executable, str(Path(__file__).resolve().parents[2] / "tools" / "kru2uni" / "krutidev2unicode.py")]
    if not command:
        return None, ["Kruti Dev converter disabled; OCR used."]
    lines = copy.deepcopy(source_lines)
    targets = [run for line in lines for run in line["runs"] if run["font"] in known]
    if not targets:
        return None, []
    try:
        result = subprocess.run(command, input="\n".join(run["text"] for run in targets) + "\n",
            encoding="utf-8", text=True, capture_output=True, timeout=30, check=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        converted = result.stdout.splitlines()
        if len(converted) != len(targets):
            return None, ["Legacy converter changed run boundaries; OCR fallback used."]
        for run, value in zip(targets, converted):
            if any("LATIN" in unicodedata.name(c, "") or c == "\ufffd" or unicodedata.category(c) == "Co" for c in value):
                return None, ["Unresolved legacy code in conversion; OCR fallback used."]
            run["source_text"] = run["text"]
            run["text"] = unicodedata.normalize("NFC", value)
            run["fit_source_width"] = True
        return lines, []
    except (OSError, subprocess.SubprocessError) as error:
        return None, [f"Legacy converter unavailable ({type(error).__name__}); OCR fallback used."]


def border_image(block, rect):
    box = fitz.Rect(block["bbox"])
    # Narrow decoration bands outside the central reading column are not text.
    return (box.width > rect.width * .65 and box.height < rect.height * .05) or (box.height > rect.height * .5 and box.width < rect.width * .08)


def ocr_lines(page, source_lines, raw):
    import pytesseract
    from PIL import Image
    command = getattr(settings, "EBOOK_TESSERACT_CMD", "")
    if command:
        pytesseract.pytesseract.tesseract_cmd = command
    dpi = 300
    pix = page.get_pixmap(dpi=dpi, alpha=False)
    image = Image.open(io.BytesIO(pix.tobytes("png")))
    if source_lines:
        # Keep source text and interior images, mask edge ornaments before OCR.
        # Some PDFs (including the pilot cover) contain text baked into small images.
        clean = Image.new("RGB", image.size, "white")
        boxes = [line["bbox"] for line in source_lines] + [b["bbox"] for b in raw["blocks"] if b.get("type") == 1 and not border_image(b, page.rect)]
        for box in boxes:
            crop = (max(0, int((box[0] - 1) * pix.width / page.rect.width)), max(0, int((box[1] - 1) * pix.height / page.rect.height)), min(pix.width, math.ceil((box[2] + 1) * pix.width / page.rect.width)), min(pix.height, math.ceil((box[3] + 1) * pix.height / page.rect.height)))
            clean.paste(image.crop(crop), crop[:2])
        image = clean
    config = getattr(settings, "EBOOK_OCR_TESSERACT_CONFIG", "--psm 3")
    languages = getattr(settings, "EBOOK_LEGACY_OCR_LANGUAGES", "hin") if source_lines else getattr(settings, "EBOOK_OCR_LANGUAGES", "hin+eng")
    data = pytesseract.image_to_data(image, lang=languages, config=config,
        output_type=pytesseract.Output.DICT, timeout=getattr(settings, "EBOOK_OCR_TIMEOUT_SECONDS", 120))
    sx, sy = page.rect.width / pix.width, page.rect.height / pix.height
    groups = {}
    for i, word in enumerate(data["text"]):
        word = unicodedata.normalize("NFC", str(word)).strip()
        if not word or float(data["conf"][i]) < 0:
            continue
        x, y = data["left"][i] * sx, data["top"][i] * sy
        w, h = data["width"][i] * sx, data["height"][i] * sy
        box = (x, y, x + w, y + h)
        candidates = [(index, source, overlap(box, source["bbox"])) for index, source in enumerate(source_lines)]
        best = max(candidates, key=lambda value: value[2], default=None)
        source_index = best[0] if best and best[2] > .3 else None
        key = ("source", source_index) if source_index is not None else ("ocr", data["block_num"][i], data["par_num"][i], data["line_num"][i])
        groups.setdefault(key, []).append((word, box, float(data["conf"][i])))
    lines, issues, matched = [], [], set()
    for key, words in groups.items():
        words.sort(key=lambda v: v[1][0])
        box = (min(w[1][0] for w in words), min(w[1][1] for w in words), max(w[1][2] for w in words), max(w[1][3] for w in words))
        source = source_lines[key[1]] if key[0] == "source" else None
        confidence = round(statistics.mean(w[2] for w in words), 1)
        if source:
            matched.add(key[1])
            style = max(source["runs"], key=lambda r: r["bbox"][2] - r["bbox"][0])
            origin, bbox, size = style["origin"], source["bbox"], style["size"]
            # Start at the complete line's left edge, not its largest interior span.
            origin = [bbox[0], origin[1]]
        else:
            size = max(6, (box[3] - box[1]) * 1.1)
            origin, bbox = [box[0], box[3] - size * .12], box
            style = {"font": "reader", "bold": False, "italic": False, "color": "#000000"}
        run = {k: style[k] for k in ("font", "bold", "italic", "color")}
        run.update(text=" ".join(w[0] for w in words), bbox=rounded(bbox), origin=rounded(origin), size=round(size, 3), confidence=confidence)
        lines.append({"bbox": rounded(bbox), "dir": [1, 0], "runs": [run]})
        if confidence < 85:
            issues.append(f"Low OCR confidence ({confidence}): {run['text'][:70]}")
    if source_lines and len(matched) < len(source_lines):
        issues.append(f"OCR/source line coverage {len(matched)}/{len(source_lines)}. Check missing/merged lines.")
    # Source line geometry separates neighboring columns and mixed cover headings.
    lines.sort(key=lambda line: (round(line["bbox"][1] / 5), line["bbox"][0]))
    return lines, issues


def overlap(a, b):
    intersection = max(0, min(a[2], b[2]) - max(a[0], b[0])) * max(0, min(a[3], b[3]) - max(a[1], b[1]))
    return intersection / max(1, min((a[2] - a[0]) * (a[3] - a[1]), (b[2] - b[0]) * (b[3] - b[1])))


def decoration_svg(page, *, omit_images=False, text_images=()):
    root = ET.fromstring(page.get_svg_image(text_as_path=False))
    # SVG is generated locally by MuPDF. Keep drawings, masks and small illustrations,
    # but remove *all* text so no hidden PDF text is used to fake content extraction.
    for parent in root.iter():
        for child in list(parent):
            tag = child.tag.rsplit("}", 1)[-1]
            text_image = tag == "image" and (int(child.get("width", 0)), int(child.get("height", 0))) in text_images
            if tag == "text" or (omit_images and tag == "image") or text_image:
                parent.remove(child)
    data = ET.tostring(root, encoding="utf-8")
    return "data:image/svg+xml;base64," + base64.b64encode(data).decode()


def validate_layout(layout):
    """Bound editable geometry and text. Rendering uses textContent, never raw HTML."""
    if not isinstance(layout, dict) or layout.get("schema_version") != 1:
        raise ValueError("Unsupported layout schema.")
    for key in ("width", "height"):
        if not isinstance(layout.get(key), (int, float)) or not math.isfinite(layout[key]) or not 1 <= layout[key] <= 20000:
            raise ValueError("Invalid page dimensions.")
    if not isinstance(layout.get("lines"), list) or len(layout["lines"]) > 10000:
        raise ValueError("Invalid line list.")
    for line in layout["lines"]:
        if not isinstance(line, dict) or not isinstance(line.get("runs"), list) or not line["runs"]:
            raise ValueError("Each line needs text runs.")
        for run in line["runs"]:
            if not isinstance(run, dict) or not isinstance(run.get("text"), str) or len(run["text"]) > 20000:
                raise ValueError("Invalid run text.")
            if any(unicodedata.category(c) == "Co" or c == "\ufffd" for c in run["text"]):
                raise ValueError("Unresolved glyphs must be corrected before approval.")
            if run.get("source_text") and any("LATIN" in unicodedata.name(c, "") for c in run["text"]):
                raise ValueError("Unconverted legacy-font characters remain in this run.")
            for key, length in (("bbox", 4), ("origin", 2)):
                values = run.get(key)
                if not isinstance(values, list) or len(values) != length or any(not isinstance(v, (int, float)) or not math.isfinite(v) or abs(v) > 40000 for v in values):
                    raise ValueError("Invalid run geometry.")
            if not isinstance(run.get("size"), (int, float)) or not math.isfinite(run["size"]) or not 1 <= run["size"] <= 1000:
                raise ValueError("Invalid font size.")
