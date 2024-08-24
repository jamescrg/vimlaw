from apps.matters.models import Relationship


def load_contacts(matter):
    relationship_groups = {
        "Client": Relationship.objects.filter(
            matter=matter, role__name__icontains="Client"
        ),
        "Adversary": Relationship.objects.filter(
            matter=matter, role__name__icontains="Adversary"
        ),
        "Court": Relationship.objects.filter(
            matter=matter, role__name__icontains="Court"
        ),
        "Other": (
            Relationship.objects.filter(matter=matter)
            .exclude(role__name__icontains="Client")
            .exclude(role__name__icontains="Adversary")
            .exclude(role__name__icontains="Court")
        ),
    }

    return relationship_groups
