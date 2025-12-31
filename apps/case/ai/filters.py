import django_filters

from .models import Conversation


class ConversationFilter(django_filters.FilterSet):
    order_by = django_filters.OrderingFilter(
        fields=[
            ("title", "title"),
            ("created_at", "created_at"),
            ("updated_at", "updated_at"),
        ],
        label="Order By",
    )

    class Meta:
        model = Conversation
        fields = ["order_by"]
