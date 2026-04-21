from django import forms
from django.core.exceptions import ValidationError

from apps.accounts.access import filter_matters_for_user
from apps.accounts.models import CustomUser
from apps.matters.models import Matter
from apps.tasks.models import Task, TaskNote
from config.settings import CustomFormRendererCompact


class TaskForm(forms.ModelForm):
    class Meta:
        model = Task

        fields = (
            "matter",
            "description",
            "user",
            "importance",
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

        IMPORTANCE_CHOICES = (
            (7, "Highest"),
            (6, "Higher"),
            (5, "High"),
            (4, "Normal"),
            (3, "Low"),
            (2, "Lower"),
            (1, "Lowest"),
        )

        widgets = {
            "description": forms.TextInput(
                attrs={
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
            "importance": forms.Select(choices=IMPORTANCE_CHOICES),
            "date_completed": forms.DateInput(attrs={"type": "date", "class": ""}),
        }

    def __init__(self, *args, **kwargs):
        user = kwargs.pop("user", None)
        super().__init__(*args, **kwargs)
        self.renderer = CustomFormRendererCompact()
        self.fields["importance"].initial = 4
        # Customize user field to display title case usernames
        self.fields["user"].label_from_instance = lambda obj: obj.username.title()
        if user:
            self.fields["matter"].queryset = filter_matters_for_user(
                self.fields["matter"].queryset, user
            )

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

    IMPORTANCE_CHOICES = [
        ("", "— No change —"),
        ("7", "Highest"),
        ("6", "Higher"),
        ("5", "High"),
        ("4", "Normal"),
        ("3", "Low"),
        ("2", "Lower"),
        ("1", "Lowest"),
    ]

    status = forms.ChoiceField(choices=STATUS_CHOICES, required=False, label="Status")
    importance = forms.ChoiceField(
        choices=IMPORTANCE_CHOICES, required=False, label="Priority"
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
        user = kwargs.pop("user", None)
        super().__init__(*args, **kwargs)

        self.renderer = CustomFormRendererCompact()
        self.fields["user"].label_from_instance = lambda obj: obj.username.title()
        if user:
            self.fields["matter"].queryset = filter_matters_for_user(
                self.fields["matter"].queryset, user
            )


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
