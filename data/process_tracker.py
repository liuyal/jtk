import pathlib

import pandas as pd

sheet_id = "1qcspy9EQAGwQDfUGo77IfbkKo8W2R-WHSDuZZhTwaW0"
sheet_name = "2026"
url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/gviz/tq?tqx=out:csv&sheet={sheet_name}"

# Load directly into a DataFrame
df = pd.read_csv(url, iterator=False, chunksize=None)

# Optional: Save to a local CSV file
output_path = pathlib.Path(__file__).parent / "output"
output_path.mkdir(parents=True, exist_ok=True)
df.to_csv(output_path / "downloaded_data.csv", index=False)
