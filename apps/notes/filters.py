import django_filters

from config.helpers import MultipleOrderingFilter

from .models import Note

IMPORTANCE_CHOICES = (
    (7, "Highest"),
    (6, "Higher"),
    (5, "High"),
    (4, "Normal"),
    (3, "Low"),
    (2, "Lower"),
    (1, "Lowest"),
)


class NotesFilter(django_filters.FilterSet):
    keyword = django_filters.CharFilter(method="filter_keyword", label="Keyword")
    category = django_filters.ChoiceFilter(
        field_name="category",
        choices=Note.CATEGORY_CHOICES,
        label="Category",
        empty_label="All Categories",
    )
    topic = django_filters.CharFilter(field_name="topic", lookup_expr="exact")
    importance = django_filters.ChoiceFilter(
        field_name="importance",
        choices=IMPORTANCE_CHOICES,
        lookup_expr="gte",
        label="Importance (≥)",
        empty_label="All",
    )
    order_by = MultipleOrderingFilter(
        fields=[
            ("updated_at", "updated_at"),
            ("created_at", "created_at"),
            ("title", "title"),
            ("topic", "topic"),
            ("importance", "importance"),
            ("viewed_at", "viewed_at"),
        ],
        field_labels={
            "updated_at": "Last Updated",
            "created_at": "Created",
            "title": "Title",
            "topic": "Topic",
            "importance": "Importance",
            "viewed_at": "Viewed",
        },
        label="Order By",
    )

    class Meta:
        model = Note
        fields = ["keyword", "category", "importance", "order_by"]

    def filter_keyword(self, queryset, name, value):
        if value:
            return queryset.filter(title__icontains=value)
        return queryset
