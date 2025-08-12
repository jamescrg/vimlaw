from django import forms

from config.settings import CustomFormRendererCompact

from .models import Matter


class MatterForm(forms.ModelForm):
    class Meta:
        model = Matter

        fields = (
            "status",
            "date_start",
            "client",
            "name",
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
                attrs={
                    "autofocus": "autofocus",
                    "onfocus": "moveFocusToEnd(this)",
                    "class": "span2",
                }
            ),
            "work_status": forms.TextInput(
                attrs={
                    "class": "span2",
                }
            ),
            "status": forms.Select(
                choices=STATUSES,
            ),
            "client_reference_id": forms.TextInput(
                attrs={
                    "class": "span2",
                }
            ),
            "client": forms.Select(
                attrs={
                    "class": "span2",
                }
            ),
            "firm": forms.Select(
                choices=FIRMS,
            ),
            "practice_area": forms.Select(
                choices=PRACTICE_AREAS,
            ),
            "date_start": forms.DateInput(attrs={"type": "date"}),
        }

        labels = {
            "date_start": "Open Date",
            "clio_matter_id": "Clio Matter",
            "client_reference_id": "Client Reference",
            "practice_area": "Practice Area",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.renderer = CustomFormRendererCompact()
