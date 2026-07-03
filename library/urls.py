from django.urls import path

from .views import (
    BookDetailView,
    BookListView,
    BookPageDetailView,
    CategoryListView,
    ChapterPageListView,
    ChapterListView,
    FavoriteDeleteView,
    FavoriteListCreateView,
    ReadingProgressListCreateView,
)

urlpatterns = [
    path("categories/", CategoryListView.as_view(), name="category_list"),
    path("", BookListView.as_view(), name="book_list"),
    path("favorites/", FavoriteListCreateView.as_view(), name="favorite_list_create"),
    path("favorites/<int:book_id>/", FavoriteDeleteView.as_view(), name="favorite_delete"),
    path("progress/", ReadingProgressListCreateView.as_view(), name="progress_list_create"),
    path("pages/<int:pk>/", BookPageDetailView.as_view(), name="book_page_detail"),
    path("chapters/<int:chapter_id>/pages/", ChapterPageListView.as_view(), name="chapter_page_list"),
    path("<slug:slug>/", BookDetailView.as_view(), name="book_detail"),
    path("<slug:slug>/chapters/", ChapterListView.as_view(), name="chapter_list"),
]
