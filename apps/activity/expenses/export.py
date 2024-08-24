import csv


def write_clio_csv(expenses, response):
    expenses = expenses.exclude(matter__clio_matter_id__isnull=True)
    writer = csv.writer(response)
    writer.writerow(
        [
            "matter",
            "date",
            "activity_description",
            "note",
            "price",
            "quantity",
            "type",
            "activity_user",
            "non-billable",
        ]
    )
    for expense in expenses:
        clio_user = f"{expense.user.first_name} {expense.user.last_name}"
        writer.writerow(
            [
                expense.matter.clio_matter_id,
                expense.date.strftime("%m/%d/%Y"),
                "",
                expense.slug,
                expense.amount,
                "1",
                "ExpenseEntry",
                clio_user,
                expense.comp,
            ]
        )
    return response


def write_standard_csv(expenses, response):
    writer = csv.writer(response)
    writer.writerow(
        [
            "Date",
            "Matter",
            "User",
            "Description",
            "Amount",
            "Comp",
            "Discounted Amount",
            "Entered",
            "Invoice",
        ]
    )
    for expense in expenses:
        writer.writerow(
            [
                expense.date.strftime("%m/%d/%Y"),
                expense.matter.name,
                expense.user.symbol,
                expense.slug,
                expense.amount,
                expense.comp,
                expense.discounted_amount,
                expense.entered,
                expense.invoice,
            ]
        )
    return response
