import pandas as pd

URL = "https://images.dhan.co/api-data/api-scrip-master-detailed.csv"
OUTPUT = "sensex_matches.csv"

print("Downloading Dhan instrument master...")

df = pd.read_csv(URL, low_memory=False)

print(f"Loaded {len(df):,} instruments")

# Search only rows containing SENSEX anywhere in the row
mask = df.astype(str).apply(
    lambda row: row.str.contains("SENSEX", case=False, na=False).any(),
    axis=1
)

matches = df[mask].copy()

print(f"Found {len(matches):,} SENSEX-related rows")

# Keep useful columns if they exist
preferred_columns = [
    "SECURITY_ID",
    "EXCH_ID",
    "SEGMENT",
    "INSTRUMENT",
    "SYMBOL_NAME",
    "DISPLAY_NAME",
    "UNDERLYING_SYMBOL",
    "UNDERLYING_SECURITY_ID",
    "EXPIRY_DATE",
    "STRIKE_PRICE",
    "OPTION_TYPE",
    "LOT_SIZE",
    "TICK_SIZE"
]

available_columns = [
    col for col in preferred_columns
    if col in matches.columns
]

# If some expected column names differ, keep all columns as a fallback
if available_columns:
    matches = matches[available_columns]

matches.to_csv(OUTPUT, index=False)

print(f"\nSaved file: {OUTPUT}")
print(f"Rows: {len(matches)}")
print(f"Columns: {len(matches.columns)}")
print("\nYou can now upload this file here.")