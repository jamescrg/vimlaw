from django.db import models

from apps.accounts.models import CustomUser
from apps.contacts.models import Contact


class Matter(models.Model):
    user_id = models.IntegerField(null=True)
    name = models.CharField(max_length=50, null=True)
    description = models.CharField(max_length=255, null=True)
    status = models.CharField(max_length=50, null=True)
    date_start = models.DateField(null=True)
    date_end = models.DateField(blank=True, null=True)
    firm = models.CharField(max_length=50, null=True)
    firm_file_no = models.CharField(max_length=500, null=True, blank=True)
    ref_no = models.CharField(max_length=50, blank=True, null=True)
    practice_area = models.CharField(max_length=50, null=True)
    hourly_rate = models.IntegerField(blank=True, null=True)
    firm_rate = models.IntegerField(null=True)
    contacts = models.ManyToManyField(Contact, through="Relationship")
    client = models.ForeignKey(
        Contact, related_name="client_matters", on_delete=models.SET_NULL, null=True
    )

    def __str__(self):
        return f"{self.name}"

    class Meta:
        db_table = "app_matter"


class Role(models.Model):
    name = models.CharField(max_length=50)

    def __str__(self):
        return f"{self.name}"

    class Meta:
        db_table = "app_matter_role"


class Relationship(models.Model):
    matter = models.ForeignKey(
        Matter,
        on_delete=models.CASCADE,
    )
    contact = models.ForeignKey(Contact, on_delete=models.CASCADE)
    role = models.ForeignKey(Role, on_delete=models.CASCADE)

    class Meta:
        db_table = "app_matter_relationship"

    def __str__(self):
        return f"matter: {self.matter.id}, contact: {self.contact.id}, role: {self.role.id}"


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


class SettlementEntry(models.Model):
    user_id = models.IntegerField()
    matter = models.ForeignKey(Matter, on_delete=models.CASCADE, null=True)
    date = models.DateField(null=True)
    medium = models.CharField(max_length=50, blank=True, null=True)
    type = models.CharField(max_length=150, null=True)
    amount = models.CharField(max_length=50, null=True)
    notes = models.CharField(max_length=50, blank=True, null=True)

    def __str__(self):
        return f"{self.amount}"

    class Meta:
        db_table = "app_settlement"


class Fact(models.Model):
    user_id = models.IntegerField()
    matter = models.ForeignKey(Matter, on_delete=models.CASCADE, null=True)
    date = models.DateField(null=True)
    description = models.CharField(max_length=150, null=True)
    citation = models.CharField(max_length=155, blank=True, null=True)
    emphasis = models.CharField(max_length=50, blank=True, null=True)

    def __str__(self):
        return f"{self.description}"

    class Meta:
        db_table = "app_fact"


class Rate(models.Model):
    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE)
    matter = models.ForeignKey(Matter, on_delete=models.CASCADE, null=True)
    matter_rate = models.IntegerField()

    def __str__(self):
        return f"{self.matter.name} - {self.user.username} - {self.matter_rate}"

    class Meta:
        db_table = "app_matter_rate"
