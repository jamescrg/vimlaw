def calculate_summary(entries, expense_entries):
    total_hours = 0
    total_fees = 0
    comp_hours = 0
    comp_fees = 0
    total_expenses = 0

    for entry in entries:
        total_hours += entry.hours
        total_fees += entry.hours * entry.rate

        if entry.comp == 1:
            comp_hours += entry.hours
            comp_fees += comp_fees + (entry.hours * entry.rate)

    for entry in expense_entries:
        total_expenses += entry.amount

    payable_hours = total_hours - comp_hours
    payable_fees = total_fees - comp_fees

    summary = {
        "total_hours": total_hours,
        "total_fees": total_fees,
        "comp_hours": comp_hours,
        "comp_fees": comp_fees,
        "payable_hours": payable_hours,
        "payable_fees": payable_fees,
        "total_expenses": total_expenses,
    }

    return summary
