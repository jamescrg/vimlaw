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
            "work_status",
            "practice_area",
            "firm",
            "client_reference_id",
        )

        STATUSES = (
            ("Open", "Open"),
            ("Complete", "Complete"),
            ("Closed", "Closed"),
        )

        FIRMS = (("Campbell & Brannon", "Campbell & Brannon"),)

        PRACTICE_AREAS = (
            ("CB", "CB"),
            ("General", "General"),
            ("Old Republic", "Old Republic"),
        )

        widgets = {
            "name": forms.TextInput(
                attrs={"autofocus": "autofocus", "onfocus": "moveFocusToEnd(this)"}
            ),
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
