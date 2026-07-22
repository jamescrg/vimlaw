from django.db import models
from simple_history.models import HistoricalRecords

from apps.accounts.models import CustomUser
from apps.folders.models import Folder
from apps.intakes.models import Intake
from utils.models import AuditMixin


def derive_client_status(statuses, has_intake=False):
    """Single source of truth for a contact's client status, derived from their
    matters' statuses (+ a linked intake, which marks a no-matter prospect as
    Pending). Never stored — see Contact.client_status."""
    statuses = set(statuses)
    if statuses & {"Open", "Complete"}:
        return "Current"
    if "Pending" in statuses:
        return "Pending"
    if statuses:
        return "Former"  # has matters, all Closed
    return "Pending" if has_intake else "Nonclient"  # no matters


class ContactQuerySet(models.QuerySet):
    """DB-level filters mirroring derive_client_status, so the client
    dropdowns/reports can select by derived status without a stored field."""

    def _with_status_flags(self):
        # Lazy import: apps.matters.models imports Contact, so importing Matter at
        # module load would be circular.
        from apps.matters.models import Matter

        matters = Matter.objects.filter(client=models.OuterRef("pk"))
        return self.annotate(
            _has_active=models.Exists(matters.filter(status__in=["Open", "Complete"])),
            _has_pending=models.Exists(matters.filter(status="Pending")),
            _has_matter=models.Exists(matters),
        )

    def current_clients(self):
        return self._with_status_flags().filter(_has_active=True)

    def pending_clients(self):
        return self._with_status_flags().filter(
            models.Q(_has_pending=True, _has_active=False)
            | models.Q(_has_matter=False, intake__isnull=False)
        )

    def former_clients(self):
        return self._with_status_flags().filter(
            _has_matter=True, _has_active=False, _has_pending=False
        )

    def nonclients(self):
        return self._with_status_flags().filter(_has_matter=False, intake__isnull=True)

    def active_or_pending_clients(self):
        return self._with_status_flags().filter(
            models.Q(_has_active=True)
            | models.Q(_has_pending=True)
            | models.Q(_has_matter=False, intake__isnull=False)
        )

    def by_client_status(self, value):
        """Dispatch a status string (from the sidebar session) to its filter."""
        return {
            "Current": self.current_clients,
            "Pending": self.pending_clients,
            "Former": self.former_clients,
            "Nonclient": self.nonclients,
        }.get(value, lambda: self)()


class Contact(AuditMixin, models.Model):
    id = models.BigAutoField(primary_key=True)
    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE)
    folder = models.ForeignKey(Folder, on_delete=models.SET_NULL, blank=True, null=True)
    name = models.CharField(max_length=100)
    company = models.CharField(max_length=100, blank=True, null=True)
    address = models.CharField(max_length=255, blank=True, null=True)
    phone1 = models.CharField(max_length=50, blank=True, null=True)
    phone1_label = models.CharField(max_length=10, blank=True, null=True)
    phone2 = models.CharField(max_length=50, blank=True, null=True)
    phone2_label = models.CharField(max_length=10, blank=True, null=True)
    phone3 = models.CharField(max_length=50, blank=True, null=True)
    phone3_label = models.CharField(max_length=10, blank=True, null=True)
    email = models.EmailField(max_length=100, blank=True, null=True)
    email2 = models.EmailField(max_length=100, blank=True, null=True)
    website = models.CharField(max_length=255, blank=True, null=True)
    map = models.CharField(max_length=255, blank=True, null=True)
    notes = models.CharField(max_length=255, blank=True, null=True)
    google_id = models.CharField(max_length=255, blank=True, null=True)
    intake = models.ForeignKey(Intake, on_delete=models.SET_NULL, null=True)
    history = HistoricalRecords()

    objects = ContactQuerySet.as_manager()

    def __str__(self):
        return f"{self.name}"

    @property
    def client_status(self):
        """Derived from the contact's matters (+ intake); never stored."""
        return derive_client_status(
            self.client_matters.values_list("status", flat=True),
            has_intake=self.intake_id is not None,
        )

    class Meta:
        db_table = "app_contact"
        indexes = [
            models.Index(fields=["user"]),
            models.Index(fields=["folder"]),
        ]


class RelationshipType(models.Model):
    """A named contact-to-contact relationship, phrased from both ends.

    One row describes both directions of a link: `label` is the phrase for
    the edge's from-side ("Employer of"), `inverse_label` for its to-side
    ("Employee of"). A blank inverse marks a symmetric relationship
    (Spouse of) — both ends read the same. Managed in Settings > Contacts.
    """

    id = models.BigAutoField(primary_key=True)
    label = models.CharField(max_length=50, unique=True)
    inverse_label = models.CharField(max_length=50, blank=True)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.label

    @property
    def is_symmetric(self):
        return not self.inverse_label or self.inverse_label == self.label

    @property
    def display_inverse(self):
        return self.inverse_label or self.label

    class Meta:
        db_table = "app_contact_relationship_type"
        ordering = ["label"]


class ContactRelationship(AuditMixin, models.Model):
    """A directed edge between two contacts, typed by RelationshipType.

    Stored once per link: "from_contact <label> to_contact". The far side
    renders the type's inverse label, so each contact's page reads the
    same edge in its own words. (Distinct from matters.Relationship, the
    contact-to-matter through model.)
    """

    id = models.BigAutoField(primary_key=True)
    from_contact = models.ForeignKey(
        Contact, on_delete=models.CASCADE, related_name="relationships_from"
    )
    to_contact = models.ForeignKey(
        Contact, on_delete=models.CASCADE, related_name="relationships_to"
    )
    relationship_type = models.ForeignKey(
        RelationshipType, on_delete=models.CASCADE, related_name="relationships"
    )
    notes = models.CharField(max_length=255, blank=True, null=True)
    history = HistoricalRecords()

    def __str__(self):
        return f"{self.from_contact} {self.relationship_type.label} {self.to_contact}"

    class Meta:
        db_table = "app_contact_relationship"
        constraints = [
            models.UniqueConstraint(
                fields=["from_contact", "to_contact", "relationship_type"],
                name="uniq_contact_relationship_edge",
            ),
            models.CheckConstraint(
                check=~models.Q(from_contact=models.F("to_contact")),
                name="no_self_contact_relationship",
            ),
        ]
        indexes = [
            models.Index(fields=["from_contact"]),
            models.Index(fields=["to_contact"]),
        ]
