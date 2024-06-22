def calculate_summary(entries, expense_entries):
    total_hours = 0
    total_fees = 0
    comp_hours = 0
    comp_fees = 0
    total_contractor_fees = 0
    comp_contractor_fees = 0
    total_expenses = 0

    for entry in entries:
        total_hours += entry.hours
        total_fees += entry.hours * entry.firm_rate
        if entry.contractor_rate:
            total_contractor_fees += entry.hours * entry.contractor_rate

        if entry.comp == 1:
            comp_hours += entry.hours
            comp_fees += comp_fees + (entry.hours * entry.firm_rate)
            if entry.contractor_rate:
                comp_contractor_fees += comp_fees + (
                    entry.hours * entry.contractor_rate
                )

    for entry in expense_entries:
        total_expenses += entry.amount

    payable_hours = total_hours - comp_hours
    payable_fees = total_fees - comp_fees
    payable_contractor_fees = total_contractor_fees - comp_contractor_fees

    summary = {}
    summary["total_hours"] = total_hours
    summary["total_fees"] = total_fees
    summary["comp_hours"] = comp_hours
    summary["comp_fees"] = comp_fees
    summary["payable_hours"] = payable_hours
    summary["payable_fees"] = payable_fees
    summary["total_contractor_fees"] = total_contractor_fees
    summary["comp_contractor_fees"] = comp_contractor_fees
    summary["payable_contractor_fees"] = payable_contractor_fees
    summary["total_expenses"] = total_expenses

    return summary
