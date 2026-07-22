from django import forms
from django.db.models import Q

from apps.contacts.models import Contact, ContactRelationship, RelationshipType
from config.settings import CustomFormRendererCompact


def type_direction_choices():
    """Every phrasing of every active type as a flat choice list.

    An asymmetric type contributes BOTH of its labels — "Employer of" and
    "Employee of" — so the user only ever picks the phrase that is true
    from the current contact's perspective; the value encodes type and
    orientation as "<id>:f" (current contact is the from-side) or "<id>:r"
    (current contact is the to-side).
    """
    choices = []
    for t in RelationshipType.objects.filter(is_active=True):
        choices.append((f"{t.id}:f", t.label))
        if not t.is_symmetric:
            choices.append((f"{t.id}:r", t.inverse_label))
    choices.sort(key=lambda c: c[1].lower())
    return choices


class ContactRelationshipForm(forms.Form):
    """Add/edit a link from the current contact's perspective.

    A plain Form rather than a ModelForm: orientation isn't a model field,
    and the edge's from/to assignment depends on the phrasing chosen.
    """

    type_direction = forms.ChoiceField(label="Relationship")
    other_contact = forms.ModelChoiceField(
        label="Contact", queryset=Contact.objects.order_by("name")
    )
    notes = forms.CharField(label="Notes", max_length=255, required=False)

    def __init__(self, *args, contact, instance=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.renderer = CustomFormRendererCompact()
        self.contact = contact
        self.instance = instance
        self.fields["type_direction"].choices = type_direction_choices()
        if instance and not self.is_bound:
            outbound = instance.from_contact_id == contact.id
            self.initial["type_direction"] = (
                f"{instance.relationship_type_id}:{'f' if outbound else 'r'}"
            )
            self.initial["other_contact"] = (
                instance.to_contact if outbound else instance.from_contact
            )
            self.initial["notes"] = instance.notes

    def _parse(self):
        type_id, _, orientation = self.cleaned_data["type_direction"].partition(":")
        return int(type_id), orientation

    def clean(self):
        cleaned = super().clean()
        other = cleaned.get("other_contact")
        if other and other.id == self.contact.id:
            self.add_error("other_contact", "A contact can't be related to itself.")
        if other and cleaned.get("type_direction"):
            type_id, _ = self._parse()
            # A duplicate in EITHER orientation is the same link (symmetric
            # types can be stored either way round); the DB constraint only
            # backstops the exact-orientation case.
            existing = ContactRelationship.objects.filter(
                Q(from_contact=self.contact, to_contact=other)
                | Q(from_contact=other, to_contact=self.contact),
                relationship_type_id=type_id,
            )
            if self.instance:
                existing = existing.exclude(pk=self.instance.pk)
            if existing.exists():
                self.add_error(None, "These contacts already have this relationship.")
        return cleaned

    def save(self):
        type_id, orientation = self._parse()
        other = self.cleaned_data["other_contact"]
        from_contact, to_contact = (
            (self.contact, other) if orientation == "f" else (other, self.contact)
        )
        rel = self.instance or ContactRelationship()
        rel.from_contact = from_contact
        rel.to_contact = to_contact
        rel.relationship_type_id = type_id
        rel.notes = self.cleaned_data["notes"] or None
        rel.save()
        return rel
