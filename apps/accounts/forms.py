from django import forms
from django.contrib.auth.forms import UserChangeForm, UserCreationForm

from .models import CustomUser


class VerificationCodeForm(forms.Form):
    code = forms.CharField(
        max_length=6,
        min_length=6,
        label="",
        widget=forms.TextInput(attrs={"autocomplete": "off", "autofocus": True}),
    )


class CustomUserCreationForm(UserCreationForm):
    class Meta(UserCreationForm):
        model = CustomUser
        fields = ("username", "email")

    # Remove default help text
    def __init__(self, *args, **kwargs):
        super(CustomUserCreationForm, self).__init__(*args, **kwargs)

        self.fields["password1"].help_text = None


class CustomUserChangeForm(UserChangeForm):
    class Meta:
        model = CustomUser
        fields = ("username", "email")
