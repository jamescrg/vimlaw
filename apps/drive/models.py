from django.db import models
from django.utils import timezone


class DriveSyncState(models.Model):
    """Stores the Google Drive Changes API page token for incremental sync.

    A single row holds the cursor for the document mirror. Mirrors the shape
    of apps.calendar.models.CalendarSyncState (which stores a Calendar sync
    token); here we persist the Drive ``changes`` page token instead.
    """

    page_token = models.TextField(null=True, blank=True)
    # Drive matter-folder names seen during sync with no matching
    # Matter.drive_folder — surfaced as a drift warning on the integrations page.
    unmatched_folders = models.JSONField(default=list, blank=True)
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


# Mirrors Document.CATEGORY_CHOICES (apps/case/models.py); kept local so this
# module stays import-light for the sync engine and migrations.
MAPPING_CATEGORY_CHOICES = [
    ("Correspondence", "Correspondence"),
    ("Discovery", "Discovery"),
    ("Evidence", "Evidence"),
    ("Record", "Record"),
]


class DriveFolderMapping(models.Model):
    """One subfolder of a matter's Drive folder, mapped to a document category.

    The Documents tab's Drive Folder modal creates one row per top-level
    subfolder the user maps; PDFs anywhere under that folder sync in with
    the row's category and proceeding (nearest mapped ancestor wins, which
    only matters for legacy nested rows such as ``Evidence/Key Documents``
    carried over from the retired convention). Unmapped folders are ignored.

    Identity is the Drive folder id so renames in Drive do not break the
    link; ``folder_path`` is the cached path relative to the matter folder,
    refreshed whenever the folder is listed. ``folder_id`` is NULL only for
    rows created by the data migration from the old name-based links, until
    the next full sync or modal open resolves the path to an id.

    Category rules mirror Document.save(): Record needs a proceeding,
    Discovery may have one, Correspondence and Evidence never do.
    """

    matter = models.ForeignKey(
        "matters.Matter",
        on_delete=models.CASCADE,
        related_name="drive_folder_mappings",
    )
    folder_id = models.CharField(max_length=255, null=True, blank=True)
    folder_path = models.CharField(max_length=1024)
    category = models.CharField(max_length=20, choices=MAPPING_CATEGORY_CHOICES)
    # Deleting a proceeding unmaps its folders; they reappear as unmapped
    # suggestions in the modal. Documents keep proceeding=NULL via their FK.
    proceeding = models.ForeignKey(
        "matters.Proceeding",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="drive_folder_mappings",
    )
    # Set by the full sync / modal save when the folder is gone from Drive;
    # the row and its documents are never deleted for that.
    missing_since = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "app_drive_folder_mapping"
        constraints = [
            models.UniqueConstraint(
                fields=["folder_id"],
                condition=models.Q(folder_id__isnull=False),
                name="unique_drive_folder_mapping_folder_id",
            ),
            models.UniqueConstraint(
                fields=["matter", "folder_path"],
                condition=models.Q(folder_id__isnull=True),
                name="unique_drive_folder_mapping_legacy_path",
            ),
            models.CheckConstraint(
                check=(
                    models.Q(category="Record", proceeding__isnull=False)
                    | models.Q(category="Discovery")
                    | models.Q(
                        category__in=["Correspondence", "Evidence"],
                        proceeding__isnull=True,
                    )
                ),
                name="drive_folder_mapping_proceeding_rule",
            ),
        ]

    def __str__(self):
        return f"{self.matter_id}:{self.folder_path} -> {self.category}"

    @property
    def folder_name(self):
        return self.folder_path.rsplit("/", 1)[-1]

    @property
    def is_nested(self):
        return "/" in self.folder_path


class DriveMatterState(models.Model):
    """Per-matter Drive housekeeping for the Documents-tab nudge badge.

    Written by the nightly full sync and by every Drive Folder modal save;
    read (DB only, never Drive) when the Documents tab renders. Kept off
    Matter so nightly refreshes do not write HistoricalMatter rows.
    """

    matter = models.OneToOneField(
        "matters.Matter", on_delete=models.CASCADE, related_name="drive_state"
    )
    # [{"id": ..., "name": ...}] top-level subfolders with no mapping
    # (the retired Notes mirror's folder excluded).
    unmapped_folders = models.JSONField(default=list, blank=True)
    # Matter.drive_folder_id not found under the root on the last full pass.
    folder_missing = models.BooleanField(default=False)
    checked_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "app_drive_matter_state"

    def __str__(self):
        return f"Drive state for matter {self.matter_id}"
