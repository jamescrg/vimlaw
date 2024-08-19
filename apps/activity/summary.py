def calculate_summary(entries, expense_entries):
    total_hours = 0
    total_fees = 0
    comp_hours = 0
    comp_fees = 0
    total_expenses = 0
    comp_expenses = 0
    net_expenses = 0

    for entry in entries:
        total_hours += entry.hours
        total_fees += entry.hours * entry.rate

        if entry.comp == 1:
            comp_hours += entry.hours
            comp_fees += entry.hours * entry.rate

    for entry in expense_entries:
        total_expenses += entry.amount

        if entry.comp == 1:
            comp_expenses += entry.amount

    net_hours = total_hours - comp_hours
    net_fees = total_fees - comp_fees

    net_expenses = total_expenses - comp_expenses

    summary = {
        "total_hours": total_hours,
        "total_fees": total_fees,
        "comp_hours": comp_hours,
        "comp_fees": comp_fees,
        "net_hours": net_hours,
        "net_fees": net_fees,
        "total_expenses": total_expenses,
        "comp_expenses": comp_expenses,
        "net_expenses": net_expenses,
    }

    return summary
