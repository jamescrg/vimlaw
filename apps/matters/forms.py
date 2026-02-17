from django import forms

from config.settings import CustomFormRendererCompact

from .models import Matter, PracticeArea


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
        )

        STATUSES = (
            ("Pending", "Pending"),
            ("Open", "Open"),
            ("Complete", "Complete"),
            ("Closed", "Closed"),
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

        # Filter practice areas to only show active ones
        self.fields["practice_area"].queryset = PracticeArea.objects.filter(
            is_active=True
        )
