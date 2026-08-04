from dataclasses import dataclass

from ebook_reader.models import EbookDocument

from .models import PageMappingAnchorPair, PageMappingResult
from .validators import validate_mapped_page


@dataclass(frozen=True)
class PageMapper:
    strategy: str
    offset: int | None
    anchors: list[PageMappingAnchorPair]
    total_pdf_pages: int | None = None

    def map_printed_page(self, printed_page_number: int | None) -> tuple[int | None, list[str]]:
        if printed_page_number is None:
            return None, ["Candidate has no printed page number."]
        if self.anchors:
            anchor = self._nearest_anchor(printed_page_number)
            pdf_page = anchor.physical_pdf_page + (
                printed_page_number - anchor.printed_page_number
            )
        elif self.offset is not None:
            pdf_page = printed_page_number + self.offset
        else:
            return None, ["No usable printed-page mapping is available."]
        warnings = validate_mapped_page(
            printed_page_number,
            pdf_page,
            self.total_pdf_pages,
        )
        return (None if warnings else pdf_page), warnings

    def _nearest_anchor(self, printed_page_number: int) -> PageMappingAnchorPair:
        return min(
            self.anchors,
            key=lambda anchor: abs(anchor.printed_page_number - printed_page_number),
        )


def manual_anchor_pairs_for_document(ebook_document: EbookDocument) -> list[PageMappingAnchorPair]:
    return [
        PageMappingAnchorPair(
            printed_page_number=anchor.printed_page_number,
            physical_pdf_page=anchor.physical_pdf_page,
            source="manual",
            is_verified=anchor.is_verified,
        )
        for anchor in ebook_document.page_mapping_anchors.all()
    ]


def build_mapper_for_document(ebook_document: EbookDocument) -> PageMapper:
    if ebook_document.page_mapping_mode == EbookDocument.PageMappingMode.NONE:
        return PageMapper("none", None, [], ebook_document.total_pdf_pages)
    if ebook_document.page_mapping_mode == EbookDocument.PageMappingMode.MANUAL_ANCHORS:
        return PageMapper(
            "manual_anchors",
            None,
            manual_anchor_pairs_for_document(ebook_document),
            ebook_document.total_pdf_pages,
        )
    if ebook_document.page_mapping_mode == EbookDocument.PageMappingMode.MANUAL_OFFSET:
        return PageMapper(
            "manual_offset",
            ebook_document.page_number_offset,
            [],
            ebook_document.total_pdf_pages,
        )
    if ebook_document.page_mapping_status == EbookDocument.PageMappingStatus.ACCEPTED:
        return PageMapper(
            "accepted_offset",
            ebook_document.page_number_offset,
            [],
            ebook_document.total_pdf_pages,
        )
    return PageMapper(
        "detected_offset",
        ebook_document.detected_page_number_offset,
        [],
        ebook_document.total_pdf_pages,
    )


def result_from_manual_mapping(ebook_document: EbookDocument) -> PageMappingResult | None:
    if ebook_document.page_mapping_mode == EbookDocument.PageMappingMode.NONE:
        return PageMappingResult(
            mapping_strategy="none",
            confidence=1.0,
            evidence=["EbookDocument is configured as no printed page mapping."],
            status="accepted",
        )
    if ebook_document.page_mapping_mode == EbookDocument.PageMappingMode.MANUAL_OFFSET:
        if ebook_document.page_number_offset is None:
            return PageMappingResult(
                mapping_strategy="manual_offset",
                warnings=["Manual offset mode is selected but no offset is configured."],
                status="review_required",
            )
        return PageMappingResult(
            mapping_strategy="manual_offset",
            proposed_offset=ebook_document.page_number_offset,
            confidence=1.0,
            evidence=["Manual page number offset is configured."],
            status="accepted",
        )
    if ebook_document.page_mapping_mode == EbookDocument.PageMappingMode.MANUAL_ANCHORS:
        anchors = manual_anchor_pairs_for_document(ebook_document)
        return PageMappingResult(
            mapping_strategy="manual_anchors",
            anchor_pairs=anchors,
            confidence=1.0 if anchors else 0.0,
            evidence=[f"{len(anchors)} manual anchor(s) configured."],
            warnings=[] if anchors else ["Manual anchor mode is selected but no anchors exist."],
            status="accepted" if anchors else "review_required",
        )
    return None
