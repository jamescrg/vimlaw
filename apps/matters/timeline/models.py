from django.db import models

from apps.matters.models import Matter


class Fact(models.Model):
    user_id = models.IntegerField()
    matter = models.ForeignKey(Matter, on_delete=models.CASCADE, null=True)
    date = models.DateField(null=True)
    time = models.TimeField(auto_now=False, auto_now_add=False, null=True, blank=True)
    description = models.CharField(max_length=150, null=True)
    citation = models.CharField(max_length=155, blank=True, null=True)
    emphasis = models.CharField(max_length=50, blank=True, null=True)

    def __str__(self):
        return f"{self.description}"

    class Meta:
        db_table = "app_fact"
