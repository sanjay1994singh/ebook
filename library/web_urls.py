from django.urls import path

from . import web_views

urlpatterns = [
    path("", web_views.web_home, name="web_home"),
    path("web/books/", web_views.web_book_list, name="web_book_list"),
    path("web/patrika/", web_views.web_patrika_list, name="web_patrika_list"),
    path("web/patrika/<slug:slug>/", web_views.web_patrika_issue_list, name="web_patrika_issue_list"),
    path("web/audio/", web_views.web_audio_list, name="web_audio_list"),
    path("web/amrit-vachan/", web_views.web_divine_quotes, name="web_divine_quotes"),
    path("web/books/<slug:slug>/", web_views.web_book_detail, name="web_book_detail"),
    path("web/chapters/<int:chapter_id>/start/", web_views.web_chapter_start, name="web_chapter_start"),
    path("web/reader/<int:page_id>/", web_views.web_reader_page, name="web_reader_page"),
    path("web/reader/<int:page_id>/data/", web_views.web_reader_page_data, name="web_reader_page_data"),
]
