"""Timekeeper legend shared by the matter PDF reports."""


def build_timekeepers(matter, time_entries):
    """Legend rows for everyone whose initials appear in the listings, with
    their rate on this matter (matter rate, else the user's default)."""
    from apps.matters.rates.models import Rate

    matter_rates = {
        rate.user_id: rate.matter_rate for rate in Rate.objects.filter(matter=matter)
    }
    seen = {}
    for entry in time_entries:
        if entry.user_id and entry.user_id not in seen:
            seen[entry.user_id] = {
                "user": entry.user,
                "rate": matter_rates.get(entry.user_id, entry.user.user_rate),
            }
    return sorted(
        seen.values(), key=lambda t: (t["user"].initials or "", t["user"].username)
    )
