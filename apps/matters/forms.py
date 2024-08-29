from django import forms

from .models import Matter


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
            "clio_matter_id",
            "client_reference_id",
        )

        STATUSES = (
            ("Open", "Open"),
            ("Closed", "Closed"),
        )

        FIRMS = (("Campbell & Brannon", "Campbell & Brannon"),)

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
            "clio_matter_id": "Clio Matter",
            "client_reference_id": "Client Reference",
            "practice_area": "Practice Area",
        }
