from django import forms
from django.core.exceptions import ValidationError

from apps.agenda.tasks.models import Task


class TaskForm(forms.ModelForm):

    class Meta:
        model = Task

        fields = (
            "description",
            "matter",
            "date_due",
            "status",
            "priority",
        )

        STATUSES = (
            ("Pending", "Pending"),
            ("Complete", "Complete"),
        )

        labels = {
            "description": "Task",
        }

        widgets = {
            "description": forms.TextInput(
                attrs={"autofocus": "autofocus", "required": "required"}
            ),
            "matter": forms.Select(attrs={"required": "required"}),
            "status": forms.Select(choices=STATUSES),
            "date_due": forms.DateInput(attrs={"type": "date"}),
        }

    def clean_description(self):
        description = self.cleaned_data["description"]
        if len(description) < 2:
            raise ValidationError("Description must be greater than 2 characters")
        if len(description) > 50:
            raise ValidationError("Description must be fewer than 50 characters")
        return description
