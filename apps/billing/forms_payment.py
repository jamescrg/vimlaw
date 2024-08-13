from datetime import datetime

from django import forms

from apps.billing.models_payment import Payment


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
            "matter": forms.Select(attrs={"required": True}),
            "date": forms.DateInput(attrs={"type": "date"}),
            "payment_method": forms.Select(attrs={"required": True}),
            "detail": forms.TextInput(attrs={"required": False}),
            "amount": forms.TextInput(attrs={"required": True}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        today = datetime.now().date()

        self.fields["date"].initial = today
        self.fields["payment_method"].initial = "CARD"
