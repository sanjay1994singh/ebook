from django.http import HttpResponseRedirect
from django.urls import reverse
from rest_framework import generics, permissions, response, views
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenRefreshView

from .serializers import LoginSerializer, RegisterSerializer, UserSerializer


class RegisterView(generics.CreateAPIView):
    serializer_class = RegisterSerializer


class LoginView(views.APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        # Mobile app yahan username/password bhejega aur token receive karega.
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return response.Response(serializer.validated_data)


class MeView(generics.RetrieveAPIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = UserSerializer

    def get_object(self):
        return self.request.user


class RefreshTokenView(TokenRefreshView):
    pass


class GoogleLoginStartView(views.APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        # Browser/mobile ko Google OAuth start URL par bhejta hai.
        next_url = request.GET.get("next", "/api/auth/google/success/")
        login_url = f"{reverse('social:begin', kwargs={'backend': 'google-oauth2'})}?next={next_url}"
        return HttpResponseRedirect(login_url)


class GoogleAuthSuccessView(views.APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        # Google login ke baad current user ke JWT tokens return karta hai.
        refresh = RefreshToken.for_user(request.user)
        data = {
            "user": UserSerializer(request.user).data,
            "access": str(refresh.access_token),
            "refresh": str(refresh),
        }
        if "application/json" in request.headers.get("Accept", ""):
            return response.Response(data)

        return response.Response(data)


class GoogleAuthErrorView(views.APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        return response.Response(
            {
                "detail": "Google login failed. Please check Google client id, secret, redirect URI and allowed domain.",
                "redirect_uri": "https://nikunjras.com/auth/complete/google-oauth2/",
            },
            status=400,
        )
