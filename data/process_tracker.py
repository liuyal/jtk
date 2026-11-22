
import pandas as pd


sheet_id = "1qcspy9EQAGwQDfUGo77IfbkKo8W2R-WHSDuZZhTwaW0"
sheet_name = "2026"
url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/gviz/tq?tqx=out:csv&sheet={sheet_name}"

# Load directly into a DataFrame
df = pd.read_csv(url)
print(df.head())

# Optional: Save to a local CSV file
df.to_csv("downloaded_data.csv", index=False)
