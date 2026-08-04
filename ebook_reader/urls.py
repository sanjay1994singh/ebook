from django.urls import path

from . import views


app_name = "ebook_reader"

urlpatterns = [
    path("", views.book_list, name="book_list"),
    path("health/", views.health_check, name="health"),
    path("highlights/", views.save_highlight_api, name="save_highlight"),
    path("books/<int:book_id>/", views.reader_view, name="reader"),
    path("<int:ebook_id>/read/", views.web_reader, name="web_reader"),
]
