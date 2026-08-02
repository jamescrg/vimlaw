from django.db.models.signals import pre_delete
from django.dispatch import receiver

from apps.case.models import Document

from .models import DriveRecordTombstone


@receiver(pre_delete, sender=Document)
def tombstone_synced_record(sender, instance, **kwargs):
    """Remember deleted Drive-synced documents so the sync doesn't re-ingest
    them while the file still exists in the Drive record folder."""
    if instance.drive_file_id:
        DriveRecordTombstone.objects.get_or_create(drive_file_id=instance.drive_file_id)
