import csv


def write_clio_csv(entries, response):
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

        clio_user = ""

        if entry.user.symbol == "JC":
            clio_user = "James Craig"

        if entry.user.symbol == "LK":
            clio_user = "Lexi Krier"

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
    pass
    return response
