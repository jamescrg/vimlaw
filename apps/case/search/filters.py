import django_filters
from django import forms
from django.db.models import Q

from apps.case.models import Document, Label

IMPORTANCE_CHOICES = tuple((i, f"Importance {i}") for i in range(1, 11))


class SearchFilter(django_filters.FilterSet):
    """Filter for unified search results across Documents, Highlights, and Facts."""

    TYPE_CHOICES = [
        ("", "All Types"),
        ("document", "Documents"),
        ("highlight", "Highlights"),
        ("fact", "Facts"),
    ]

    result_type = django_filters.ChoiceFilter(
        choices=TYPE_CHOICES,
        method="filter_noop",
        empty_label=None,
        label="Type",
    )
    category = django_filters.ChoiceFilter(
        choices=[("", "All")] + Document.CATEGORY_CHOICES,
        method="filter_noop",
        empty_label=None,
        label="Category",
    )
    label = django_filters.ModelChoiceFilter(
        method="filter_noop",
        queryset=Label.objects.none(),
        empty_label="All Labels",
        label="Label",
    )
    document = django_filters.ModelChoiceFilter(
        queryset=Document.objects.none(),
        method="filter_noop",
        empty_label="All Documents",
        label="Document",
    )
    date_from = django_filters.DateFilter(
        method="filter_noop",
        label="Date From",
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    date_to = django_filters.DateFilter(
        method="filter_noop",
        label="Date To",
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    importance = django_filters.ChoiceFilter(
        choices=IMPORTANCE_CHOICES,
        method="filter_noop",
        label="Importance (≤)",
        empty_label="All",
    )

    class Meta:
        model = Document
        fields = [
            "result_type",
            "category",
            "label",
            "document",
            "date_from",
            "date_to",
            "importance",
        ]

    def __init__(self, data=None, *args, matter=None, **kwargs):
        super().__init__(data, *args, **kwargs)
        self.matter = matter
        if matter:
            self.filters["label"].queryset = Label.objects.filter(
                Q(matter=matter) | Q(matter__isnull=True)
            ).order_by("name")

            # Build document queryset filtered by category and label if set
            doc_qs = Document.objects.filter(matter=matter)

            if data:
                # Filter by category if selected
                category = data.get("category", "")
                if category:
                    doc_qs = doc_qs.filter(category=category)

                # Filter by label if selected
                label_id = data.get("label", "")
                if label_id:
                    try:
                        doc_qs = doc_qs.filter(labels__id=int(label_id))
                    except (ValueError, TypeError):
                        pass

            self.filters["document"].queryset = doc_qs.order_by("name")

    def filter_noop(self, queryset, name, value):
        """No-op filter - actual filtering done in view on search results."""
        return queryset
