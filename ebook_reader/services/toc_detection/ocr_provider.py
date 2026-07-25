from django.conf import settings

from ebook_reader.services.ocr import get_ocr_engine
from ebook_reader.services.pdf_rendering import render_pdf_page_to_image


def ocr_text_provider_for_document(ebook_document):
    engine = get_ocr_engine()

    def provider(_reader, page_index):
        image = render_pdf_page_to_image(
            ebook_document,
            page_index + 1,
            dpi=settings.EBOOK_RENDER_DPI,
        )
        return engine.extract(image).full_text

    return provider
