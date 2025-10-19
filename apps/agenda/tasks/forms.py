from django import forms
from django.core.exceptions import ValidationError

from apps.agenda.tasks.models import Task
from config.settings import CustomFormRendererCompact


class TaskForm(forms.ModelForm):

    class Meta:
        model = Task

        fields = (
            "matter",
            "focus",
            "description",
            "user",
            "priority",
            "date_due",
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
                    "class": "span3",
                }
            ),
            "matter": forms.Select(
                attrs={
                    "class": "span2",
                }
            ),
            "focus": forms.Select(attrs={"class": "span1"}),
            "user": forms.Select(attrs={"class": ""}),
            "status": forms.Select(choices=STATUSES),
            "date_due": forms.DateInput(attrs={"type": "date", "class": ""}),
            "priority": forms.Select(choices=PRIORITIES),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.renderer = CustomFormRendererCompact()
        self.fields["priority"].initial = 3
        # Customize user field to display title case usernames
        self.fields["user"].label_from_instance = lambda obj: obj.username.title()

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
