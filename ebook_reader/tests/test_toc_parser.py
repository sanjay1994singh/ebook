from django.test import TestCase

from ebook_reader.models import EbookDocument
from ebook_reader.services.toc_parser import parse_toc, resolve_effective_toc_range
from ebook_reader.services.toc_parser.exceptions import EffectiveTocRangeError
from ebook_reader.services.toc_parser.models import (
    TocOcrWord,
    TocPageInput,
    TocParserInput,
)


def word(text, left, top, *, width=60, height=20, confidence=90, line_id=1):
    return TocOcrWord(
        text=text,
        confidence=confidence,
        left=left,
        top=top,
        width=width,
        height=height,
        block_id=1,
        paragraph_id=1,
        line_id=line_id,
    )


def three_column_page(page_number, rows, *, width=1000, y_start=100):
    words = []
    for index, (order, title, page) in enumerate(rows, start=1):
        y = y_start + index * 40
        if order is not None:
            words.append(word(str(order), 30, y, width=35, line_id=index))
        title_tokens = title.split()
        x = 240
        for token in title_tokens:
            words.append(word(token, x, y, width=max(45, len(token) * 10), line_id=index))
            x += max(55, len(token) * 11)
        if page is not None:
            words.append(word(str(page), 880, y, width=45, line_id=index))
    return TocPageInput(page_number=page_number, ocr_words=words, width=width, height=1400)


def parser_input(pages, *, start=2, end=None, total=200, warnings=None):
    return TocParserInput(
        ebook_document_id=1,
        effective_toc_start_page=start,
        effective_toc_end_page=end or pages[-1].page_number,
        total_pdf_pages=total,
        pages=pages,
        extraction_warnings=warnings or [],
    )


class TocParserTests(TestCase):
    def test_one_page_three_column_hindi_toc(self):
        page = three_column_page(
            2,
            [
                (1, "प्रथम पाठ", 10),
                (2, "दूसरा पाठ", 20),
            ],
        )

        result = parse_toc(parser_input([page]))

        self.assertEqual(result.total_detected, 2)
        self.assertEqual(result.valid_candidates[0].title, "प्रथम पाठ")
        self.assertEqual(result.valid_candidates[0].printed_page_number, 10)
        self.assertEqual(result.valid_candidates[0].parser_strategy, "three_column_anchor")

    def test_multi_page_three_column_hindi_toc(self):
        pages = [
            three_column_page(9, [(1, "पहला अध्याय", 11), (2, "दूसरा अध्याय", 18)]),
            three_column_page(10, [(3, "तीसरा अध्याय", 26), (4, "चौथा अध्याय", 30)]),
        ]

        result = parse_toc(parser_input(pages, start=9, end=10))

        self.assertEqual([item.order for item in result.valid_candidates], [1, 2, 3, 4])
        self.assertEqual(result.valid_candidates[-1].source_toc_page, 10)

    def test_two_column_title_page_toc(self):
        page = TocPageInput(
            page_number=4,
            width=1000,
            ocr_words=[
                word("Introduction", 160, 100, line_id=1),
                word("5", 890, 100, line_id=1),
                word("Practice", 160, 150, line_id=2),
                word("21", 890, 150, line_id=2),
            ],
        )

        result = parse_toc(parser_input([page], start=4))

        self.assertEqual(result.total_detected, 2)
        self.assertIsNone(result.valid_candidates[0].order)
        self.assertEqual(result.missing_serial_numbers, 2)
        self.assertEqual(result.valid_candidates[0].parser_strategy, "two_column_title_page")

    def test_english_toc_from_embedded_text(self):
        page = TocPageInput(
            page_number=2,
            embedded_text="Contents\n1. First Chapter 8\n2. Second Chapter 15",
        )

        result = parse_toc(parser_input([page]))

        self.assertEqual([item.title for item in result.valid_candidates], ["First Chapter", "Second Chapter"])
        self.assertEqual(result.page_level_diagnostics[0].rows_filtered, 1)

    def test_embedded_text_column_blocks_are_paired(self):
        page = TocPageInput(
            page_number=9,
            embedded_text=(
                "9\n"
                "1-\n"
                "2-\n"
                "26\n"
                "28\n"
                "fo’k; lwph %-\n"
                "dz0 la0 fooj.k i`0 la0\n"
                "ekbZ jh lgt tksjh izxV Hk;h tq]\n"
                "#fp ds Ádkl ijLij [ksyu ykxs\n"
                "vkHkkl mYFkk Vhdk dsfyeky th dh"
            ),
        )

        result = parse_toc(parser_input([page], start=9, end=9, total=218))

        self.assertEqual(result.total_detected, 2)
        self.assertEqual(result.valid_candidates[0].order, 1)
        self.assertEqual(result.valid_candidates[0].title, "ekbZ jh lgt tksjh izxV Hk;h tq]")
        self.assertEqual(result.valid_candidates[0].printed_page_number, 26)
        self.assertEqual(result.valid_candidates[0].parser_strategy, "embedded_column_block")

    def test_mixed_hindi_english_toc(self):
        page = three_column_page(3, [(1, "Bhakti योग", 7), (2, "Prem Rasa", 15)])

        result = parse_toc(parser_input([page], start=3))

        self.assertEqual(result.valid_candidates[0].title, "Bhakti योग")
        self.assertEqual(result.valid_candidates[1].title, "Prem Rasa")

    def test_devanagari_digits(self):
        page = TocPageInput(
            page_number=2,
            embedded_text="१ प्रथम पाठ १०\n२ दूसरा पाठ २०",
        )

        result = parse_toc(parser_input([page]))

        self.assertEqual(result.valid_candidates[0].order, 1)
        self.assertEqual(result.valid_candidates[1].printed_page_number, 20)

    def test_arabic_digits(self):
        page = TocPageInput(page_number=2, embedded_text="1 First 10\n2 Second 20")

        result = parse_toc(parser_input([page]))

        self.assertEqual(result.valid_candidates[0].order, 1)
        self.assertEqual(result.valid_candidates[1].printed_page_number, 20)

    def test_wrapped_titles_are_joined_with_layout_evidence(self):
        page = TocPageInput(
            page_number=2,
            width=1000,
            ocr_words=[
                word("1", 30, 100, width=30, line_id=1),
                word("Long", 240, 100, line_id=1),
                word("title", 300, 100, line_id=1),
                word("44", 890, 100, line_id=1),
                word("continued", 240, 125, line_id=2),
            ],
        )

        result = parse_toc(parser_input([page]))

        self.assertIn("continued", result.valid_candidates[0].title)
        self.assertIn("Wrapped title", result.valid_candidates[0].warnings[0])

    def test_missing_serial_number_is_reported(self):
        page = TocPageInput(
            page_number=2,
            width=1000,
            ocr_words=[
                word("Title", 200, 100, line_id=1),
                word("12", 890, 100, line_id=1),
            ],
        )

        result = parse_toc(parser_input([page]))

        self.assertEqual(result.missing_serial_numbers, 1)
        self.assertIsNone(result.valid_candidates[0].order)

    def test_duplicate_serial_number_is_invalid(self):
        page = three_column_page(2, [(1, "First", 10), (1, "Second", 20)])

        result = parse_toc(parser_input([page]))

        self.assertEqual(result.duplicates, [1])
        self.assertEqual(len(result.invalid_candidates), 2)

    def test_missing_printed_page_number_keeps_candidate_for_review(self):
        page = three_column_page(2, [(1, "Only Title", None)])

        result = parse_toc(parser_input([page]))

        self.assertEqual(result.total_detected, 1)
        self.assertIsNone(result.valid_candidates[0].printed_page_number)
        self.assertIn("Printed page number was not available.", result.valid_candidates[0].warnings)

    def test_repeated_page_headers_and_footers_are_filtered(self):
        page1 = TocPageInput(page_number=2, embedded_text="विषय सूची\n1 First 10\nPage 2")
        page2 = TocPageInput(page_number=3, embedded_text="विषय सूची\n2 Second 20\nPage 2")

        result = parse_toc(parser_input([page1, page2], end=3))

        self.assertEqual(result.total_detected, 2)
        self.assertGreaterEqual(result.page_level_diagnostics[0].rows_filtered, 1)

    def test_garbled_embedded_text_with_usable_ocr_prefers_ocr(self):
        page = three_column_page(2, [(1, "साफ पाठ", 10)])
        page = TocPageInput(
            page_number=page.page_number,
            embedded_text="à¤µà¤¿à¤·à¤¯ ????",
            ocr_words=page.ocr_words,
            width=1000,
        )

        result = parse_toc(parser_input([page]))

        self.assertEqual(result.valid_candidates[0].title, "साफ पाठ")
        self.assertIn("garbled", result.page_level_diagnostics[0].warnings[0])

    def test_no_valid_structured_rows_returns_unclassified_rows(self):
        page = TocPageInput(page_number=2, embedded_text="This is only a heading")

        result = parse_toc(parser_input([page]))

        self.assertEqual(result.total_detected, 0)
        self.assertTrue(result.requires_review)
        self.assertEqual(len(result.unclassified_rows), 1)

    def test_ocr_title_only_rows_are_kept_as_reviewable_candidates(self):
        page = TocPageInput(
            page_number=9,
            width=1000,
            ocr_words=[
                word("First", 180, 100, line_id=1),
                word("lesson", 250, 100, line_id=1),
                word("Second", 180, 145, line_id=2),
                word("lesson", 260, 145, line_id=2),
            ],
        )

        result = parse_toc(parser_input([page], start=9, end=9))

        self.assertEqual(result.total_detected, 2)
        self.assertEqual([item.title for item in result.valid_candidates], ["First lesson", "Second lesson"])
        self.assertTrue(all(item.order is None for item in result.valid_candidates))
        self.assertTrue(all(item.printed_page_number is None for item in result.valid_candidates))
        self.assertEqual(result.valid_candidates[0].parser_strategy, "title_only_ocr")

    def test_hindi_ocr_title_only_filters_latin_hallucination_lines(self):
        page = TocPageInput(
            page_number=9,
            width=1000,
            ocr_words=[
                word("ऐसी", 180, 100, line_id=1),
                word("तौ", 240, 100, line_id=1),
                word("विचित्र", 290, 100, line_id=1),
                word("जोरी", 380, 100, line_id=1),
                word("बनी", 450, 100, line_id=1),
                word("Sea", 180, 145, line_id=2),
                word("Bad", 230, 145, line_id=2),
                word("Saat", 280, 145, line_id=2),
                word("Para", 340, 145, line_id=2),
                word("अद्भुत", 180, 190, line_id=3),
                word("गति", 260, 190, line_id=3),
                word("उपजत", 310, 190, line_id=3),
            ],
        )

        result = parse_toc(parser_input([page], start=9, end=9))

        self.assertEqual([item.title for item in result.valid_candidates], [
            "ऐसी तौ विचित्र जोरी बनी",
            "अद्भुत गति उपजत",
        ])

    def test_one_toc_entry_only(self):
        page = TocPageInput(page_number=2, embedded_text="1 Only lesson 12")

        result = parse_toc(parser_input([page]))

        self.assertEqual(result.total_detected, 1)
        self.assertEqual(result.valid_candidates[0].title, "Only lesson")

    def test_different_page_sizes_and_coordinate_scales(self):
        small = three_column_page(2, [(1, "Small Page", 5)], width=500)
        large = three_column_page(3, [(2, "Large Page", 15)], width=2000)

        result = parse_toc(parser_input([small, large], end=3))

        self.assertEqual(result.total_detected, 2)
        self.assertEqual(result.valid_candidates[1].title, "Large Page")

    def test_effective_range_can_be_other_than_pages_9_to_13(self):
        page = three_column_page(23, [(1, "Different Range", 40)])

        result = parse_toc(parser_input([page], start=23, end=23))

        self.assertEqual(result.valid_candidates[0].source_toc_page, 23)

    def test_none_or_missing_range_returns_no_toc_review_result(self):
        result = parse_toc(
            TocParserInput(
                ebook_document_id=1,
                effective_toc_start_page=None,
                effective_toc_end_page=None,
                total_pdf_pages=20,
            )
        )

        self.assertTrue(result.no_toc)
        self.assertTrue(result.requires_review)

    def test_invalid_effective_range_is_rejected(self):
        with self.assertRaises(EffectiveTocRangeError):
            parse_toc(parser_input([three_column_page(2, [(1, "Bad", 3)])], start=5, end=2))

    def test_resolve_effective_range_uses_manual_before_detected_values(self):
        document = EbookDocument(
            toc_mode=EbookDocument.TocMode.MANUAL,
            toc_start_page=9,
            toc_end_page=13,
            detected_toc_start_page=2,
            detected_toc_end_page=3,
        )

        start, end, warnings = resolve_effective_toc_range(document)

        self.assertEqual((start, end), (9, 13))
        self.assertEqual(warnings, [])

    def test_resolve_effective_range_auto_requires_accepted_detected_values(self):
        document = EbookDocument(toc_mode=EbookDocument.TocMode.AUTO)

        start, end, warnings = resolve_effective_toc_range(document)

        self.assertEqual((start, end), (None, None))
        self.assertIn("No accepted TOC range", warnings[0])
