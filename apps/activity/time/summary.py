def calculate_summary(entries):
    total_hours = 0
    total_fees = 0
    comp_hours = 0
    comp_fees = 0
    admin_hours = 0
    admin_fees = 0

    for entry in entries:
        total_hours += entry.hours
        total_fees += entry.hours * entry.rate

        if entry.comp == 1:
            comp_hours += entry.hours
            comp_fees += entry.hours * entry.rate

        if hasattr(entry, "matter") and entry.matter and not entry.matter.billable:
            admin_hours += entry.hours
            admin_fees += entry.hours * entry.rate

    net_hours = total_hours - comp_hours - admin_hours
    net_fees = total_fees - comp_fees - admin_fees

    summary = {
        "total_hours": total_hours,
        "total_fees": total_fees,
        "comp_hours": comp_hours,
        "comp_fees": comp_fees,
        "admin_hours": admin_hours,
        "admin_fees": admin_fees,
        "net_hours": net_hours,
        "net_fees": net_fees,
    }

    return summary
