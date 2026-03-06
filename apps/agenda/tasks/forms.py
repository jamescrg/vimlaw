from django import forms
from django.core.exceptions import ValidationError

from apps.accounts.models import CustomUser
from apps.agenda.tasks.models import Task, TaskNote
from apps.matters.models import Matter
from config.settings import CustomFormRendererCompact


class TaskForm(forms.ModelForm):
    class Meta:
        model = Task

        fields = (
            "matter",
            "description",
            "user",
            "priority",
            "status",
            "date_due",
            "date_completed",
        )

        STATUSES = (
            ("Pending", "Pending"),
            ("Complete", "Complete"),
        )

        labels = {
            "description": "Task",
        }

        priorities = []
        for i in range(1, 11):
            priorities.append((i, f"Priority {i}"))
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
            "user": forms.Select(attrs={"class": ""}),
            "status": forms.Select(choices=STATUSES),
            "date_due": forms.DateInput(attrs={"type": "date", "class": ""}),
            "priority": forms.Select(choices=PRIORITIES),
            "date_completed": forms.DateInput(attrs={"type": "date", "class": ""}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.renderer = CustomFormRendererCompact()
        self.fields["priority"].initial = 5
        # Customize user field to display title case usernames
        self.fields["user"].label_from_instance = lambda obj: obj.username.title()

    def clean_description(self):
        description = self.cleaned_data["description"]
        if len(description) < 4:
            raise ValidationError("Description must be 4 or more  characters.")
        if len(description) > 200:
            raise ValidationError("Description is limited to 200 character.")
        return description

    def clean_matter(self):
        matter = self.cleaned_data["matter"]
        # if not matter:
        #     raise ValidationError("This field is required")

        return matter


class BulkTasksForm(forms.Form):
    STATUS_CHOICES = [
        ("", "— No change —"),
        ("Pending", "Pending"),
        ("Complete", "Complete"),
    ]

    PRIORITY_CHOICES = [("", "— No change —")] + [
        (str(i), f"Priority {i}") for i in range(1, 11)
    ]

    status = forms.ChoiceField(choices=STATUS_CHOICES, required=False, label="Status")
    priority = forms.ChoiceField(
        choices=PRIORITY_CHOICES, required=False, label="Priority"
    )
    date_due = forms.DateField(
        widget=forms.DateInput(attrs={"type": "date"}),
        required=False,
        label="Due Date",
    )
    user = forms.ModelChoiceField(
        queryset=CustomUser.objects.filter(is_active=True).order_by("username"),
        required=False,
        empty_label="— No change —",
        label="User",
    )
    matter = forms.ModelChoiceField(
        queryset=Matter.objects.filter(status__in=["Pending", "Open"]).order_by("name"),
        required=False,
        empty_label="— No change —",
        label="Matter",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.renderer = CustomFormRendererCompact()
        self.fields["user"].label_from_instance = lambda obj: obj.username.title()


class TaskNoteForm(forms.ModelForm):
    class Meta:
        model = TaskNote
        fields = ("date", "time", "details")
        widgets = {
            "date": forms.DateInput(attrs={"type": "date"}),
            "time": forms.TimeInput(attrs={"type": "time"}, format="%H:%M"),
            "details": forms.Textarea(
                attrs={
                    "class": "span3",
                    "rows": "4",
                    "maxlength": "300",
                    "placeholder": "",
                }
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.renderer = CustomFormRendererCompact()

    def clean_details(self):
        details = self.cleaned_data.get("details", "")
        if details and len(details) > 300:
            raise ValidationError("Note is limited to 300 characters.")
        return details
