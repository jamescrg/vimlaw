from django.db import models
from django.utils import timezone


class DriveSyncState(models.Model):
    """Stores the Google Drive Changes API page token for incremental sync.

    A single row holds the cursor for the case-notes mirror. Mirrors the shape
    of apps.calendar.models.CalendarSyncState (which stores a Calendar sync
    token); here we persist the Drive ``changes`` page token instead.
    """

    page_token = models.TextField(null=True, blank=True)
    # Drive matter-folder names seen during sync with no matching
    # Matter.drive_folder — surfaced as a drift warning on the integrations page.
    unmatched_folders = models.JSONField(default=list, blank=True)
    # "<matter folder>/<record folder>" links whose folder wasn't found in
    # Drive during the last full pass — drift warning, nothing is deleted.
    missing_record_folders = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    last_sync_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Drive sync state (token set: {bool(self.page_token)})"

    class Meta:
        db_table = "app_drive_sync_state"


class DriveRecordTombstone(models.Model):
    """Drive file ids of synced record Documents deleted in the app.

    The record sync never mirrors Drive deletions, so without a tombstone a
    document deliberately deleted in the app would boomerang back on the
    next pass while its file still sits in the Drive folder. Written by a
    pre_delete signal (apps/drive/signals.py) so every delete path (row,
    bulk, matter cascade) is covered; ingest skips these ids.
    """

    drive_file_id = models.CharField(max_length=255, unique=True)
    created_at = models.DateTimeField(default=timezone.now)

    def __str__(self):
        return self.drive_file_id

    class Meta:
        db_table = "app_drive_record_tombstone"
