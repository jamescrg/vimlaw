from django import forms

from .models import Fact, Matter, Proceeding, Rate, SettlementEntry


class MatterForm(forms.ModelForm):
    class Meta:
        model = Matter

        fields = (
            "client",
            "status",
            "name",
            "date_start",
            "description",
            "practice_area",
            "firm",
            "firm_file_no",
            "ref_no",
        )

        STATUSES = (
            ("Open", "Open"),
            ("Closed", "Closed"),
        )

        FIRMS = (
            ("Campbell & Brannon", "Campbell & Brannon"),
            ("Craig Law", "Craig Law"),
            ("Mitchell Law", "Mitchell Law"),
            ("Mays & Kerr", "Mays & Kerr"),
        )

        PRACTICE_AREAS = (
            ("CB", "CB"),
            ("General", "General"),
            ("Old Republic", "Old Republic"),
        )

        widgets = {
            "name": forms.TextInput(attrs={"autofocus": "autofocus"}),
            "status": forms.Select(choices=STATUSES),
            "firm": forms.Select(choices=FIRMS),
            "practice_area": forms.Select(choices=PRACTICE_AREAS),
            "date_start": forms.DateInput(attrs={"type": "date"}),
        }

        labels = {
            "date_start": "Open Date",
            "firm_file_no": "File Number",
            "ref_no": "Client Reference",
            "practice_area": "Practice Area",
        }


class ProceedingForm(forms.ModelForm):
    class Meta:
        model = Proceeding

        fields = (
            "date_filed",
            "forum",
            "case_number",
            "status",
        )

        STATUSES = (
            ("Ongoing", "Ongoing"),
            ("Concluded", "Concluded"),
            ("Stayed", "Stayed"),
            ("Dismissed", "Dismissed"),
        )

        widgets = {
            "forum": forms.TextInput(attrs={"autofocus": "autofocus"}),
            "status": forms.Select(choices=STATUSES),
            "date_filed": forms.DateInput(attrs={"type": "date"}),
        }

        labels = {
            "date_filed": "Date Filed",
            "case_number": "Case Number",
        }


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


class FactForm(forms.ModelForm):
    class Meta:
        model = Fact

        fields = (
            "date",
            "description",
            "citation",
            "emphasis",
        )

        EMPHASIS_OPTIONS = (
            ("No", "No"),
            ("Yes", "Yes"),
        )

        widgets = {
            "date": forms.DateInput(attrs={"type": "date"}),
            "emphasis": forms.Select(choices=EMPHASIS_OPTIONS),
        }


class RateForm(forms.ModelForm):
    class Meta:
        model = Rate

        fields = (
            "user",
            "matter_rate",
        )
