from django.db import models

from apps.matters.models import Matter


class Proceeding(models.Model):
    user_id = models.IntegerField()
    matter = models.ForeignKey(Matter, on_delete=models.CASCADE, null=True)
    date_filed = models.DateField(null=True)
    forum = models.CharField(max_length=150, null=True)
    case_number = models.CharField(max_length=50, null=True)
    status = models.CharField(max_length=50, null=True)

    def __str__(self):
        return f"{self.case_number}"

    class Meta:
        db_table = "app_proceeding"
