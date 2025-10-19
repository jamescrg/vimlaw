from django.contrib.auth import get_user_model
from django.core.files.storage import default_storage as storage
from django.db import models

from apps.documents.utils import sanitize_filename
from apps.matters.models import Matter
from apps.matters.proceedings.models import Proceeding

User = get_user_model()


class Label(models.Model):
    matter = models.ForeignKey(Matter, on_delete=models.CASCADE, related_name="labels")
    name = models.CharField(max_length=100)
    color = models.CharField(max_length=7, default="#FFFFFF")  # Hex color code

    def __str__(self):
        return self.name

    class Meta:
        db_table = "app_label"
        ordering = ["name"]


def document_upload_path(instance, filename):
    file_extension = filename.split(".")[-1].lower()

    file_name = instance.name if instance.name else filename
    file_name = sanitize_filename(file_name)

    full_file_name = f"{file_name}.{file_extension}"

    if instance.category == "Record" and instance.date:
        file_name = f"{instance.date}_{file_name}"
        full_file_name = f"{file_name}.{file_extension}"

    matter_name = instance.matter.name if instance.matter else "unknown"
    matter_name = sanitize_filename(matter_name)

    if instance.proceeding and instance.proceeding.case_number:
        case_number = (
            sanitize_filename(instance.proceeding.case_number)
            if instance.proceeding.case_number
            else "UnknownCase"
        )
        forum = (
            sanitize_filename(instance.proceeding.forum)
            if instance.proceeding.forum
            else "UnknownForum"
        )

        return (
            f"documents/{matter_name}_{instance.matter_id}/"
            f"{instance.category.capitalize()}/{forum}_{case_number}_{instance.proceeding.id}/"
            f"{full_file_name}"
        )

    return f"documents/{matter_name}_{instance.matter_id}/{instance.category.capitalize()}/{full_file_name}"


class Document(models.Model):
    CATEGORY_CHOICES = [
        ("Evidence", "Evidence"),
        ("Record", "Record"),
        ("Correspondence", "Correspondence"),
        ("Discovery", "Discovery"),
    ]

    matter = models.ForeignKey(
        Matter, on_delete=models.CASCADE, related_name="documents"
    )
    date = models.DateField(blank=True, null=True)
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True, null=True)
    category = models.CharField(
        max_length=20,
        choices=CATEGORY_CHOICES,
        default="Evidence",
    )
    proceeding = models.ForeignKey(
        Proceeding, on_delete=models.SET_NULL, null=True, blank=True
    )
    file = models.FileField(upload_to=document_upload_path)
    labels = models.ManyToManyField(Label, related_name="documents", blank=True)
    uploaded_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name

    class Meta:
        db_table = "app_document"
        ordering = ["-uploaded_at"]

    def save(self, *args, **kwargs):
        self.full_clean()

        # Set category to "Record" if proceeding is set
        if self.proceeding and self.category != "Record":
            self.category = "Record"

        # Check if updating an existing document
        if self.pk:
            old_document = Document.objects.get(pk=self.pk)

            # Update file path if matter, name, category or proceeding has changed
            if (
                old_document.matter != self.matter
                or old_document.name != self.name
                or old_document.category != self.category
                or old_document.proceeding != self.proceeding
                or old_document.date != self.date
            ):
                old_path = old_document.file.name
                new_path = document_upload_path(self, self.file.name)

                if storage.exists(old_path):
                    storage.save(new_path, self.file)
                    storage.delete(old_path)

                    self.file.name = new_path

        super().save(*args, **kwargs)
