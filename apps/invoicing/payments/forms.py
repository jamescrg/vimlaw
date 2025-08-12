from datetime import datetime

from django import forms

from apps.invoicing.payments.models import Payment
from config.settings import CustomFormRendererCompact


class PaymentForm(forms.ModelForm):
    class Meta:
        model = Payment
        fields = [
            "matter",
            "date",
            "payment_method",
            "detail",
            "amount",
        ]
        widgets = {
            "matter": forms.Select(attrs={"class": "span2"}),
            "date": forms.DateInput(attrs={"type": "date"}),
            "payment_method": forms.Select(),
            "detail": forms.TextInput(attrs={"required": False, "class": "span2"}),
            "amount": forms.TextInput(attrs={"class": "span2"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.renderer = CustomFormRendererCompact()

        today = datetime.now().date()

        self.fields["date"].initial = today
        self.fields["payment_method"].initial = "CARD"
