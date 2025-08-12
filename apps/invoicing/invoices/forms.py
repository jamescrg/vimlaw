from datetime import datetime, timedelta

from django import forms

from apps.invoicing.invoices.models import Invoice
from config.settings import CustomFormRendererCompact


class InvoiceForm(forms.ModelForm):
    class Meta:
        model = Invoice
        fields = [
            "matter",
            "date_limit",
            "date_issued",
            "message",
            "comment",
            "discount",
            "show_comp",
        ]
        widgets = {
            "matter": forms.Select(attrs={"class": "span2"}),
            "date_issued": forms.DateInput(attrs={"type": "date"}),
            "date_limit": forms.DateInput(attrs={"type": "date"}),
            "message": forms.Textarea(attrs={"rows": 3, "class": "span2"}),
            "comment": forms.Textarea(attrs={"rows": 3, "class": "span2"}),
            "discount": forms.TextInput(attrs={"class": "span2"}),
            "show_comp": forms.CheckboxInput(attrs={"class": "span2"}),
        }

    def clean_matter(self):
        matter = self.cleaned_data.get("matter")

        if not matter:
            raise forms.ValidationError("This field is required")

        return matter

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.renderer = CustomFormRendererCompact()

        today = datetime.now().date()

        first_day_of_current_month = today.replace(day=1)

        last_day_of_previous_month = first_day_of_current_month - timedelta(days=1)

        self.fields["date_issued"].initial = today
        self.fields["date_issued"].label = "Issue Date"
        self.fields["show_comp"].initial = True

        self.fields["date_limit"].initial = last_day_of_previous_month
        self.fields["date_limit"].label = "Limit Date"


class EditInvoiceForm(forms.ModelForm):
    class Meta:
        model = Invoice

        fields = [
            "date_limit",
            "date_issued",
            "message",
            "comment",
            "discount",
            "show_comp",
        ]
        widgets = {
            "date_issued": forms.DateInput(attrs={"type": "date"}),
            "date_limit": forms.DateInput(attrs={"type": "date"}),
            "message": forms.Textarea(attrs={"rows": 3, "class": "span2"}),
            "comment": forms.Textarea(attrs={"rows": 3, "class": "span2"}),
            "discount": forms.TextInput(attrs={"class": "span2"}),
            "show_comp": forms.CheckboxInput(attrs={"class": "span2"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.renderer = CustomFormRendererCompact()
