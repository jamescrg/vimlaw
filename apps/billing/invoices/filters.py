import django_filters

from apps.billing.invoices.models import INVOICE_STATUS, Invoice
from apps.matters.models import Matter
from config.helpers import MultipleOrderingFilter


class InvoiceFilter(django_filters.FilterSet):
    matter = django_filters.ModelChoiceFilter(
        queryset=Matter.objects.filter(invoice__isnull=False)
        .distinct()
        .order_by("name"),
        empty_label="All",
    )
    status = django_filters.ChoiceFilter(choices=INVOICE_STATUS, empty_label="All")
    date_issued = django_filters.DateFromToRangeFilter(
        widget=django_filters.widgets.RangeWidget(attrs={"type": "date"})
    )
    order_by = MultipleOrderingFilter(
        fields=[
            (("date_issued", "id"), "date_issued"),
            ("matter__name", "matter"),
            ("status", "status"),
        ],
        empty_label=None,
    )

    class Meta:
        model = Invoice
        fields = ["matter", "status", "date_issued"]
