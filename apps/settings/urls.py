from django.urls import path

from apps.settings.views import index, google_logout, google_login, google_store

urlpatterns = [
    path("settings/", index, name="settings"),
    path(
        "settings/google/login/<str:app>",
        google_login,
        name="settings-google-login",
    ),
    path("settings/google/store", google_store, name="settings-google-store"),
    path(
        "settings/google/logout/<str:app>",
        google_logout,
        name="settings-google-logout",
    ),
]
