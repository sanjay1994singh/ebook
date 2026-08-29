from django.urls import path

from .views import AppLatestBuildView

urlpatterns = [
    path("latest/", AppLatestBuildView.as_view(), name="app_update_latest"),
]
