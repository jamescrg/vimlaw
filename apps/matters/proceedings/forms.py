from django import forms

from apps.matters.proceedings.models import Proceeding


class ProceedingForm(forms.ModelForm):
    class Meta:
        model = Proceeding
        fields = (
            "date_filed",
            "forum",
            "case_number",
            "status",
            "primary",
        )

        STATUSES = (
            ("Ongoing", "Ongoing"),
            ("Concluded", "Concluded"),
            ("Stayed", "Stayed"),
            ("Dismissed", "Dismissed"),
        )

        widgets = {
            "forum": forms.TextInput(
                attrs={"autofocus": "autofocus", "onfocus": "moveFocusToEnd(this)"}
            ),
            "status": forms.Select(choices=STATUSES),
            "date_filed": forms.DateInput(attrs={"type": "date"}),
        }

        labels = {
            "date_filed": "Date Filed",
            "case_number": "Case Number",
        }
