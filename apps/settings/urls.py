from django.urls import path

import apps.settings.appearance.views as appearance_urls
import apps.settings.claude.views as claude_urls
import apps.settings.contacts.views as contact_urls
import apps.settings.firm.views as firm_urls
import apps.settings.intake_emails.views as intake_email_urls
import apps.settings.integrations.views as integration_urls
import apps.settings.matters.views as matter_urls
import apps.settings.notifications.views as notification_urls
import apps.settings.permissions.views as permission_urls
import apps.settings.profile.views as profile_urls
import apps.settings.session.views as session_urls
import apps.settings.tasks.views as tasks_urls
import apps.settings.users.views as user_urls

app_name = "settings"

urlpatterns = [
    path(
        "settings/intake-emails/",
        intake_email_urls.intake_emails_index,
        name="intake-emails-index",
    ),
    path(
        "settings/intake-emails/list/",
        intake_email_urls.email_template_list,
        name="intake-email-list",
    ),
    path(
        "settings/intake-emails/add/",
        intake_email_urls.add_email_template,
        name="add-intake-email",
    ),
    path(
        "settings/intake-emails/edit/<int:template_id>/",
        intake_email_urls.edit_email_template,
        name="edit-intake-email",
    ),
    path(
        "settings/intake-emails/delete/<int:template_id>/",
        intake_email_urls.delete_email_template,
        name="delete-intake-email",
    ),
    # Session
    path("settings/", session_urls.index, name="settings"),
    path(
        "settings/keyboard-shortcuts/",
        session_urls.keyboard_shortcuts,
        name="keyboard-shortcuts",
    ),
    # Claude Desktop (notes MCP connector)
    path("settings/claude/", claude_urls.claude_index, name="claude-index"),
    path("settings/claude/rotate/", claude_urls.claude_rotate, name="claude-rotate"),
    path("settings/claude/revoke/", claude_urls.claude_revoke, name="claude-revoke"),
    path("settings/claude/script/", claude_urls.claude_script, name="claude-script"),
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
    # Firm
    path("settings/firm/", firm_urls.firm_index, name="firm-index"),
    path("settings/tasks/", tasks_urls.tasks_index, name="tasks-index"),
    path(
        "settings/firm/logo/upload/",
        firm_urls.firm_upload_logo,
        name="firm-upload-logo",
    ),
    path(
        "settings/firm/logo/remove/",
        firm_urls.firm_remove_logo,
        name="firm-remove-logo",
    ),
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
    path(
        "settings/permissions/",
        permission_urls.permissions_index,
        name="permissions-index",
    ),
    path(
        "settings/permissions/table/",
        permission_urls.permissions_table,
        name="permissions-table",
    ),
    path(
        "settings/users/toggle-perm/<int:user_id>/<str:perm>/",
        user_urls.toggle_permission,
        name="toggle-perm",
    ),
    path(
        "settings/users/matter-assignments/<int:user_id>/",
        user_urls.matter_assignments,
        name="matter-assignments",
    ),
    path(
        "settings/users/toggle-matter/<int:user_id>/<int:matter_id>/",
        user_urls.toggle_matter_assignment,
        name="toggle-matter-assignment",
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
    # Appearance
    path(
        "settings/appearance/",
        appearance_urls.appearance_index,
        name="appearance-index",
    ),
    path(
        "settings/appearance/nav-layout/",
        appearance_urls.set_nav_layout,
        name="nav-layout",
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
    path(
        "settings/contacts/relationship-types/",
        contact_urls.relationship_type_list,
        name="relationship-type-list",
    ),
    path(
        "settings/contacts/relationship-types/filter/<str:filter_value>/",
        contact_urls.relationship_type_filter_view,
        name="relationship-type-filter",
    ),
    path(
        "settings/contacts/relationship-types/add/",
        contact_urls.add_relationship_type,
        name="add-relationship-type",
    ),
    path(
        "settings/contacts/relationship-types/edit/<int:type_id>/",
        contact_urls.edit_relationship_type,
        name="edit-relationship-type",
    ),
    path(
        "settings/contacts/relationship-types/delete/<int:type_id>/",
        contact_urls.delete_relationship_type,
        name="delete-relationship-type",
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
