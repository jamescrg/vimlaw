from django.urls import include, path

app_name = "accounts"

# fmt: off
urlpatterns = [
    # path("signup/", SignUpView.as_view(), name="signup"),
    path("", include("django.contrib.auth.urls")),
]
# fmt: on
