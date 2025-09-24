import django_filters

from apps.documents.models import Document
from apps.matters.models import Matter


class DocumentsFilter(django_filters.FilterSet):
    name = django_filters.CharFilter(lookup_expr="icontains", label="Name")
    matter = django_filters.ModelChoiceFilter(
        queryset=Matter.objects.filter(documents__isnull=False)
        .distinct()
        .order_by("name"),
        empty_label="All",
    )
    order_by = django_filters.OrderingFilter(
        fields=[
            ("name", "name"),
            ("matter__name", "matter"),
            ("uploaded_by__first_name", "uploaded_by"),
            ("uploaded_at", "uploaded_at"),
            ("date", "date"),
        ]
    )

    class Meta:
        model = Document
        fields = ["name", "matter", "order_by"]
