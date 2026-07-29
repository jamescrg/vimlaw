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


class UserPermissionsForm(forms.ModelForm):
    class Meta:
        model = CustomUser
        fields = [
            "perm_all_matters",
            "perm_financial",
            "perm_intakes",
            "perm_reports",
            "perm_research",
        ]

        YESNO_CHOICES = (
            (True, "Yes"),
            (False, "No"),
        )

        widgets = {
            "perm_all_matters": forms.Select(choices=YESNO_CHOICES),
            "perm_financial": forms.Select(choices=YESNO_CHOICES),
            "perm_intakes": forms.Select(choices=YESNO_CHOICES),
            "perm_reports": forms.Select(choices=YESNO_CHOICES),
            "perm_research": forms.Select(choices=YESNO_CHOICES),
        }

        labels = {
            "perm_all_matters": "All Matters",
            "perm_financial": "Financial",
            "perm_intakes": "Intakes",
            "perm_reports": "Reports",
            "perm_research": "Research",
        }

        help_texts = {
            "perm_all_matters": ("No restricts this user to their assigned matters."),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.renderer = CustomFormRendererCompact()
