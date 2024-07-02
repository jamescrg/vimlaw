from django.urls import include, path

from .views import SignUpView

urlpatterns = [
    path("signup/", SignUpView.as_view(), name="signup"),
    path("accounts/", include("django.contrib.auth.urls")),
]
