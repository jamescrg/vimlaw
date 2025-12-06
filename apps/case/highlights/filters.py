import django_filters
from django.db.models import Q

from apps.case.models import Document, Highlight, Label

IMPORTANCE_CHOICES = tuple((i, f"Importance {i}") for i in range(1, 11))


class HighlightsFilter(django_filters.FilterSet):
    """Filter for highlights list."""

    document = django_filters.ModelChoiceFilter(
        queryset=Document.objects.none(),
        empty_label="All",
        label="Document",
    )
    keyword = django_filters.CharFilter(method="filter_keyword", label="Keyword")
    label = django_filters.ModelChoiceFilter(
        method="filter_label",
        queryset=Label.objects.none(),
        empty_label="All Labels",
        label="Label",
    )
    importance = django_filters.ChoiceFilter(
        field_name="importance",
        choices=IMPORTANCE_CHOICES,
        lookup_expr="lte",
        label="Importance (≤)",
        empty_label="All",
    )
    order_by = django_filters.OrderingFilter(
        fields=[
            ("document__name", "document"),
            ("slug", "slug"),
        ],
        field_labels={
            "document__name": "Document",
            "slug": "Slug",
        },
        label="Order By",
    )

    class Meta:
        model = Highlight
        fields = ["document", "keyword", "label", "importance", "order_by"]

    def __init__(self, *args, matter=None, **kwargs):
        super().__init__(*args, **kwargs)
        if matter:
            self.filters["document"].queryset = Document.objects.filter(
                matter=matter
            ).order_by("name")
            self.filters["label"].queryset = Label.objects.filter(
                Q(matter=matter) | Q(matter__isnull=True)
            ).order_by("name")

    def filter_keyword(self, queryset, name, value):
        """Filter highlights by keyword in slug or text."""
        if value:
            return queryset.filter(Q(slug__icontains=value) | Q(text__icontains=value))
        return queryset

    def filter_label(self, queryset, name, value):
        """Filter highlights by label."""
        if value:
            return queryset.filter(labels=value)
        return queryset
