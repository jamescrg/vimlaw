from django import forms

from apps.accounts.models import CustomUser


class UserForm(forms.ModelForm):
    class Meta:
        model = CustomUser
        fields = [
            "username",
            "first_name",
            "last_name",
            "email",
            "role",
            "is_active",
            "initials",
        ]
