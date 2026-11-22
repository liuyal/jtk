import argparse
import csv
import json
import os
import pathlib
import re
from datetime import datetime
from itertools import product

from pypdf import PdfReader

MONTHS = "Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec"
AMOUNT = r"-?[\d,]+\.\d{2}"
PERIOD_RE = re.compile(r"From (\w+ \d{1,2}, \d{4}) to (\w+ \d{1,2}, \d{4})")
OPENING_RE = re.compile(rf"Opening Balance\s+(\$?{AMOUNT})")
DATE_RE = re.compile(rf"^(\d{{1,2}}) ({MONTHS})\s+(.*)$")
TWO_RE = re.compile(rf"^(.*?)\s*({AMOUNT})\s+({AMOUNT})$")
ONE_RE = re.compile(rf"^(.*?\S)\s+({AMOUNT})$")
PAGE_NOISE_RE = re.compile(r"^(\d+ of \d+|Please check this Account Statement|Details of your account activity)")
MC_PERIOD_RE = re.compile(rf"STATEMENT FROM ({MONTHS.upper()}) \d{{1,2}}(?:, \d{{4}})? TO ({MONTHS.upper()}) \d{{1,2}}, (\d{{4}})")
MC_PREV_RE = re.compile(r"PREVIOUS ACCOUNT BALANCE\s+(-?\$?[\d,]+\.\d{2})", re.I)
MC_HEADER_RE = re.compile(r"^(TRANSACTION POSTING ACTIVITY|DATE ACTIVITY DESCRIPTION)")
MC_TXN_RE = re.compile(rf"^({MONTHS.upper()}) (\d{{1,2}}) ({MONTHS.upper()}) (\d{{1,2}}) (.*)$")
MC_AMOUNT_RE = re.compile(r"^-?\$[\d,]+\.\d{2}$")
MC_REF_RE = re.compile(r"^\d{15,}$")
MC_NOISE_RE = re.compile(r"^(\d+ OF \d+$|STATEMENT FROM|RBC.{0,3} .*Mastercard|\d{4} \d{2}\*\* |.* - (PRIMARY|AUTHORIZED))")


def money(s):
    return float(s.replace("$", "").replace(",", ""))


def read_text(path):
    reader = PdfReader(path)
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def resolve_group(group, balance, new_balance):
    """Pick deposit/withdrawal for same-day rows so they add up to the balance change."""
    target = round(new_balance - balance, 2)
    for signs in product((1, -1), repeat=len(group)):
        if round(sum(s * r["amount"] for s, r in zip(signs, group)), 2) == target:
            break
    else:
        signs = [1 if target >= 0 else -1] * len(group)

    running = balance
    for s, r in zip(signs, group):
        amount = r.pop("amount")
        running = round(running + s * amount, 2)
        r["withdrawal"] = amount if s < 0 else None
        r["deposit"] = amount if s > 0 else None
        r["balance"] = running


def parse_activity(text):
    """Return the 'Details of your account activity' rows as a list of dicts."""

    period = PERIOD_RE.search(text)
    if not period:
        return None
    start = datetime.strptime(period.group(1), "%B %d, %Y")
    end = datetime.strptime(period.group(2), "%B %d, %Y")

    rows = []
    group = []  # rows seen since the last printed balance
    balance = None
    date = None
    in_table = False
    noise = False

    # inside page header/footer text between table pages
    for line in text.splitlines():
        line = line.strip()
        if PAGE_NOISE_RE.match(line):
            noise = True
            continue
        if line.startswith("Opening Balance"):
            balance = money(OPENING_RE.match(line).group(1))
            in_table = True
            continue
        if line.startswith("Closing Balance"):
            in_table = False
            continue
        if not in_table:
            continue

        m = DATE_RE.match(line)
        if m:
            day, mon, line = int(m.group(1)), m.group(2), m.group(3)
            month = datetime.strptime(mon, "%b").month
            # statement may span a year boundary (Dec -> Jan)
            date = datetime(start.year if month >= start.month else end.year, month, day).date()

        if m:
            noise = False
        two = TWO_RE.match(line)
        one = ONE_RE.match(line)
        if two or one:
            noise = False
            t = two or one
            row = {"date": date, "description": t.group(1).strip(), "amount": money(t.group(2))}
            rows.append(row)
            group.append(row)
            if two:
                new_balance = money(two.group(3))
                resolve_group(group, balance, new_balance)
                balance = new_balance
                group = []
        elif rows and line and not noise:
            # description wrapped onto another line
            rows[-1]["description"] += " " + line

    return rows


def parse_mastercard(text):
    """Return credit card statement rows as a list of dicts (None if not a card statement)."""
    period = MC_PERIOD_RE.search(text)
    if not period:
        return None

    end_year = int(period.group(3))
    end_month = datetime.strptime(period.group(2), "%b").month
    prev = MC_PREV_RE.search(text)
    balance = money(prev.group(1)) if prev else 0.0

    rows = []
    in_table = False
    for line in text.splitlines():
        line = line.strip()
        if MC_HEADER_RE.match(line):
            in_table = True
            continue
        if line.startswith(("TOTAL ACCOUNT BALANCE", "CREDIT BALANCE")):
            in_table = False
            continue
        if not in_table or not line or MC_NOISE_RE.match(line):
            continue

        m = MC_TXN_RE.match(line)
        if m:
            month = datetime.strptime(m.group(1), "%b").month
            # statement may span a year boundary (Dec -> Jan)
            year = end_year - 1 if month > end_month else end_year
            date = datetime(year, month, int(m.group(2))).date()
            rows.append({"date": date, "description": m.group(5).strip(),
                         "withdrawal": None, "deposit": None, "balance": None})
        elif MC_AMOUNT_RE.match(line) and rows and rows[-1]["balance"] is None:
            amount = money(line)
            balance = round(balance + amount, 2)
            row = rows[-1]
            row["withdrawal"] = amount if amount > 0 else None
            row["deposit"] = -amount if amount < 0 else None
            row["balance"] = balance
        elif rows and rows[-1]["balance"] is None and not MC_REF_RE.match(line):
            # description wrapped onto another line (e.g. foreign currency details)
            rows[-1]["description"] += " " + line
    return [r for r in rows if r["balance"] is not None]


def parse_statement(text):
    """Pick the parser that matches the statement layout."""
    if MC_PERIOD_RE.search(text):
        return parse_mastercard(text)
    return parse_activity(text)


def load_pdfs(root):
    """Walk root recursively and return {pdf_path: extracted_text}."""
    texts = {}
    for dirpath, _, filenames in os.walk(root):
        for name in sorted(filenames):
            if not name.lower().endswith(".pdf"):
                continue
            path = os.path.join(str(dirpath), str(name))
            try:
                texts[path] = read_text(path)
            except Exception as e:
                print(f"Failed to read {path}: {e}")
    return texts


def save_transactions(pdf_folders,
                      output_folder):
    """Save transactions to JSON and CSV files."""

    transactions = {}

    for path, text in load_pdfs(pdf_folders).items():
        rows = parse_statement(text)
        if rows is None:
            print(f"Skipped {path}: no 'From <date> to <date>' statement period found")
            continue
        print(f"{os.path.basename(path)}: {len(rows)} transactions")
        for r in rows:
            print(r)
            if str(r["date"]) not in transactions:
                transactions[str(r["date"])] = []
            transactions[str(r["date"])].append(r)

    with open(output_folder / "transactions.json", "w") as f:
        json.dump(transactions, f, default=str)

    by_year = {}
    for day in sorted(transactions):
        by_year.setdefault(day[:4], []).extend(transactions[day])

    fields = ["date", "description", "withdrawal", "deposit", "balance"]
    for year, rows in by_year.items():
        with open(output_folder / f"transactions_{year}.csv", "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)

        print(f"transactions_{year}.csv: {len(rows)} rows")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--folder",
                        required=True,
                        help="Base folder containing the statement type subfolders")
    args = parser.parse_args()

    statement_types = ["Savings", "Chequing", "MasterCard"]
    for statement_type in statement_types:
        pdf_folder = rf"{args.folder}\{statement_type}"
        output_folder = pathlib.Path(f"statements/{statement_type}")
        output_folder.mkdir(exist_ok=True, parents=True)
        save_transactions(pdf_folder, output_folder)
