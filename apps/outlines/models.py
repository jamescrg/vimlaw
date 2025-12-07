from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone

from apps.accounts.models import CustomUser
from apps.matters.models import Matter


class Outline(models.Model):
    """A single outline/document containing a tree of items."""

    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE)
    matter = models.ForeignKey(
        Matter,
        on_delete=models.CASCADE,
        related_name="outlines",
    )
    title = models.CharField(max_length=200)
    date = models.DateField(default=timezone.localdate)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    viewed_at = models.DateTimeField(null=True, blank=True)
    importance = models.PositiveIntegerField(
        default=5, validators=[MinValueValidator(1), MaxValueValidator(10)]
    )

    class Meta:
        ordering = ["-date"]

    def __str__(self):
        return self.title

    def get_root_items(self):
        """Get top-level items (no parent)."""
        return self.items.filter(parent__isnull=True).order_by("order")


class OutlineItem(models.Model):
    """A single item/node in the outline tree."""

    outline = models.ForeignKey(Outline, on_delete=models.CASCADE, related_name="items")
    parent = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="children",
    )
    content = models.TextField(blank=True, default="")
    order = models.PositiveIntegerField(default=0)
    collapsed = models.BooleanField(default=False)
    heading = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["order"]

    def __str__(self):
        preview = self.content[:50] if self.content else "(empty)"
        return f"{preview}"

    def get_children(self):
        """Get ordered children."""
        return self.children.all().order_by("order")

    def get_siblings(self):
        """Get siblings (same parent) including self."""
        return OutlineItem.objects.filter(
            outline=self.outline, parent=self.parent
        ).order_by("order")

    def get_previous_sibling(self):
        """Get the sibling before this one."""
        siblings = list(self.get_siblings())
        try:
            idx = siblings.index(self)
            if idx > 0:
                return siblings[idx - 1]
        except (ValueError, IndexError):
            pass
        return None

    def get_next_sibling(self):
        """Get the sibling after this one."""
        siblings = list(self.get_siblings())
        try:
            idx = siblings.index(self)
            if idx < len(siblings) - 1:
                return siblings[idx + 1]
        except (ValueError, IndexError):
            pass
        return None

    def get_depth(self):
        """Calculate nesting depth (0 for root items)."""
        depth = 0
        item = self
        while item.parent:
            depth += 1
            item = item.parent
        return depth
