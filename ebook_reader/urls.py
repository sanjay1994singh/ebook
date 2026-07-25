from django.urls import path

from . import views


app_name = "ebook_reader"

urlpatterns = [
    path("health/", views.health_check, name="health"),
    path("<int:ebook_id>/read/", views.web_reader, name="web_reader"),
]
