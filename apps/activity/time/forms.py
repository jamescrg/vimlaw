from django import forms

from apps.accounts.access import filter_matters_for_user
from config.settings import CustomFormRendererCompact

from .models import AbbreviationCode, TimeEntry


class TimeEntryForm(forms.ModelForm):
    class Meta:
        model = TimeEntry

        fields = (
            "matter",
            "date",
            "actions",
            "hours",
            "rate",
            "comp",
            "entered",
        )

        COMP_CHOICES = (
            (False, "No"),
            (True, "Yes"),
        )

        ENTERED_CHOICES = (
            (False, "No"),
            (True, "Yes"),
        )

        widgets = {
            "matter": forms.Select(attrs={"onchange": "updateRate()", "tabindex": "1"}),
            "date": forms.DateInput(attrs={"type": "date", "tabindex": "3"}),
            "actions": forms.Textarea(
                attrs={
                    "onfocus": "moveFocusToEnd(this)",
                    "rows": "3",
                    "class": "span2",
                    "tabindex": "2",
                }
            ),
            "comp": forms.Select(choices=COMP_CHOICES),
            "entered": forms.Select(choices=ENTERED_CHOICES),
        }

        labels = {"rate": "Rate"}

    def __init__(self, *args, **kwargs):
        user = kwargs.pop("user", None)
        super().__init__(*args, **kwargs)
        self.renderer = CustomFormRendererCompact()
        if user:
            self.fields["matter"].queryset = filter_matters_for_user(
                self.fields["matter"].queryset, user
            )


class AbbreviationCodeForm(forms.ModelForm):
    class Meta:
        model = AbbreviationCode

        fields = ("code", "expansion")

        widgets = {
            "code": forms.TextInput(
                attrs={
                    "placeholder": "e.g., 'conf ' or ' MSJ'",
                }
            ),
            "expansion": forms.TextInput(
                attrs={
                    "placeholder": "e.g., 'conference ' or ' Motion for Summary Judgment'"
                }
            ),
        }

        labels = {"code": "Abbreviation Code", "expansion": "Expansion Text"}

        help_texts = {
            "code": "Include spaces if needed (case-sensitive). Examples: 'conf ', ' MSJ', 'Attn '",
            "expansion": "The full text that will replace the abbreviation.",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.renderer = CustomFormRendererCompact()

    def clean_code(self):
        code = self.cleaned_data.get("code")
        if not code:
            raise forms.ValidationError("Abbreviation code is required.")

        # Check for duplicate codes (excluding current instance when editing)
        queryset = AbbreviationCode.objects.filter(code=code)
        if self.instance.pk:
            queryset = queryset.exclude(pk=self.instance.pk)

        if queryset.exists():
            raise forms.ValidationError(
                f"The abbreviation code '{code}' already exists."
            )

        return code
