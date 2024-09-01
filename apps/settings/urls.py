from django.urls import path

from apps.settings.views import google_login, google_logout, google_store, index

app_name = "settings"

# fmt: off
urlpatterns = [
    path("settings/", index, name="settings"),
    path("settings/google/login/<str:app>", google_login, name="google-login"),
    path("settings/google/store", google_store, name="google-store"),
    path("settings/google/logout/<str:app>", google_logout, name="google-logout"),
]
# fmt: on
