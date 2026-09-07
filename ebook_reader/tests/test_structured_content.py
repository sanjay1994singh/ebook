import copy
import json
import tempfile
from unittest.mock import patch

import fitz
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from ebook_reader.models import ContentEdition, ContentPage
from ebook_reader.services.structured_content import process_edition, publish_edition, queue_content
from ebook_reader.services.structured_extraction import convert_legacy_lines, extract_page, validate_layout, run_emphasis
from library.models import Book


def source_pdf():
    doc = fitz.open()
    page = doc.new_page(width=400, height=600)
    page.insert_text((45, 80), "A book heading", fontsize=26)
    page.insert_text((70, 120), "First verse line", fontsize=16)
    page.insert_text((100, 145), "Indented second line", fontsize=16)
    page.draw_rect((30, 40, 370, 550))
    data = doc.tobytes()
    doc.close()
    return data


class StructuredContentTests(TestCase):
    def test_embedded_bold_face_is_used_when_pdf_span_flags_are_missing(self):
        fonts = {"F1": {"style": " Bold"}, "F2": {"style": "Regular"}}
        self.assertTrue(run_emphasis({"font": "F1", "flags": 0}, fonts)["bold"])
        self.assertFalse(run_emphasis({"font": "F2", "flags": 0}, fonts)["bold"])
        self.assertTrue(run_emphasis({"font": "F2", "flags": 16}, fonts)["bold"])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.settings_override = override_settings(MEDIA_ROOT=self.temp.name, CONTENT_SOURCE_ROOT=self.temp.name + "/private")
        self.settings_override.enable()
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(self.settings_override.disable)
        self.book = Book.objects.create(title="Structured sample", is_published=True, auto_extract_pdf=False,
            pdf_file=SimpleUploadedFile("sample.pdf", source_pdf()))
        self.staff = get_user_model().objects.create_user(username="reviewer", is_staff=True, is_superuser=True)

    def draft(self):
        edition = queue_content(self.book, dispatch=False)
        process_edition(edition.pk)
        edition.refresh_from_db()
        return edition

    def review_and_publish(self, edition):
        edition.pages.update(reviewed_at=timezone.now(), reviewed_by=self.staff)
        return publish_edition(edition.pk)

    def test_extract_preserves_sizes_positions_and_drawings_without_page_image(self):
        with fitz.open(stream=source_pdf(), filetype="pdf") as doc:
            layout, method, issues = extract_page(doc, doc[0])
        self.assertEqual(method, "embedded")
        self.assertEqual([r["size"] for line in layout["lines"] for r in line["runs"]], [26, 16, 16])
        self.assertEqual(layout["lines"][2]["runs"][0]["origin"], [100, 145])
        import base64
        decoration = base64.b64decode(layout["decoration"].split(",", 1)[1]).decode()
        self.assertNotIn("A book heading", decoration)
        self.assertIn("path", decoration)
        self.assertNotIn("data:image/png", decoration)
        validate_layout(layout)

    def test_upload_is_idempotent_and_source_is_snapshot(self):
        first = queue_content(self.book, dispatch=False)
        second = queue_content(self.book, dispatch=False)
        self.assertEqual(first.pk, second.pk)
        self.assertNotEqual(first.source_pdf.name, self.book.pdf_file.name)
        with first.source_pdf.open("rb") as snapshot, self.book.pdf_file.open("rb") as source:
            self.assertEqual(snapshot.read(), source.read())

    def test_unreviewed_or_missing_pages_cannot_publish(self):
        edition = self.draft()
        self.assertEqual(edition.status, "review")
        with self.assertRaises(ValidationError): publish_edition(edition.pk)
        edition.pages.update(reviewed_at=timezone.now())
        ContentEdition.objects.filter(pk=edition.pk).update(total_pages=2)
        with self.assertRaises(ValidationError): publish_edition(edition.pk)

    def test_drafts_and_source_previews_are_not_public(self):
        edition = self.draft()
        self.assertEqual(self.client.get(reverse("ebook_reader:content_page", args=[edition.pk, 1])).status_code, 404)
        self.assertEqual(self.client.get(reverse("ebook_reader:content_source", args=[edition.pk, 1])).status_code, 302)
        self.assertEqual(self.client.get(reverse("ebook_reader:content_reader", args=[self.book.pk])).status_code, 404)
        self.assertFalse(self.client.get(reverse("ebook_reader:content_manifest", args=[self.book.pk])).json()["available"])

    def test_published_reader_search_and_unpublish_access(self):
        edition = self.review_and_publish(self.draft())
        url = reverse("ebook_reader:content_page", args=[edition.pk, 1])
        self.assertEqual(self.client.get(url).status_code, 200)
        results = self.client.get(reverse("ebook_reader:content_search", args=[edition.pk]), {"q": "Indented"}).json()
        self.assertEqual(results["results"][0]["page"], 1)
        self.assertEqual(self.client.get(reverse("ebook_reader:content_reader", args=[self.book.pk])).status_code, 200)
        self.book.is_published = False; self.book.save()
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_new_version_preserves_approved_content_and_replaces_atomically(self):
        first = self.review_and_publish(self.draft())
        old_page = first.pages.first()
        old_page.plain_text = "Human correction"; old_page.save()
        second = queue_content(self.book, dispatch=False, new_version=True)
        process_edition(second.pk)
        first.refresh_from_db(); old_page.refresh_from_db()
        self.assertEqual(first.status, "published")
        self.assertEqual(old_page.plain_text, "Human correction")
        self.review_and_publish(second)
        first.refresh_from_db()
        self.assertEqual(first.status, "archived")

    def test_ocr_failure_never_becomes_publishable(self):
        edition = queue_content(self.book, dispatch=False)
        with patch("ebook_reader.services.structured_extraction.is_garbled_text", return_value=True), patch("ebook_reader.services.structured_extraction.ocr_lines", side_effect=RuntimeError("Hindi OCR unavailable")):
            with self.assertRaisesRegex(RuntimeError, "Hindi OCR unavailable"): process_edition(edition.pk)
        edition.refresh_from_db()
        self.assertEqual(edition.status, "failed")
        self.assertIn("Hindi OCR unavailable", edition.error)
        with self.assertRaises(ValidationError): publish_edition(edition.pk)

    def test_retry_does_not_overwrite_manual_draft_corrections(self):
        edition = self.draft(); page = edition.pages.first()
        page.plain_text = "Do not overwrite"; page.revision = 5; page.save()
        ContentEdition.objects.filter(pk=edition.pk).update(status="failed")
        process_edition(edition.pk); page.refresh_from_db()
        self.assertEqual(page.plain_text, "Do not overwrite")
        self.assertEqual(page.revision, 5)

    def test_editor_version_conflict_and_published_immutability(self):
        edition = self.draft(); page = edition.pages.first()
        self.client.force_login(self.staff)
        url = reverse("ebook_reader:content_review_save", args=[edition.pk, 1])
        data = {"revision": page.revision, "lines": copy.deepcopy(page.layout["lines"]), "approve": True}
        data["lines"][0]["runs"][0]["text"] = "Corrected heading"
        response = self.client.post(url, json.dumps(data), content_type="application/json")
        self.assertEqual(response.status_code, 200)
        page.refresh_from_db()
        self.assertIn("Corrected heading", page.plain_text)
        self.assertIsNotNone(page.reviewed_at)
        self.assertEqual(self.client.post(url, json.dumps(data), content_type="application/json").status_code, 409)
        publish_edition(edition.pk)
        data["revision"] = page.revision
        self.assertEqual(self.client.post(url, json.dumps(data), content_type="application/json").status_code, 409)

    def test_draft_edit_resets_approval_and_requires_permission_and_csrf(self):
        edition = self.draft(); page = edition.pages.first()
        page.reviewed_at = timezone.now(); page.save()
        url = reverse("ebook_reader:content_review_save", args=[edition.pk, 1])
        data = {"revision": 1, "lines": page.layout["lines"], "approve": False}
        limited = get_user_model().objects.create_user(username="limited", is_staff=True)
        self.client.force_login(limited)
        self.assertEqual(self.client.get(reverse("ebook_reader:content_source", args=[edition.pk, 1])).status_code, 403)
        self.assertEqual(self.client.post(url, json.dumps(data), content_type="application/json").status_code, 403)
        csrf_client = Client(enforce_csrf_checks=True); csrf_client.force_login(self.staff)
        self.assertEqual(csrf_client.post(url, json.dumps(data), content_type="application/json").status_code, 403)
        self.client.force_login(self.staff)
        self.assertEqual(self.client.post(url, json.dumps(data), content_type="application/json").status_code, 200)
        page.refresh_from_db(); self.assertIsNone(page.reviewed_at)

    def test_invalid_geometry_and_unresolved_glyphs_cannot_be_approved(self):
        page = self.draft().pages.first()
        bad = copy.deepcopy(page.layout)
        bad["lines"][0]["runs"][0]["size"] = float("nan")
        with self.assertRaises(ValueError): validate_layout(bad)
        bad = copy.deepcopy(page.layout); bad["lines"][0]["runs"][0]["text"] = "\ufffd"
        with self.assertRaises(ValueError): validate_layout(bad)

    def test_upload_admin_queues_content_instead_of_replacing_library_pages(self):
        from django.contrib import admin
        from django.test import RequestFactory
        from library.admin import BookAdmin
        from unittest.mock import Mock
        request = RequestFactory().post("/"); request.user = self.staff
        model_admin = BookAdmin(Book, admin.site)
        self.book.auto_extract_pdf = True
        with patch("ebook_reader.services.structured_content.queue_content") as queue, patch.object(model_admin, "message_user"), patch("library.admin.extract_pdf_to_book") as legacy:
            queue.return_value = Mock(pk=123)
            model_admin.save_model(request, self.book, Mock(changed_data=["pdf_file"]), True)
        queue.assert_called_once(); legacy.assert_not_called()

    def test_krutidev_conversion_preserves_source_runs_and_braj_words(self):
        lines = [{"bbox": [1, 1, 200, 40], "runs": [{"text": "nwts Jh foiqy] fcgkjhnkl xkÅ¡ eSaA", "font": "F1", "size": 24, "origin": [1, 30], "bbox": [1, 1, 200, 40]}]}]
        result, issues = convert_legacy_lines(lines, {"F1": {"family": "Kruti Dev 021"}})
        self.assertEqual(result[0]["runs"][0]["text"], "दूजे श्री विपुल, बिहारीदास गाऊँ मैं।")
        self.assertEqual(result[0]["runs"][0]["source_text"], lines[0]["runs"][0]["text"])
        self.assertEqual(result[0]["runs"][0]["size"], 24)
        self.assertEqual(lines[0]["runs"][0]["text"], "nwts Jh foiqy] fcgkjhnkl xkÅ¡ eSaA")

    def test_converter_never_applies_to_unknown_or_unicode_fonts(self):
        result, issues = convert_legacy_lines([{"runs": [{"text": "Normal English", "font": "F1"}]}], {"F1": {"family": "Arial"}})
        self.assertIsNone(result)

    def test_krutidev_half_ya_and_unmapped_characters(self):
        fonts = {"F1": {"family": "Kruti Dev 021"}}
        result, _ = convert_legacy_lines([{"runs": [{"text": "HkjîkS", "font": "F1"}]}], fonts)
        self.assertEqual(result[0]["runs"][0]["text"], "भर्यौ")
        result, issues = convert_legacy_lines([{"runs": [{"text": "Ωø", "font": "F1"}]}], fonts)
        self.assertIsNone(result)
        self.assertTrue(issues)

    def test_published_chapter_opens_content_at_source_page(self):
        from library.models import Chapter
        edition = self.draft()
        edition.pages.update(reviewed_at=timezone.now())
        publish_edition(edition.pk)
        chapter = Chapter.objects.create(book=self.book, title="Chapter", start_page=1)
        response = self.client.get(reverse("web_chapter_start", args=[chapter.pk]))
        self.assertRedirects(response, reverse("ebook_reader:content_reader", args=[self.book.pk]) + "?page=1")

    def test_private_source_has_no_media_url(self):
        edition = queue_content(self.book, dispatch=False)
        with self.assertRaises(ValueError):
            _ = edition.source_pdf.url

    def test_review_progress_tracks_approval_and_is_not_public(self):
        edition = self.draft()
        url = reverse("ebook_reader:content_page", args=[edition.pk, 1])
        self.client.force_login(self.staff)
        summary = self.client.get(url).json()["review_summary"]
        self.assertEqual(summary, {"total": 1, "approved": 0, "pending": [1], "available": [1]})
        page = edition.pages.get(page_number=1)
        response = self.client.post(reverse("ebook_reader:content_review_save", args=[edition.pk, 1]),
            json.dumps({"revision": page.revision, "lines": page.layout["lines"], "approve": True}), content_type="application/json")
        self.assertEqual(response.json()["review_summary"]["approved"], 1)
        self.assertEqual(response.json()["review_summary"]["pending"], [])
        publish_edition(edition.pk)
        self.client.logout()
        self.assertNotIn("review_summary", self.client.get(url).json())
