from django.urls import path

from .views import BannerListView


urlpatterns = [
    path("", BannerListView.as_view(), name="banner_list"),
]
