import csv


def write_clio_csv(entries, response):
    entries = entries.exclude(matter__clio_matter_id__isnull=True)
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
    for entry in entries:
        clio_user = f"{entry.user.first_name} {entry.user.last_name}"
        writer.writerow(
            [
                entry.matter.clio_matter_id,
                entry.date.strftime("%m/%d/%Y"),
                "",
                entry.actions,
                entry.rate,
                entry.hours,
                "TimeEntry",
                clio_user,
                entry.comp,
            ]
        )
    return response


def write_standard_csv(entries, response):
    writer = csv.writer(response)
    writer.writerow(
        [
            "Date",
            "Matter",
            "User",
            "Actions",
            "Hours",
            "Rate",
            "Fee",
            "Comp",
            "Discounted Fee",
            "Entered",
            "Invoice",
        ]
    )
    for entry in entries:
        writer.writerow(
            [
                entry.date.strftime("%m/%d/%Y"),
                entry.matter.name,
                entry.user.symbol,
                entry.actions,
                entry.hours,
                entry.rate,
                entry.fee,
                entry.comp,
                entry.discounted_fee,
                entry.entered,
                entry.invoice,
            ]
        )
    return response
