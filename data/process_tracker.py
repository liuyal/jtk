import csv
import datetime
import pathlib
import re

import pandas as pd

DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}$")
sheet_id = "1qcspy9EQAGwQDfUGo77IfbkKo8W2R-WHSDuZZhTwaW0"
sheet_name = "2026"

# headers=0 stops Google from dropping cells that don't match the inferred column type
url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/gviz/tq?tqx=out:csv&sheet={sheet_name}&headers=0"
df = pd.read_csv(url, header=None, dtype=str, keep_default_na=False)

# Optional: Save to a local CSV file
output_path = pathlib.Path(__file__).parent / "output"
output_path.mkdir(parents=True, exist_ok=True)
csv_path = output_path / "downloaded_data.csv"
df.to_csv(csv_path, index=False, header=False)


def load_entries(path):
    """ Every date up to today gets an entry;
        days without a value are type "None", distance 0.
    """

    with open(path, newline="", encoding="utf-8") as f:
        # skip header row
        rows = list(csv.reader(f))[1:]

    def is_date_row(row):
        return any(DATE_RE.match(c.strip()) for c in row[:7])

    def cells(row):
        # drop "Unnamed" columns, pad short rows
        return (row + [""] * 7)[:7]

    today = datetime.date.today().isoformat()
    entries = []
    for i, row in enumerate(rows):
        if not is_date_row(row):
            continue

        # future weeks have no type/distance rows
        has_values = i + 2 < len(rows) and not is_date_row(rows[i + 1])
        event = cells(rows[i + 1]) if has_values else [""] * 7
        types = cells(rows[i + 2]) if has_values else [""] * 7
        distances = cells(rows[i + 3]) if has_values else [""] * 7

        for date, event, kind, distance in zip(cells(row), event, types, distances):
            date, event, kind = date.strip(), event.strip(), kind.strip()
            if not DATE_RE.match(date) or date > today:
                continue

            try:
                distance = float(distance)

            except ValueError:
                distance = 0

            if kind and len(kind) < 1:
                kind, distance = None, 0.0

            entries.append(
                {
                    "date": date,
                    "type": kind,
                    "event": event,
                    "distance": distance
                }
            )

    return entries


rows = load_entries(csv_path)

[print(i) for i in rows]
print(len(rows))

run_total = sum([i.get("distance", 0) for i in rows if i.get("type", "") != "BIKE"])
print(run_total)

bike_total = sum([i.get("distance", 0) for i in rows if i.get("type", "") == "BIKE"])
print(bike_total)
