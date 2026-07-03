from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render

from .models import Book, BookPage, Category, Chapter


def web_home(request):
    """Website home page: featured books, intro, contact aur footer dikhata hai."""
    books = Book.objects.filter(is_published=True).select_related("category")[:5]
    categories = Category.objects.all()
    return render(
        request,
        "library/web/home.html",
        {
            "books": books,
            "categories": categories,
        },
    )


def web_book_list(request):
    """Uploaded/published books ko catalog UI me dikhata hai."""
    books = Book.objects.filter(is_published=True).select_related("category")
    categories = Category.objects.all()
    return render(
        request,
        "library/web/book_list.html",
        {
            "books": books,
            "categories": categories,
        },
    )


def web_patrika_list(request):
    """Patrika landing page: magazine cards dikhata hai."""
    magazines = [
        {
            "title": "गीत-गोविंद (हिन्दी)",
            "subtitle": "गीत-गोविंद (हिन्दी)",
            "language": "हिन्दी/संस्कृत",
            "issues": 46,
            "latest": "वर्ष 4 संख्या 10 (जुलाई, 2026)",
            "cover": "गीत-गोविंद",
        },
        {
            "title": "गीत-गोविंद (अंग्रेजी)",
            "subtitle": "गीत-गोविंद (अंग्रेजी)",
            "language": "अंग्रेजी",
            "issues": 46,
            "latest": "वर्ष 4 संख्या 7 (अप्रैल, 2026)",
            "cover": "Geet-Govind",
        },
        {
            "title": "कल्याण (हिन्दी)",
            "subtitle": "कल्याण (हिन्दी)",
            "language": "हिन्दी/संस्कृत",
            "issues": 132,
            "latest": "वर्ष 11 संख्या 12 (जुलाई, 1937)",
            "cover": "कल्याण",
        },
        {
            "title": "कल्याण कल्पतरु (अंग्रेजी)",
            "subtitle": "कल्याण कल्पतरु (अंग्रेजी)",
            "language": "अंग्रेजी",
            "issues": 300,
            "latest": "वर्ष 25 संख्या 12 (दिसंबर, 1961)",
            "cover": "Kalyana Kalpataru",
        },
        {
            "title": "विवेक वाणी (बांग्ला)",
            "subtitle": "विवेक वाणी (बांग्ला)",
            "language": "बांग्ला",
            "issues": 7,
            "latest": "संख्या 3 (मई, 2025)",
            "cover": "विवेक वाणी",
        },
    ]
    return render(request, "library/web/patrika_list.html", {"magazines": magazines})


def web_audio_list(request):
    """Audio page: pravachan/audio list dikhata hai."""
    audio_items = [
        {"title": "श्री गुरु वन्दना", "speaker": "श्री हरिदासीय परम्परा", "duration": "00:15:39"},
        {"title": "01 मंगलाचरण", "speaker": "स्वामी श्री हरिदास", "duration": "00:09:14"},
        {"title": "नित्य निकुंज रसोपासना", "speaker": "संत वाणी", "duration": "00:05:22"},
        {"title": "01 भावनामृत - कुञ्ज बिहारी", "speaker": "श्री वृन्दावन धाम", "duration": "00:16:08"},
        {"title": "02 कृपा का स्वरूप", "speaker": "रसिक संत वचन", "duration": "00:08:56"},
        {"title": "03 नाम जप की महिमा", "speaker": "सत्संग प्रवचन", "duration": "00:16:31"},
        {"title": "राधा नाम रस", "speaker": "भक्ति संगीत", "duration": "00:25:07"},
        {"title": "श्रीहरिदासजी महाराज", "speaker": "जीवन चरित्र", "duration": "00:42:41"},
        {"title": "02 अमृत वचन", "speaker": "अनमोल लेख से", "duration": "07:53:34"},
        {"title": "मधुर भजन संग्रह", "speaker": "गायन", "duration": "01:34:25"},
        {"title": "06 प्रभु मिलन", "speaker": "रस वाणी", "duration": "01:20:12"},
        {"title": "02 संत कृपा", "speaker": "सत्संग", "duration": "00:17:09"},
    ]
    return render(request, "library/web/audio_list.html", {"audio_items": audio_items})


def web_divine_quotes(request):
    """Amrit Vachan page: devotional quote cards dikhata hai."""
    quotes = [
        {
            "text": "जैसे सूर्य सबको समान प्रकाश देता है, वैसे ही भगवान की कृपा सब जीवों पर समान रूप से बरसती है।",
            "source": "अमृत वचन",
        },
        {
            "text": "नाम स्मरण से चित्त निर्मल होता है और निर्मल चित्त में ही प्रेम का प्रकाश प्रकट होता है।",
            "source": "भक्ति मार्ग",
        },
        {
            "text": "सेवा वही है जिसमें अपना मान नहीं, प्रभु की प्रसन्नता ही एकमात्र लक्ष्य हो।",
            "source": "संत वाणी",
        },
        {
            "text": "सत्संग मनुष्य को भीतर से बदलता है; यह जीवन में शांति और सद्बुद्धि का मार्ग खोलता है।",
            "source": "सत्संग प्रसंग",
        },
        {
            "text": "श्रद्धा और धैर्य से किया गया छोटा प्रयास भी प्रभु कृपा से महान फल देता है।",
            "source": "अनमोल लेख",
        },
        {
            "text": "जिस हृदय में दया, नम्रता और प्रेम है, वहीं सच्चे धर्म का निवास है।",
            "source": "दिव्य विचार",
        },
        {
            "text": "वाणी मधुर हो, मन सरल हो और कर्म सेवा में लगे हों, यही साधना का सुंदर रूप है।",
            "source": "अमृत वचन",
        },
        {
            "text": "ईश्वर को पाने का मार्ग दूर नहीं; अपने भीतर के अहंकार को शांत करना ही पहला कदम है।",
            "source": "आध्यात्मिक चिंतन",
        },
    ]
    return render(request, "library/web/divine_quotes.html", {"quotes": quotes})


def web_book_detail(request, slug):
    """Ek book ka detail page aur vishay suchi dikhata hai."""
    book = get_object_or_404(Book.objects.select_related("category"), slug=slug, is_published=True)
    chapters = Chapter.objects.filter(book=book).prefetch_related("pages")
    first_page = (
        BookPage.objects.filter(chapter__book=book)
        .order_by("chapter__order", "chapter__id", "page_number", "id")
        .first()
    )
    return render(
        request,
        "library/web/book_detail.html",
        {
            "book": book,
            "chapters": chapters,
            "first_page": first_page,
        },
    )


def web_chapter_start(request, chapter_id):
    """Chapter par click karne par us chapter ke first page par bhejta hai."""
    chapter = get_object_or_404(Chapter.objects.select_related("book"), id=chapter_id)
    first_page = chapter.pages.order_by("page_number", "id").first()
    if first_page:
        return redirect("web_reader_page", page_id=first_page.id)
    return redirect("web_book_detail", slug=chapter.book.slug)


def _reader_context(page):
    """Reader ke liye current, previous aur next page data ready karta hai."""
    page = get_object_or_404(
        BookPage.objects.select_related("chapter", "chapter__book"),
        id=page.id,
    )
    book = page.chapter.book
    book_pages = list(
        BookPage.objects.filter(chapter__book=book)
        .select_related("chapter")
        .order_by("chapter__order", "chapter__id", "page_number", "id")
    )
    page_ids = [book_page.id for book_page in book_pages]
    current_index = page_ids.index(page.id)
    previous_page = book_pages[current_index - 1] if current_index > 0 else None
    next_page = book_pages[current_index + 1] if current_index < len(book_pages) - 1 else None

    return {
        "book": book,
        "page": page,
        "previous_page": previous_page,
        "next_page": next_page,
        "current_index": current_index + 1,
        "total_pages": len(book_pages),
    }


def web_reader_page(request, page_id):
    """Reader page: current PDF page dikhata hai."""
    page = get_object_or_404(BookPage, id=page_id)
    context = _reader_context(page)
    return render(
        request,
        "library/web/reader.html",
        context,
    )


def web_reader_page_data(request, page_id):
    """Next/previous click par JavaScript ko fast reader data deta hai."""
    page = get_object_or_404(BookPage, id=page_id)
    context = _reader_context(page)
    current_page = context["page"]
    previous_page = context["previous_page"]
    next_page = context["next_page"]

    image_url = request.build_absolute_uri(current_page.page_image.url) if current_page.page_image else ""
    reader_url = request.build_absolute_uri(f"/web/reader/{current_page.id}/")
    return JsonResponse(
        {
            "id": current_page.id,
            "title": current_page.title or current_page.chapter.title,
            "content": current_page.content,
            "image_url": image_url,
            "reader_url": reader_url,
            "previous_id": previous_page.id if previous_page else None,
            "next_id": next_page.id if next_page else None,
            "current_index": context["current_index"],
            "total_pages": context["total_pages"],
        }
    )
