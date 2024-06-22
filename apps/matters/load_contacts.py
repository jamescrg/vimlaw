from apps.matters.models import Relationship


def load_contacts(matter):
    relationship_groups = {}

    relationship_groups["Client"] = Relationship.objects.filter(
        matter=matter, role__name__icontains="Client"
    )

    relationship_groups["Adversary"] = Relationship.objects.filter(
        matter=matter, role__name__icontains="Adversary"
    )

    relationship_groups["Court"] = Relationship.objects.filter(
        matter=matter, role__name__icontains="Court"
    )

    relationship_groups["Other"] = (
        Relationship.objects.filter(matter=matter)
        .exclude(role__name__icontains="Client")
        .exclude(role__name__icontains="Adversary")
        .exclude(role__name__icontains="Court")
    )

    return relationship_groups
