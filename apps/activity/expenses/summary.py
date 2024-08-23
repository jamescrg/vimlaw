def calculate_summary(expenses):
    total_expenses = 0
    comp_expenses = 0

    for entry in expenses:
        total_expenses += entry.amount

        if entry.comp == 1:
            comp_expenses += entry.amount

    net_expenses = total_expenses - comp_expenses

    summary = {
        "total_expenses": total_expenses,
        "comp_expenses": comp_expenses,
        "net_expenses": net_expenses,
    }

    return summary
