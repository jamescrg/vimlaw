from django.db import models

from apps.matters.models import Matter


class Fact(models.Model):
    COLOR_CHOICES = [
        (None, "None"),
        ("Blue", "Blue"),
        ("Gray", "Gray"),
        ("Green", "Green"),
        ("Orange", "Orange"),
        ("Purple", "Purple"),
        ("Red", "Red"),
        ("Yellow", "Yellow"),
    ]

    user_id = models.IntegerField()
    matter = models.ForeignKey(Matter, on_delete=models.CASCADE, null=True)
    date = models.DateField(null=True)
    time = models.TimeField(auto_now=False, auto_now_add=False, null=True, blank=True)
    description = models.CharField(max_length=150, null=True)
    citations = models.CharField(max_length=255, blank=True, null=True)
    color = models.CharField(
        max_length=10, choices=COLOR_CHOICES, blank=True, null=True, default=None
    )

    def __str__(self):
        return f"{self.description}"

    class Meta:
        db_table = "app_fact"
