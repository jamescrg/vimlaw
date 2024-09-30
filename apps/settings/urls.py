from django.urls import path

# Import all from company.views as company_urls
import apps.settings.company.views as company_urls
import apps.settings.profile.views as profile_urls
import apps.settings.session.views as session_urls
import apps.settings.users.views as user_urls

app_name = "settings"

urlpatterns = [
    path("settings/", session_urls.index, name="settings"),
    path(
        "settings/google/login/<str:app>",
        session_urls.google_login,
        name="google-login",
    ),
    path("settings/google/store", session_urls.google_store, name="google-store"),
    path(
        "settings/google/logout/<str:app>",
        session_urls.google_logout,
        name="google-logout",
    ),
    # Company
    path("settings/company/", company_urls.company_index, name="company-index"),
    # Users
    path("settings/users/", user_urls.users_index, name="users-index"),
    path("settings/users/list/", user_urls.user_list, name="user-list"),
    path("settings/users/filter/", user_urls.user_filter, name="user-filter"),
    path("settings/users/sort/<str:order>/", user_urls.user_sort, name="user-sort"),
    path(
        "settings/users/change-role/<int:user_id>/<str:role>/",
        user_urls.change_role,
        name="change-role",
    ),
    # Profile
    path("settings/profile/", profile_urls.profile_index, name="profile-index"),
]
