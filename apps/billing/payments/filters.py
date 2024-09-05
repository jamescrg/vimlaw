import django_filters

from apps.billing.payments.models import PAYMENT_METHOD_CHOICES, Payment
from apps.matters.models import Matter
from config.helpers import MultipleOrderingFilter


class PaymentFilter(django_filters.FilterSet):
    payment_method = django_filters.ChoiceFilter(
        choices=PAYMENT_METHOD_CHOICES, empty_label="All"
    )
    matter = django_filters.ModelChoiceFilter(
        queryset=Matter.objects.filter(status="Open").order_by("name"),
        empty_label="All",
    )
    date = django_filters.DateFromToRangeFilter(
        widget=django_filters.widgets.RangeWidget(attrs={"type": "date"})
    )
    order_by = MultipleOrderingFilter(
        fields=[(("date", "id"), "date")], empty_label=None
    )

    class Meta:
        model = Payment
        fields = ["payment_method", "matter", "date"]
