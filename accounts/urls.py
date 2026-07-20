from django.urls import path

from .views import GoogleAuthErrorView, GoogleAuthSuccessView, GoogleLoginStartView, LoginView, MeView, RefreshTokenView, RegisterView

urlpatterns = [
    path("register/", RegisterView.as_view(), name="register"),
    path("login/", LoginView.as_view(), name="login"),
    path("google/start/", GoogleLoginStartView.as_view(), name="google_login_start"),
    path("google/success/", GoogleAuthSuccessView.as_view(), name="google_auth_success"),
    path("google/error/", GoogleAuthErrorView.as_view(), name="google_auth_error"),
    path("me/", MeView.as_view(), name="me"),
    path("token/refresh/", RefreshTokenView.as_view(), name="token_refresh"),
]
