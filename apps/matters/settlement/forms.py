from django import forms

from config.settings import CustomFormRendererCompact

from .models import SettlementEntry


class SettlementEntryForm(forms.ModelForm):
    class Meta:
        model = SettlementEntry

        fields = (
            "date",
            "medium",
            "type",
            "amount",
            "notes",
        )

        MEDIA = (
            ("Email", "Email"),
            ("In Person", "In Person"),
            ("Letter", "Letter"),
            ("Phone", "Phone"),
        )

        ENTRY_TYPES = (
            ("Authorization", "Authorization"),
            ("Demand", "Demand"),
            ("Offer", "Offer"),
        )

        widgets = {
            "date": forms.DateInput(attrs={"type": "date"}),
            "medium": forms.Select(choices=MEDIA),
            "type": forms.Select(choices=ENTRY_TYPES),
            "notes": forms.Textarea(
                attrs={
                    "autofocus": "autofocus",
                    "onfocus": "moveFocusToEnd(this)",
                    "class": "span2",
                    "rows": 3,
                }
            ),
        }

        labels = {
            "date_filed": "Date Filed",
            "case_number": "Case Number",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.renderer = CustomFormRendererCompact()
