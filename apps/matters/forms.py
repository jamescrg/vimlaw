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
            "description",
            "work_status",
            "practice_area",
            "firm",
        )

        STATUSES = (
            ("Open", "Open"),
            ("Complete", "Complete"),
            ("Closed", "Closed"),
        )

        FIRMS = (
            ("Craig Legal", "Craig Legal"),
            ("Campbell & Brannon", "Campbell & Brannon"),
        )

        PRACTICE_AREAS = (
            ("General", "General"),
            ("Interpleader", "Interpleader"),
            ("Construction", "Construction"),
            ("Boundary", "Boundary"),
            ("LLT-L", "LLT-L"),
            ("LLT-T", "LLT-T"),
            ("QT", "QT"),
            ("HOA", "HOA"),
            ("Fraud", "Fraud"),
        )

        widgets = {
            "name": forms.TextInput(
                attrs={
                    "autofocus": "autofocus",
                    "onfocus": "moveFocusToEnd(this)",
                    "class": "span2",
                }
            ),
            "description": forms.TextInput(
                attrs={
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

        # Set Craig Legal as default for new matters
        if not self.instance.pk:
            self.fields["firm"].initial = "Craig Legal"
