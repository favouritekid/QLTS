import pandas as pd
import sys

try:
    df = pd.read_excel("Import_Thong_Tin_Hoc_Vien_Data_1767431894263.xlsx")
    print("COLUMNS:", df.columns.tolist())
except Exception as e:
    print("ERROR:", e)
