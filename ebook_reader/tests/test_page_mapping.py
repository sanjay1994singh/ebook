from django.core.exceptions import ValidationError
from django.test import TestCase

from ebook_reader.models import EbookDocument, EbookPageMappingAnchor
from ebook_reader.services.page_mapping import estimate_page_mapping, map_toc_candidates
from ebook_reader.services.page_mapping.anchors import build_mapper_for_document
from ebook_reader.services.page_mapping.estimator import save_detected_mapping
from ebook_reader.services.page_mapping.models import PageNumberSample
from ebook_reader.services.toc_parser.models import TocCandidate
from library.models import Book, Category


def sample(printed, physical, confidence=95):
    return PageNumberSample(
        printed_page_number=printed,
        physical_pdf_page=physical,
        source="test",
        confidence=confidence,
        evidence=[f"printed={printed} physical={physical}"],
    )


def candidate(title, printed_page_number):
    return TocCandidate(
        order=1,
        title=title,
        printed_page_number=printed_page_number,
        proposed_pdf_page=None,
        confidence=0.9,
        source_toc_page=2,
        parser_strategy="test",
    )


class PageMappingTests(TestCase):
    def setUp(self):
        self.category = Category.objects.create(name="Vani")
        self.book = Book.objects.create(
            title=f"Book {Book.objects.count() + 1}",
            slug=f"book-{Book.objects.count() + 1}",
            category=self.category,
        )
        self.document = EbookDocument.objects.create(
            book=self.book,
            total_pdf_pages=100,
        )

    def test_zero_offset(self):
        result = estimate_page_mapping(
            self.document,
            [sample(1, 1), sample(26, 26), sample(40, 40)],
        )

        self.assertEqual(result.status, "detected")
        self.assertEqual(result.proposed_offset, 0)
        self.assertGreater(result.confidence, 0.65)

    def test_positive_offset(self):
        result = estimate_page_mapping(
            self.document,
            [sample(1, 17), sample(26, 42), sample(50, 66)],
        )

        self.assertEqual(result.status, "detected")
        self.assertEqual(result.proposed_offset, 16)

    def test_negative_offset(self):
        result = estimate_page_mapping(
            self.document,
            [sample(10, 5), sample(20, 15), sample(30, 25)],
        )

        self.assertEqual(result.status, "detected")
        self.assertEqual(result.proposed_offset, -5)

    def test_mapping_based_on_multiple_agreeing_samples(self):
        result = estimate_page_mapping(self.document, [sample(4, 9), sample(8, 13)])

        self.assertEqual(result.status, "detected")
        self.assertIn("2 sample(s) agree", result.evidence[0])

    def test_conflicting_samples_require_review(self):
        result = estimate_page_mapping(
            self.document,
            [sample(1, 17), sample(26, 42), sample(40, 70)],
        )

        self.assertEqual(result.status, "review_required")
        self.assertIsNone(result.proposed_offset)
        self.assertTrue(result.conflicts)

    def test_no_printed_page_numbers(self):
        result = estimate_page_mapping(
            self.document,
            [
                PageNumberSample(None, 10, source="ocr", confidence=0),
                PageNumberSample(None, 20, source="ocr", confidence=0),
            ],
        )

        self.assertEqual(result.status, "review_required")
        self.assertIn("No usable printed page numbers", result.warnings[-1])

    def test_missing_ocr_samples(self):
        result = estimate_page_mapping(self.document, [])

        self.assertEqual(result.status, "review_required")
        self.assertIn("No page-number samples", result.warnings[0])

    def test_manual_offset_overrides_auto_detection(self):
        self.document.page_mapping_mode = EbookDocument.PageMappingMode.MANUAL_OFFSET
        self.document.page_number_offset = 7
        self.document.save()

        result = estimate_page_mapping(self.document, [sample(1, 99), sample(2, 100)])

        self.assertEqual(result.mapping_strategy, "manual_offset")
        self.assertEqual(result.proposed_offset, 7)
        self.assertEqual(result.status, "accepted")

    def test_manual_anchors_override_auto_detection(self):
        self.document.page_mapping_mode = EbookDocument.PageMappingMode.MANUAL_ANCHORS
        self.document.save()
        EbookPageMappingAnchor.objects.create(
            ebook=self.document,
            printed_page_number=1,
            physical_pdf_page=17,
            is_verified=True,
        )
        EbookPageMappingAnchor.objects.create(
            ebook=self.document,
            printed_page_number=26,
            physical_pdf_page=42,
            is_verified=True,
        )

        result = estimate_page_mapping(self.document, [sample(1, 1), sample(2, 2)])

        self.assertEqual(result.mapping_strategy, "manual_anchors")
        self.assertEqual(len(result.anchor_pairs), 2)
        self.assertEqual(result.status, "accepted")

    def test_mapped_page_outside_pdf_range(self):
        self.document.page_mapping_mode = EbookDocument.PageMappingMode.MANUAL_OFFSET
        self.document.page_number_offset = 90
        self.document.save()

        mapped, warnings = map_toc_candidates(
            [candidate("Too far", 20)],
            build_mapper_for_document(self.document),
        )

        self.assertIsNone(mapped[0].proposed_pdf_page)
        self.assertIn("outside", warnings[0])

    def test_different_pdfs_can_have_different_offsets(self):
        other_book = Book.objects.create(
            title="Other",
            slug="other",
            category=self.category,
        )
        other_document = EbookDocument.objects.create(book=other_book, total_pdf_pages=100)

        first = estimate_page_mapping(self.document, [sample(1, 17), sample(26, 42)])
        second = estimate_page_mapping(other_document, [sample(1, 5), sample(26, 30)])

        self.assertEqual(first.proposed_offset, 16)
        self.assertEqual(second.proposed_offset, 4)

    def test_toc_candidates_without_printed_page_numbers_stay_unmapped(self):
        result = estimate_page_mapping(self.document, [sample(1, 17), sample(26, 42)])

        mapped, warnings = map_toc_candidates(
            [candidate("No page", None)],
            result,
            total_pdf_pages=100,
        )

        self.assertIsNone(mapped[0].proposed_pdf_page)
        self.assertIn("no printed page number", warnings[0])

    def test_numbering_begins_after_introductory_pages(self):
        result = estimate_page_mapping(
            self.document,
            [sample(1, 12), sample(2, 13), sample(10, 21)],
        )
        mapped, warnings = map_toc_candidates(
            [candidate("Chapter", 26)],
            result,
            total_pdf_pages=100,
        )

        self.assertEqual(result.proposed_offset, 11)
        self.assertEqual(mapped[0].proposed_pdf_page, 37)
        self.assertEqual(warnings, [])

    def test_save_detected_mapping_stores_reviewable_result_without_accepting(self):
        result = estimate_page_mapping(self.document, [sample(1, 17), sample(26, 42)])

        save_detected_mapping(self.document, result)
        self.document.refresh_from_db()

        self.assertEqual(self.document.detected_page_number_offset, 16)
        self.assertEqual(
            self.document.page_mapping_status,
            EbookDocument.PageMappingStatus.DETECTED,
        )
        self.assertIsNone(self.document.page_number_offset)

    def test_anchor_cannot_exceed_total_pdf_pages(self):
        anchor = EbookPageMappingAnchor(
            ebook=self.document,
            printed_page_number=1,
            physical_pdf_page=101,
        )

        with self.assertRaises(ValidationError):
            anchor.full_clean()

    def test_manual_offset_mode_requires_offset(self):
        self.document.page_mapping_mode = EbookDocument.PageMappingMode.MANUAL_OFFSET
        self.document.page_number_offset = None

        with self.assertRaises(ValidationError):
            self.document.full_clean()
