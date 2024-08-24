from django import forms

from apps.matters.settlement.models import SettlementEntry


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
        }

        labels = {
            "date_filed": "Date Filed",
            "case_number": "Case Number",
        }
