from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from simple_history.admin import SimpleHistoryAdmin

from .forms import CustomUserChangeForm, CustomUserCreationForm
from .models import CustomUser


class CustomUserAdmin(SimpleHistoryAdmin, UserAdmin):
    add_form = CustomUserCreationForm
    form = CustomUserChangeForm
    model = CustomUser
    list_display = [
        "email",
        "username",
        "is_staff",
        "user_rate",
        "initials",
        "role",
    ]

    fieldsets = UserAdmin.fieldsets + (
        (None, {"fields": ("user_rate", "initials", "role")}),
    )


admin.site.register(CustomUser, CustomUserAdmin)
