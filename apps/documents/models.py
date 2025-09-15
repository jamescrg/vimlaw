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

    def clean(self):
        # Validate the color field to ensure it is a valid hex code
        if not self.color.startswith("#") or len(self.color) != 7:
            raise ValueError("Color must be a valid hex code in the format #RRGGBB")

        # Validate only one label per matter with the same name
        if (
            Label.objects.filter(matter=self.matter, name=self.name)
            .exclude(id=self.id)
            .exists()
        ):
            raise ValueError("A label with this name already exists for this matter.")

        super().clean()

    def save(self, *args, **kwargs):
        self.full_clean()

        super().save(*args, **kwargs)


def document_upload_path(instance, filename):
    file_extension = filename.split(".")[-1].lower()
    file_name = instance.name if instance.name else filename

    matter_name = instance.matter.name if instance.matter else "unknown"
    matter_name = sanitize_filename(matter_name)

    if instance.proceeding and instance.proceeding.case_number:
        case_number = sanitize_filename(instance.proceeding.case_number)

        return (
            f"documents/{instance.matter_id}_{matter_name}/"
            f"{instance.category.capitalize()}/{instance.proceeding.id}_{case_number}/"
            f"{file_name}.{file_extension}"
        )

    return f"documents/{instance.matter_id}_{matter_name}/{instance.category.capitalize()}/{file_name}.{file_extension}"


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

    def clean(self):
        # Skip ManyToMany validation if object hasn't been saved yet
        if self.pk:
            # Validate all labels belong to the same matter as the document
            for label in self.labels.all():
                if label.matter != self.matter:
                    raise ValueError(
                        f"Label '{label.name}' does not belong to matter '{self.matter.name}'"
                    )

            # Validate no duplicate labels (labels with same name) on the document
            label_names = [label.name for label in self.labels.all()]
            if len(label_names) != len(set(label_names)):
                raise ValueError(
                    "Document cannot have multiple labels with the same name"
                )

        super().clean()

    def save(self, *args, **kwargs):
        self.full_clean()

        # Check if updating an existing document
        if self.pk:
            old_document = Document.objects.get(pk=self.pk)

            # Update file path if matter, name, category or proceeding has changed
            if (
                old_document.matter != self.matter
                or old_document.name != self.name
                or old_document.category != self.category
                or old_document.proceeding != self.proceeding
            ):
                old_path = old_document.file.name
                new_path = document_upload_path(self, self.file.name)

                if storage.exists(old_path):
                    storage.save(new_path, self.file)
                    storage.delete(old_path)

                    self.file.name = new_path

        super().save(*args, **kwargs)
