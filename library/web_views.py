from django.db.models import Prefetch, Q
from django.core.paginator import Paginator
from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from app_updates.models import AppBuildRelease
from banners.models import Banner
from ebook_reader.models import EbookDocument
from ebook_reader.views import user_can_preview_reader
from .models import AudioTrack, Book, BookPage, Category, Chapter, Magazine, MagazineIssue


def _paginate_queryset(request, queryset, per_page):
    """Web pages ke liye safe page object banata hai."""
    paginator = Paginator(queryset, per_page)
    page_number = request.GET.get("page")
    return paginator.get_page(page_number)


def web_home(request):
    """Website home page: featured books, intro, contact aur footer dikhata hai."""
    latest_app_release = _latest_app_release()
    home_banners = (
        Banner.objects.filter(is_published=True, device__in=[Banner.DEVICE_ALL, Banner.DEVICE_DESKTOP])
        .exclude(desktop_image="")
        .order_by("order", "-id")
    )
    books = (
        Book.objects.filter(is_published=True)
        .filter(magazine_issue__isnull=True)
        .exclude(category__slug__in=["patrika", "magazine"])
        .select_related("category")
        .only("id", "title", "slug", "cover_image", "category__id", "category__name", "category__slug")
    )[:5]
    categories = Category.objects.exclude(slug__in=["patrika", "magazine"])
    return render(
        request,
        "library/web/home.html",
        {
            "books": books,
            "categories": categories,
            "home_banners": home_banners,
            "latest_app_release": latest_app_release,
        },
    )


def _latest_app_release():
    return (
        AppBuildRelease.objects.filter(
            platform=AppBuildRelease.PLATFORM_ANDROID,
            channel=AppBuildRelease.CHANNEL_TESTING,
            is_active=True,
            rollout_percent__gt=0,
        )
        .order_by("-version_code", "-created_at")
        .first()
    )


def _app_release_url(request, release):
    if release.artifact_file:
        return request.build_absolute_uri(release.artifact_file.url)
    return release.artifact_url or release.play_store_url


def web_app_download(request):
    """Website ka fixed latest APK download URL."""
    latest_app_release = _latest_app_release()
    if not latest_app_release:
        raise Http404("Latest app release not available.")
    if latest_app_release.artifact_file:
        version_name = str(latest_app_release.version_name or "latest").replace(" ", "-")
        download_filename = f"nikunj-ras-{version_name}-code-{latest_app_release.version_code}.apk"
        return FileResponse(
            latest_app_release.artifact_file.open("rb"),
            as_attachment=True,
            filename=download_filename,
        )
    download_url = _app_release_url(request, latest_app_release)
    if not download_url:
        raise Http404("Latest app download URL not available.")
    return redirect(download_url)


def web_book_list(request):
    """Uploaded/published books ko catalog UI me dikhata hai."""
    books_queryset = (
        Book.objects.filter(is_published=True)
        .filter(magazine_issue__isnull=True)
        .exclude(category__slug__in=["patrika", "magazine"])
        .select_related("category")
        .only("id", "title", "slug", "cover_image", "category__id", "category__name", "category__slug")
    )
    page_obj = _paginate_queryset(request, books_queryset, 12)
    categories = Category.objects.exclude(slug__in=["patrika", "magazine"])
    return render(
        request,
        "library/web/book_list.html",
        {
            "books": page_obj.object_list,
            "page_obj": page_obj,
            "paginator": page_obj.paginator,
            "total_count": page_obj.paginator.count,
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
    magazines = Magazine.objects.filter(is_published=True).prefetch_related("issues")
    return render(request, "library/web/patrika_list.html", {"magazines": magazines})


def _first_page_for_book(book):
    if not book:
        return None
    return (
        BookPage.objects.filter(chapter__book=book)
        .order_by("chapter__order", "chapter__id", "page_number", "id")
        .first()
    )


def web_patrika_issue_list(request, slug):
    """Selected patrika ke sabhi ank dikhata hai."""
    magazine = get_object_or_404(Magazine, slug=slug, is_published=True)
    issue_queryset = (
        MagazineIssue.objects.filter(magazine=magazine, is_published=True)
        .select_related("book")
        .order_by("order", "-year", "-issue_number", "title")
    )
    page_obj = _paginate_queryset(request, issue_queryset, 10)
    issue_cards = [
        {"issue": issue, "first_page": _first_page_for_book(issue.book)}
        for issue in page_obj.object_list
    ]
    active_issue = page_obj.object_list[0] if page_obj.object_list else None
    active_first_page = _first_page_for_book(active_issue.book) if active_issue else None
    return render(
        request,
        "library/web/patrika_issue_list.html",
        {
            "magazine": magazine,
            "issue_cards": issue_cards,
            "active_issue": active_issue,
            "active_first_page": active_first_page,
            "page_obj": page_obj,
            "paginator": page_obj.paginator,
            "total_count": page_obj.paginator.count,
        },
    )


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
    audio_queryset = AudioTrack.objects.filter(is_published=True).select_related("category")
    page_obj = _paginate_queryset(request, audio_queryset, 10)
    return render(
        request,
        "library/web/audio_list.html",
        {
            "audio_items": page_obj.object_list,
            "page_obj": page_obj,
            "paginator": page_obj.paginator,
            "total_count": page_obj.paginator.count,
        },
    )


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
    from ebook_reader.structured_views import published_edition
    content_edition = published_edition(book.pk)
    ebook_document = EbookDocument.objects.filter(book=book).first()
    new_reader_preview_url = None
    if ebook_document and user_can_preview_reader(request, ebook_document):
        new_reader_preview_url = reverse("ebook_reader:web_reader", args=[ebook_document.id])
    chapter_pages = BookPage.objects.only("id", "chapter_id", "title", "page_number").order_by("page_number", "id")
    chapters = Chapter.objects.filter(book=book).prefetch_related(Prefetch("pages", queryset=chapter_pages))
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
            "new_reader_preview_url": new_reader_preview_url,
            "content_reader_url": reverse("ebook_reader:content_reader", args=[book.pk]) if content_edition else None,
        },
    )


def web_chapter_start(request, chapter_id):
    """Chapter par click karne par us chapter ke first page par bhejta hai."""
    chapter = get_object_or_404(Chapter.objects.select_related("book"), id=chapter_id)
    from ebook_reader.structured_views import published_edition
    if published_edition(chapter.book_id):
        url = reverse("ebook_reader:content_reader", args=[chapter.book_id])
        return redirect(f"{url}?page={chapter.start_page or 1}")
    first_page = chapter.pages.order_by("page_number", "id").first()
    if first_page:
        return redirect("web_reader_page", page_id=first_page.id)
    return redirect("web_book_detail", slug=chapter.book.slug)


def _page_position_filter(page, direction):
    """Current page se pehle/baad wale pages ko DB level par filter karta hai."""
    chapter_order = page.chapter.order
    chapter_id = page.chapter_id
    page_number = page.page_number

    if direction == "previous":
        return (
            Q(chapter__order__lt=chapter_order)
            | Q(chapter__order=chapter_order, chapter_id__lt=chapter_id)
            | Q(chapter__order=chapter_order, chapter_id=chapter_id, page_number__lt=page_number)
            | Q(chapter__order=chapter_order, chapter_id=chapter_id, page_number=page_number, id__lt=page.id)
        )

    return (
        Q(chapter__order__gt=chapter_order)
        | Q(chapter__order=chapter_order, chapter_id__gt=chapter_id)
        | Q(chapter__order=chapter_order, chapter_id=chapter_id, page_number__gt=page_number)
        | Q(chapter__order=chapter_order, chapter_id=chapter_id, page_number=page_number, id__gt=page.id)
    )


def _ordered_pages_for_book(book):
    """Book ke pages ka common ordered queryset banata hai."""
    return BookPage.objects.filter(chapter__book=book).select_related("chapter").order_by(
        "chapter__order",
        "chapter__id",
        "page_number",
        "id",
    )


def _reader_context(page):
    """Reader ke liye current, previous aur next page data ready karta hai."""
    page = get_object_or_404(
        BookPage.objects.select_related("chapter", "chapter__book"),
        id=page.id,
    )
    book = page.chapter.book
    book_pages = _ordered_pages_for_book(book)
    previous_filter = _page_position_filter(page, "previous")
    next_filter = _page_position_filter(page, "next")
    previous_page = book_pages.filter(previous_filter).order_by(
        "-chapter__order",
        "-chapter__id",
        "-page_number",
        "-id",
    ).first()
    next_page = book_pages.filter(next_filter).first()
    current_index = book_pages.filter(previous_filter).count() + 1

    return {
        "book": book,
        "page": page,
        "previous_page": previous_page,
        "next_page": next_page,
        "current_index": current_index,
        "total_pages": book_pages.count(),
    }


def _reader_payload(request, context):
    """Reader page ko JSON format me bhejne ke liye lightweight payload banata hai."""
    current_page = context["page"]
    previous_page = context["previous_page"]
    next_page = context["next_page"]
    image_url = request.build_absolute_uri(current_page.page_image.url) if current_page.page_image else ""
    next_image_url = request.build_absolute_uri(next_page.page_image.url) if next_page and next_page.page_image else ""
    previous_image_url = (
        request.build_absolute_uri(previous_page.page_image.url) if previous_page and previous_page.page_image else ""
    )
    return {
        "id": current_page.id,
        "title": current_page.title or current_page.chapter.title,
        "content": current_page.content,
        "image_url": image_url,
        "next_image_url": next_image_url,
        "previous_image_url": previous_image_url,
        "reader_url": request.build_absolute_uri(f"/web/reader/{current_page.id}/"),
        "previous_id": previous_page.id if previous_page else None,
        "next_id": next_page.id if next_page else None,
        "current_index": context["current_index"],
        "total_pages": context["total_pages"],
    }


def web_reader_page(request, page_id):
    """Reader page: current PDF page dikhata hai."""
    page = get_object_or_404(BookPage, id=page_id)
    context = _reader_context(page)
    context["reader_payload"] = _reader_payload(request, context)
    return render(
        request,
        "library/web/reader.html",
        context,
    )


def web_reader_page_data(request, page_id):
    """Next/previous click par JavaScript ko fast reader data deta hai."""
    page = get_object_or_404(BookPage, id=page_id)
    context = _reader_context(page)
    response = JsonResponse(_reader_payload(request, context))
    response["Cache-Control"] = "public, max-age=300"
    return response


def _legal_context(title, sections):
    return {
        "title": title,
        "support_email": "support@nikunjras.com",
        "updated_on": "August 26, 2026",
        "sections": [{"heading": heading, "body": body} for heading, body in sections],
    }


def web_privacy_policy(request):
    """Google Play listing ke liye public, non-PDF Privacy Policy page."""
    return render(
        request,
        "library/web/legal_page.html",
        _legal_context(
            "Privacy Policy",
            [
                ("Developer and contact", "Nikunj Ras is a spiritual ebook, audio, video and devotional content app. Privacy questions can be sent to support@nikunjras.com."),
                ("Data we collect", "The app may collect a generated device ID, name, mobile number, email address, contact messages, profile language, ratings, reviews, reading activity and app usage needed to provide library, support, feedback, caching and account features."),
                ("How data is used", "Data is used to show content, save profile details, answer support requests, store ratings, improve the service, remember reading progress and provide offline cache."),
                ("Sharing", "We do not sell personal data. Data may be processed by hosting, backend, storage and content delivery providers only for operating the app and website."),
                ("Security", "The app uses HTTPS for backend communication and stores cached content in app-private storage."),
                ("Retention and deletion", "Support messages, profile data, ratings and device identifiers are kept only as long as needed for app operation, support and legal requirements. Users can request deletion at support@nikunjras.com."),
                ("Children", "The app is intended for a general devotional audience and is not designed to knowingly collect personal data from children."),
            ],
        ),
    )


def web_terms_conditions(request):
    """Public Terms and Conditions page."""
    return render(
        request,
        "library/web/legal_page.html",
        _legal_context(
            "Terms & Conditions",
            [
                ("Use of the app", "Use this app for lawful personal reading, listening and devotional learning. Do not misuse, copy, scrape, attack, overload or interfere with the app or backend services."),
                ("Content", "Books, audio, video, quotes and related content are provided for spiritual and educational use. Availability can change based on rights, technical needs or service updates."),
                ("User submissions", "When you submit contact messages, ratings or profile details, you confirm that the information is accurate and does not violate anyone's rights."),
                ("No harmful use", "You may not use the app to upload illegal content, harass others, attempt unauthorized access or violate applicable laws."),
                ("Changes", "Features and terms may be updated. Continued use after updates means you accept the updated terms."),
            ],
        ),
    )


def web_data_safety(request):
    """Public data safety page for app users and store review links."""
    return render(
        request,
        "library/web/legal_page.html",
        _legal_context(
            "Data Safety",
            [
                ("Collected data", "The app may collect profile details, contact messages, device identifiers, ratings, reviews, reading activity and app usage needed for account, library, support and update features."),
                ("Purpose", "Data is used to run the library service, provide support, save user preferences, improve reliability and deliver app updates."),
                ("Sharing", "We do not sell personal data. Data may be processed by trusted hosting, storage, analytics or delivery providers only for operating Nikunj Ras."),
                ("Security and deletion", "The app uses HTTPS and app-private storage for cached content. Users can request account or data deletion from the Account/Data Deletion page or by emailing support@nikunjras.com."),
            ],
        ),
    )


def web_support(request):
    """Public support page for store listing and app users."""
    return render(
        request,
        "library/web/legal_page.html",
        _legal_context(
            "Support",
            [
                ("Contact", "For support, feedback, content questions or privacy requests, email support@nikunjras.com."),
                ("App help", "Please include your device model, app version, affected book/audio/video name and screenshots if possible."),
                ("Response time", "Support requests are normally reviewed within 7 business days."),
            ],
        ),
    )


def web_account_deletion(request):
    """Public account/data deletion instruction page."""
    return render(
        request,
        "library/web/legal_page.html",
        _legal_context(
            "Account & Data Deletion",
            [
                ("How to request deletion", "Send a deletion request to support@nikunjras.com with your name, mobile number or email used in the app. If available, include your device ID from the app profile."),
                ("What is deleted", "We will delete or anonymize profile details, contact messages, ratings, reviews and reading progress associated with the verified request, unless retention is legally required."),
                ("Timeline", "Deletion requests are normally processed within 30 days after verification."),
            ],
        ),
    )
