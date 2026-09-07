from django.urls import path

from . import views
from . import structured_views as content


app_name = "ebook_reader"

urlpatterns = [
    path("content/books/<int:book_id>/", content.manifest, name="content_manifest"),
    path("content/books/<int:book_id>/read/", content.reader, name="content_reader"),
    path("content/editions/<int:edition_id>/pages/<int:page_number>/", content.page_data, name="content_page"),
    path("content/editions/<int:edition_id>/search/", content.search, name="content_search"),
    path("content/editions/<int:edition_id>/review/", content.review, name="content_review"),
    path("content/editions/<int:edition_id>/preview/", content.draft_preview, name="content_preview"),
    path("content/editions/<int:edition_id>/source/<int:page_number>/", content.source_page, name="content_source"),
    path("content/editions/<int:edition_id>/review/<int:page_number>/", content.save_review, name="content_review_save"),
    path("content/editions/<int:edition_id>/publish/", content.publish, name="content_publish"),
    path("", views.book_list, name="book_list"),
    path("health/", views.health_check, name="health"),
    path("highlights/", views.save_highlight_api, name="save_highlight"),
    path("books/<int:book_id>/", views.reader_view, name="reader"),
    path("<int:ebook_id>/read/", views.web_reader, name="web_reader"),
]
