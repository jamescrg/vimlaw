from django.urls import path

# Import all from company.views as company_urls
import apps.settings.company.views as company_urls
import apps.settings.contacts.views as contact_urls
import apps.settings.integrations.views as integration_urls
import apps.settings.matters.views as matter_urls
import apps.settings.notifications.views as notification_urls
import apps.settings.profile.views as profile_urls
import apps.settings.session.views as session_urls
import apps.settings.users.views as user_urls

app_name = "settings"

urlpatterns = [
    # Session
    path("settings/", session_urls.index, name="settings"),
    # Integrations
    path("settings/integrations/", integration_urls.index, name="integrations-index"),
    path(
        "settings/google/login/<str:app>",
        integration_urls.google_login,
        name="google-login",
    ),
    path("settings/google/store", integration_urls.google_store, name="google-store"),
    path(
        "settings/google/logout/<str:app>",
        integration_urls.google_logout,
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
    path(
        "settings/users/switch-status/<int:user_id>/",
        user_urls.switch_status,
        name="switch-status",
    ),
    path(
        "settings/users/edit/<int:user_id>/",
        user_urls.edit_user,
        name="edit-user",
    ),
    path(
        "settings/users/add/",
        user_urls.add_user,
        name="add-user",
    ),
    # Notifications
    path(
        "settings/notifications/",
        notification_urls.notifications_index,
        name="notifications-index",
    ),
    path(
        "settings/notifications/toggle-digest/",
        notification_urls.toggle_digest,
        name="toggle-digest",
    ),
    path(
        "settings/notifications/toggle-weekends/",
        notification_urls.toggle_weekends,
        name="toggle-weekends",
    ),
    path(
        "settings/notifications/send-test/",
        notification_urls.send_test_digest,
        name="send-test-digest",
    ),
    # Profile
    path("settings/profile/", profile_urls.profile_index, name="profile-index"),
    path(
        "settings/profile/personal/",
        profile_urls.personal_profile,
        name="personal-profile",
    ),
    path(
        "settings/profile/personal/<str:form_type>/",
        profile_urls.personal_profile,
        name="personal-profile",
    ),
    # Contacts (Groups and Roles)
    path("settings/contacts/", contact_urls.contacts_index, name="contacts-index"),
    path("settings/contacts/roles/", contact_urls.role_list, name="role-list"),
    path(
        "settings/contacts/roles/filter/<str:status>/",
        contact_urls.role_filter,
        name="role-filter",
    ),
    path("settings/contacts/roles/add/", contact_urls.add_role, name="add-role"),
    path(
        "settings/contacts/roles/edit/<int:role_id>/",
        contact_urls.edit_role,
        name="edit-role",
    ),
    path(
        "settings/contacts/roles/delete/<int:role_id>/",
        contact_urls.delete_role,
        name="delete-role",
    ),
    path("settings/contacts/groups/", contact_urls.group_list, name="group-list"),
    path(
        "settings/contacts/groups/filter/<str:status>/",
        contact_urls.group_filter,
        name="group-filter",
    ),
    path("settings/contacts/groups/add/", contact_urls.add_group, name="add-group"),
    path(
        "settings/contacts/groups/edit/<int:group_id>/",
        contact_urls.edit_group,
        name="edit-group",
    ),
    path(
        "settings/contacts/groups/delete/<int:group_id>/",
        contact_urls.delete_group,
        name="delete-group",
    ),
    path(
        "settings/contacts/groups/update-order/",
        contact_urls.update_group_order,
        name="update-group-order",
    ),
    # Matters (Practice Areas)
    path("settings/matters/", matter_urls.matters_index, name="matters-index"),
    path(
        "settings/matters/practice-areas/",
        matter_urls.practice_area_list,
        name="practice-area-list",
    ),
    path(
        "settings/matters/practice-areas/filter/<str:status>/",
        matter_urls.practice_area_filter,
        name="practice-area-filter",
    ),
    path(
        "settings/matters/practice-areas/add/",
        matter_urls.add_practice_area,
        name="add-practice-area",
    ),
    path(
        "settings/matters/practice-areas/edit/<int:practice_area_id>/",
        matter_urls.edit_practice_area,
        name="edit-practice-area",
    ),
    path(
        "settings/matters/practice-areas/delete/<int:practice_area_id>/",
        matter_urls.delete_practice_area,
        name="delete-practice-area",
    ),
]
