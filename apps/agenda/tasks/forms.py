from datetime import date

from django import forms
from django.core.exceptions import ValidationError

from apps.agenda.tasks.models import Task


class TaskForm(forms.ModelForm):
    class Meta:
        model = Task

        fields = (
            "matter",
            "description",
            "priority",
            "user",
            "date_due",
            "term",
        )

        STATUSES = (
            ("Pending", "Pending"),
            ("Complete", "Complete"),
        )

        labels = {
            "description": "Task",
        }

        priorities = []
        for i in range(1, 10):
            priorities.append((i, i))
        PRIORITIES = tuple(priorities)

        widgets = {
            "description": forms.TextInput(
                attrs={
                    "autofocus": "autofocus",
                    "onfocus": "moveFocusToEnd(this)",
                }
            ),
            "status": forms.Select(choices=STATUSES),
            "date_due": forms.DateInput(attrs={"type": "date"}),
            "priority": forms.Select(choices=PRIORITIES),
            "term": forms.Select(),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["priority"].initial = 3
        self.fields["date_due"].initial = date.today().strftime("%Y-%m-%d")

    def clean_description(self):
        description = self.cleaned_data["description"]
        if len(description) < 2:
            raise ValidationError("Description must be greater than 2 characters.")
        if len(description) > 200:
            raise ValidationError("Description is limited to 200 character.")
        return description

    def clean_matter(self):
        matter = self.cleaned_data["matter"]
        # if not matter:
        #     raise ValidationError("This field is required")

        return matter
