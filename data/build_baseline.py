import pandas as pd
import json

print("Loading CalCOFI data...")
df = pd.read_csv("data/calcofi/CalCOFI_Database_194903-202105_csv_16October2023/194903-202105_Bottle.csv", 
                 low_memory=False, encoding='latin-1')

df = df[df["Depthm"] < 200]
df = df.dropna(subset=["T_degC"])

temp_mean = round(df["T_degC"].mean(), 2)
temp_std  = round(df["T_degC"].std(), 2)

print(f"Overall: {temp_mean} ± {temp_std}°C from {len(df)} samples")

baseline = {}
for month in range(1, 13):
    baseline[month] = {
        "temp_mean": temp_mean,
        "temp_std":  temp_std,
        "dist_mean": 100,
        "dist_std":  10
    }

with open("data/baselines.json", "w") as f:
    json.dump(baseline, f, indent=2)

print("Done! baselines.json saved.")