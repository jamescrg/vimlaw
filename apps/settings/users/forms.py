from django import forms

from apps.accounts.models import CustomUser
from config.settings import CustomFormRendererCompact


class UserForm(forms.ModelForm):
    class Meta:
        model = CustomUser
        fields = [
            "username",
            "email",
            "first_name",
            "last_name",
            "role",
            "is_attorney",
            "title",
            "initials",
            "user_rate",
            "is_active",
        ]

        ATTORNEY_CHOICES = (
            (True, "Yes"),
            (False, "No"),
        )

        ACTIVE_CHOICES = (
            (True, "Active"),
            (False, "Inactive"),
        )

        widgets = {
            "is_attorney": forms.Select(choices=ATTORNEY_CHOICES),
            "is_active": forms.Select(choices=ACTIVE_CHOICES),
        }

        labels = {
            "is_attorney": "Attorney",
            "user_rate": "Hourly Rate",
            "is_active": "Status",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.renderer = CustomFormRendererCompact()


class CreateUserForm(forms.ModelForm):
    class Meta:
        model = CustomUser
        fields = [
            "username",
            "password",
            "first_name",
            "last_name",
            "email",
            "role",
        ]
        widgets = {
            "username": forms.TextInput(attrs={"class": ""}),
            "password": forms.PasswordInput(attrs={"class": ""}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.renderer = CustomFormRendererCompact()

    def save(self, commit=True):
        user = super().save(commit=False)
        user.set_password(self.cleaned_data["password"])

        if commit:
            user.save()

        return user
