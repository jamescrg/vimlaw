from django.db import models
from simple_history.models import HistoricalRecords

from apps.contacts.models import Contact
from utils.models import AuditMixin

BILLING_TYPE_CHOICES = (
    ("HOURLY", "Hourly"),
    ("FLAT_FEE", "Flat Fee"),
)


class Matter(AuditMixin, models.Model):
    user = models.ForeignKey(
        "accounts.CustomUser", on_delete=models.SET_NULL, null=True, blank=True
    )
    name = models.CharField(max_length=50, null=True)
    work_status = models.CharField(max_length=255, null=True, blank=True)
    description = models.CharField(max_length=255, null=True, blank=True)
    status = models.CharField(max_length=50, null=True)
    date_start = models.DateField(null=True)
    date_end = models.DateField(blank=True, null=True)

    clio_matter_id = models.CharField(max_length=500, null=True, blank=True)
    client_reference_id = models.CharField(max_length=50, blank=True, null=True)
    # This matter's Google Drive folder under DRIVE_NOTES_ROOT: the folder
    # id is the link (renames in Drive keep working), the name is kept for
    # display and the drafts picker. Set via the Documents tab's Drive
    # Folder modal (or the link_drive_folders command); its mapped
    # subfolders (apps.drive.models.DriveFolderMapping) feed the document
    # mirror.
    drive_folder = models.CharField(max_length=255, null=True, blank=True)
    drive_folder_id = models.CharField(max_length=255, null=True, blank=True)
    # Gmail label mapped to this matter for case-email sync. The label NAME
    # is the contract: every connected mailbox (GmailAccount) resolves it to
    # its own label id at sync time, so one link serves all mailboxes.
    # gmail_label_id is legacy (pre-multi-account) and no longer written.
    gmail_label_id = models.CharField(max_length=64, null=True, blank=True)
    gmail_label_name = models.CharField(max_length=255, null=True, blank=True)
    practice_area = models.ForeignKey(
        "PracticeArea",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="matters",
    )
    contacts = models.ManyToManyField(Contact, through="Relationship")
    client = models.ForeignKey(
        Contact, related_name="client_matters", on_delete=models.SET_NULL, null=True
    )
    jurisdiction = models.CharField(max_length=100, blank=True)
    billable = models.BooleanField(default=True)
    billing_type = models.CharField(
        max_length=20, choices=BILLING_TYPE_CHOICES, default="HOURLY"
    )
    flat_fee_amount = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True
    )
    # Deferred-fee arrangement (e.g. hybrid agreements): fees accrue but are not
    # currently collectible, and the retainer is waived. Drives the low-trust-available
    # exclusion regardless of whether the matter has been invoiced yet.
    deferred_fees = models.BooleanField(default=False)
    # Whether uncategorized time counts toward the claimed total in the
    # activity Categories view. Matter-level so the whole team sees the same
    # rollup (the attorney sets it, the paralegal's view reflects it).
    uncategorized_claimed = models.BooleanField(default=True)
    # Defaults for the Fee and Expense Report's options; the modal reads
    # them and generating the report saves the choices back, so the
    # settings follow the matter.
    report_include_unclaimed = models.BooleanField(default=True)
    report_show_entries = models.BooleanField(default=True)
    report_group_by_category = models.BooleanField(default=True)
    # Claim comped work too: fees compute on gross and comp entries lose
    # the struck-through treatment.
    report_reclaim_comp = models.BooleanField(default=False)
    members = models.ManyToManyField(
        "accounts.CustomUser",
        related_name="assigned_matters",
        blank=True,
    )
    history = HistoricalRecords()

    def __str__(self):
        return f"{self.name}"

    class Meta:
        db_table = "app_matter"
        indexes = [
            models.Index(fields=["status"]),
            models.Index(fields=["client"]),
            models.Index(fields=["billable"]),
            models.Index(fields=["billing_type"]),
        ]

    # Statuses under which work is no longer tracked: the file has moved out
    # of the "Matters - Open" Drive/Gmail roots, so its mirrors are unlinked.
    # "Complete" is the closing-out phase (usually waiting on a trust
    # reimbursement); "Closed" is final and additionally starts the chat
    # retention clock (apps/case/ai/purge.py).
    INACTIVE_STATUSES = ("Complete", "Closed")

    def save(self, *args, **kwargs):
        if self.status in self.INACTIVE_STATUSES:
            from apps.matters.proceedings.models import Proceeding

            # Mark all proceedings as concluded when work ends, and drop the
            # matter's Drive folder mappings along with its Drive and Gmail
            # links. Closed-out files move out of the "Matters - Open"
            # Drive/Gmail roots, so stale links only produce missing-folder
            # and missing-label drift warnings (and automatic label setup
            # would recreate the matter's Gmail labels). Synced rows all
            # survive the unlink: record Documents are append-only and
            # Email rows are only removed by label events on a still-mapped
            # matter.
            Proceeding.objects.filter(matter=self).update(status="Concluded")
            self.gmail_label_id = None
            self.gmail_label_name = None
            self.drive_folder = None
            self.drive_folder_id = None
            if self.pk:
                from apps.drive.models import DriveFolderMapping, DriveMatterState

                DriveFolderMapping.objects.filter(matter=self).delete()
                DriveMatterState.objects.filter(matter=self).delete()

        # (Client status is no longer maintained here — it's derived from a
        # contact's matters; see apps.contacts.models.derive_client_status.)

        # Document files are stored by matter ID (see case.models
        # document_upload_path: documents/{matter_id}/{document_id}.ext), so a
        # name change never requires moving files. (Older builds embedded the
        # matter name in the path and rewrote every document on rename — slow,
        # and it reverted files to the deprecated name-based layout.)
        super().save(*args, **kwargs)

        self._ensure_client_relationship()

    def _ensure_client_relationship(self):
        """Make sure the canonical client (Matter.client) is represented as a
        party in the Client group + Client role.

        Purely additive: it only ever *adds* the one missing row and never
        removes or edits anything else, so co-clients, spouses, and former
        clients that also carry the Client role are left untouched. Idempotent —
        does nothing if the row already exists or the matter has no client.
        Matter.client stays the canonical field; this is only its representation
        on the parties list."""
        if not self.client_id:
            return
        client_group = Group.objects.client_group()
        client_role = Role.objects.client_role()
        if client_group is None or client_role is None:
            return
        already = Relationship.objects.filter(
            matter=self,
            contact_id=self.client_id,
            group=client_group,
            role=client_role,
        ).exists()
        if not already:
            Relationship.objects.create(
                matter=self,
                contact_id=self.client_id,
                group=client_group,
                role=client_role,
            )

    @property
    def gmail_label_short(self):
        """Label name without the GMAIL_LABEL_ROOT prefix, for display."""
        from django.conf import settings

        name = self.gmail_label_name or ""
        prefix = f"{settings.GMAIL_LABEL_ROOT}/" if settings.GMAIL_LABEL_ROOT else ""
        if prefix and name.startswith(prefix):
            return name[len(prefix) :]
        return name

    @property
    def primary_proceeding(self):
        """Return the primary proceeding for this matter, if any."""
        from apps.matters.proceedings.models import Proceeding

        return Proceeding.objects.filter(matter=self, primary=True).first()

    @property
    def value(self):
        from django.db.models import Case, DecimalField, F, Sum, Value, When

        from apps.activity.expenses.models import ExpenseEntry
        from apps.activity.flat_fees.models import FlatFeeEntry
        from apps.activity.time.models import TimeEntry
        from apps.invoicing.invoices.models import Invoice
        from apps.invoicing.payments.models import Payment

        # Helper to build fee/expense aggregation dict
        def aggregate_fees(queryset):
            """Aggregate time entry fees using database-level calculation."""
            result = queryset.aggregate(
                gross_fees=Sum(
                    F("hours") * F("rate"),
                    output_field=DecimalField(max_digits=10, decimal_places=2),
                ),
                comp_fees=Sum(
                    Case(
                        When(comp=True, then=F("hours") * F("rate")),
                        default=Value(0),
                        output_field=DecimalField(max_digits=10, decimal_places=2),
                    )
                ),
            )
            gross = result["gross_fees"] or 0
            comp = result["comp_fees"] or 0
            return gross, comp

        def aggregate_expenses(queryset):
            """Aggregate expense amounts using database-level calculation."""
            result = queryset.aggregate(
                gross_expenses=Sum("amount"),
                comp_expenses=Sum(
                    Case(
                        When(comp=True, then=F("amount")),
                        default=Value(0),
                        output_field=DecimalField(max_digits=10, decimal_places=2),
                    )
                ),
            )
            gross = result["gross_expenses"] or 0
            comp = result["comp_expenses"] or 0
            return gross, comp

        def aggregate_flat_fees(queryset):
            """Aggregate flat-fee amounts using database-level calculation."""
            result = queryset.aggregate(
                gross_flat_fees=Sum("amount"),
                comp_flat_fees=Sum(
                    Case(
                        When(comp=True, then=F("amount")),
                        default=Value(0),
                        output_field=DecimalField(max_digits=10, decimal_places=2),
                    )
                ),
            )
            gross = result["gross_flat_fees"] or 0
            comp = result["comp_flat_fees"] or 0
            return gross, comp

        # Total fees and expenses (all entries for this matter)
        gross_fees, comp_fees = aggregate_fees(TimeEntry.objects.filter(matter=self))
        net_fees = gross_fees - comp_fees

        gross_expenses, comp_expenses = aggregate_expenses(
            ExpenseEntry.objects.filter(matter=self)
        )
        net_expenses = gross_expenses - comp_expenses

        gross_flat_fees, comp_flat_fees = aggregate_flat_fees(
            FlatFeeEntry.objects.filter(matter=self)
        )
        net_flat_fees = gross_flat_fees - comp_flat_fees

        total = {
            "gross_fees": gross_fees,
            "comp_fees": comp_fees,
            "net_fees": net_fees,
            "gross_expenses": gross_expenses,
            "comp_expenses": comp_expenses,
            "net_expenses": net_expenses,
            "gross_flat_fees": gross_flat_fees,
            "comp_flat_fees": comp_flat_fees,
            "net_flat_fees": net_flat_fees,
            "net_fees_and_expenses": net_fees + net_expenses + net_flat_fees,
        }

        # Unbilled fees and expenses (entered=False, no invoice)
        unbilled_gross_fees, unbilled_comp_fees = aggregate_fees(
            TimeEntry.objects.filter(matter=self, entered=False, invoice__isnull=True)
        )
        unbilled_net_fees = unbilled_gross_fees - unbilled_comp_fees

        unbilled_gross_expenses, unbilled_comp_expenses = aggregate_expenses(
            ExpenseEntry.objects.filter(
                matter=self, entered=False, invoice__isnull=True
            )
        )
        unbilled_net_expenses = unbilled_gross_expenses - unbilled_comp_expenses

        unbilled_gross_flat_fees, unbilled_comp_flat_fees = aggregate_flat_fees(
            FlatFeeEntry.objects.filter(
                matter=self, entered=False, invoice__isnull=True
            )
        )
        unbilled_net_flat_fees = unbilled_gross_flat_fees - unbilled_comp_flat_fees

        unbilled = {
            "gross_fees": unbilled_gross_fees,
            "comp_fees": unbilled_comp_fees,
            "net_fees": unbilled_net_fees,
            "gross_expenses": unbilled_gross_expenses,
            "comp_expenses": unbilled_comp_expenses,
            "net_expenses": unbilled_net_expenses,
            "gross_flat_fees": unbilled_gross_flat_fees,
            "comp_flat_fees": unbilled_comp_flat_fees,
            "net_flat_fees": unbilled_net_flat_fees,
            "net_fees_and_expenses": (
                unbilled_net_fees + unbilled_net_expenses + unbilled_net_flat_fees
            ),
        }

        # Billed = total - unbilled
        billed = {key: total[key] - unbilled[key] for key in total.keys()}

        # Invoice totals - aggregate from time/expense/flat-fee entries on all invoices except DRAFT/APPROVED
        invoice_fees, invoice_comp_fees = aggregate_fees(
            TimeEntry.objects.filter(matter=self, invoice__isnull=False).exclude(
                invoice__status__in=["DRAFT", "APPROVED", "VOID", "UNCOLLECTIBLE"]
            )
        )
        invoice_expenses, invoice_comp_expenses = aggregate_expenses(
            ExpenseEntry.objects.filter(matter=self, invoice__isnull=False).exclude(
                invoice__status__in=["DRAFT", "APPROVED", "VOID", "UNCOLLECTIBLE"]
            )
        )
        invoice_flat_fees, invoice_comp_flat_fees = aggregate_flat_fees(
            FlatFeeEntry.objects.filter(matter=self, invoice__isnull=False).exclude(
                invoice__status__in=["DRAFT", "APPROVED", "VOID", "UNCOLLECTIBLE"]
            )
        )
        invoice_discount = (
            Invoice.objects.filter(matter=self)
            .exclude(status__in=["DRAFT", "APPROVED", "VOID", "UNCOLLECTIBLE"])
            .aggregate(total_discount=Sum("discount"))["total_discount"]
            or 0
        )

        billed_invoices = (
            (invoice_fees - invoice_comp_fees)
            + (invoice_expenses - invoice_comp_expenses)
            + (invoice_flat_fees - invoice_comp_flat_fees)
            - invoice_discount
        )

        payment_sum = (
            Payment.objects.filter(matter=self).aggregate(models.Sum("amount"))[
                "amount__sum"
            ]
            or 0
        )

        invoices = {
            "billed": billed_invoices,
            "payment_sum": payment_sum,
            "due": billed_invoices - payment_sum,
        }

        return {
            "total": total,
            "unbilled": unbilled,
            "billed": billed,
            "invoices": invoices,
        }


class PracticeArea(AuditMixin, models.Model):
    name = models.CharField(max_length=50)
    is_active = models.BooleanField(default=True)
    history = HistoricalRecords()

    def __str__(self):
        return self.name

    class Meta:
        db_table = "app_practice_area"
        ordering = ["name"]


class GroupQuerySet(models.QuerySet):
    def for_matter(self, matter):
        """Active groups available on a matter: the global (firm-wide) ones plus
        that matter's own groups, in display order."""
        return (
            self.filter(is_active=True)
            .filter(models.Q(matter__isnull=True) | models.Q(matter=matter))
            .order_by("order")
        )

    def client_group(self):
        """The protected firm-wide system Client group. A matter's client is
        mirrored into a Relationship in this group; it's the one stable reference
        (see is_system) that replaces name-string lookups."""
        return self.filter(is_system=True, name="Client", matter__isnull=True).first()


class Group(AuditMixin, models.Model):
    # Firm-wide (global) groups occupy the low order band (1, 2, 3, …); matter-
    # specific groups are numbered from this base up, so ordering by `order`
    # always sorts the firm groups first, then a matter's own groups.
    MATTER_GROUP_ORDER_BASE = 1000

    name = models.CharField(max_length=50)
    order = models.IntegerField(default=0)
    is_active = models.BooleanField(default=True)
    # Protected system row (the Client group): the matter-client mirror depends on
    # it, so Settings blocks renaming/deleting it.
    is_system = models.BooleanField(default=False)
    # Null → a global (firm-wide) group; set → a group scoped to one matter.
    matter = models.ForeignKey(
        Matter,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="groups",
    )
    history = HistoricalRecords()

    objects = GroupQuerySet.as_manager()

    def __str__(self):
        return self.name

    class Meta:
        db_table = "app_matter_group"
        ordering = ["order"]


class RoleQuerySet(models.QuerySet):
    def client_role(self):
        """The protected system Client role used for the matter-client mirror."""
        return self.filter(is_system=True, name="Client").first()


class Role(AuditMixin, models.Model):
    name = models.CharField(max_length=50)
    is_active = models.BooleanField(default=True)
    # Protected system row (the Client role): see Group.is_system.
    is_system = models.BooleanField(default=False)
    history = HistoricalRecords()

    objects = RoleQuerySet.as_manager()

    def __str__(self):
        return f"{self.name}"

    class Meta:
        db_table = "app_matter_role"


class Relationship(AuditMixin, models.Model):
    matter = models.ForeignKey(
        Matter,
        on_delete=models.CASCADE,
    )
    contact = models.ForeignKey(Contact, on_delete=models.CASCADE)
    role = models.ForeignKey(Role, on_delete=models.CASCADE)
    group = models.ForeignKey(Group, on_delete=models.CASCADE)
    history = HistoricalRecords()

    class Meta:
        db_table = "app_matter_relationship"

    def __str__(self):
        return f"matter: {self.matter.id}, contact: {self.contact.id}, role: {self.role.id}"
