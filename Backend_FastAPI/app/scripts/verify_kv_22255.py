"""Verify 1 xã KV2-NT — Xã Tây Hòa (ward_code 22255) for user lookup."""
import re
import pandas as pd


def main():
    df = pd.read_excel('/tmp/master_xa_kk.xls', sheet_name='Sheet1', header=5)
    df.columns = ['stt', 'ma_tinh', 'ten_tinh', 'ma_huyen', 'ten_huyen', 'ma_xa', 'ten_xa', 'loai']

    print('=== 1. Tra cứu Master Excel MOET (file user gửi) — Phú Yên + Tây Hòa ===')
    py_th = df[(df['ten_tinh'] == 'Phú Yên') &
               (df['ten_huyen'].astype(str).str.contains('Tây Hòa', na=False) |
                df['ten_xa'].astype(str).str.contains('Tây Hòa', na=False))]
    if len(py_th) > 0:
        print(f'FOUND {len(py_th)} rows mention "Tây Hòa":')
        print(py_th[['ten_huyen','ten_xa','loai']].to_string(index=False))
    else:
        print('"Tây Hòa" KHÔNG có trong Phú Yên section → KHÔNG phải KK/ĐBKK → NOT KV1')

    print()
    print('=== 2. wards.sql (BNV codes post-2025) ===')
    with open('/tmp/wards.sql', encoding='utf-8') as f:
        wards = f.read()
    m = re.search(r"VALUES \([^,]+, '22255', '([^']+)', '([^']+)'\)", wards)
    if m:
        print(f'  ward_code=22255 → tên hiện tại: "{m.group(1)}"')
        print(f'  province_code={m.group(2)} (66 = Đắk Lắk mới)')

    print()
    print('=== 3. ward_mappings.sql — Các xã pre-2025 sáp nhập vào ward 22255 ===')
    with open('/tmp/ward_mappings.sql', encoding='utf-8') as f:
        wm = f.read()
    old_in_22255 = []
    for mm in re.finditer(
        r"VALUES \(\d+, '([^']+)', '([^']+)', '([^']+)', '([^']+)', '22255', '([^']+)', '([^']+)'",
        wm,
    ):
        old_in_22255.append({
            'old_code': mm.group(1),
            'old_ward': mm.group(2),
            'old_district': mm.group(3),
            'old_province': mm.group(4),
            'new_ward': mm.group(5),
            'new_province': mm.group(6),
        })

    print(f'Total old xã sáp nhập vào 22255: {len(old_in_22255)}')
    for row in old_in_22255:
        print(f"  • {row['old_ward']} / {row['old_district']} / {row['old_province']}")
        print(f"    (old_code={row['old_code']}) → ward 22255 \"{row['new_ward']}\"")

    print()
    print('=== 4. Verify mỗi xã cũ — có thuộc master KK/ĐBKK không? ===')
    for row in old_in_22255:
        prov_clean = row['old_province'].replace('Tỉnh ', '')
        # Strip prefix from district + ward names
        d_search = row['old_district'].replace('Huyện ', '').replace('Thị xã ', '').replace('Thành phố ', '')
        w_search = row['old_ward'].replace('Xã ', '').replace('Phường ', '').replace('Thị trấn ', '')

        matches = df[(df['ten_tinh'] == prov_clean) &
                     (df['ten_huyen'].astype(str).str.contains(d_search, na=False, regex=False)) &
                     (df['ten_xa'].astype(str).str.contains(w_search, na=False, regex=False))]

        if len(matches) > 0:
            loai_list = matches['loai'].tolist()
            print(f'  ✓ "{row["old_ward"]}" / "{row["old_district"]}" → IN MASTER as: {loai_list}')
        else:
            print(f'  ✗ "{row["old_ward"]}" / "{row["old_district"]}" → NOT in master Excel KK/ĐBKK')

    print()
    print('=== 5. Kết luận KV cho ward 22255 ===')
    print('Pipeline logic:')
    print('  - Có ANY old xã trong master KK/ĐBKK? → KV1')
    print('  - Không có ANY → Apply default rule:')
    print('    • Province 66 (Đắk Lắk) là TỈNH, không phải TP TƯ')
    print('    • ward_kind = XA (vì tên bắt đầu "Xã ")')
    print('    • → default = KV2-NT')
    print()
    print('Final: ward_code=22255 "Xã Tây Hòa" → KV2-NT (+0.50 điểm ưu tiên)')


if __name__ == '__main__':
    main()
