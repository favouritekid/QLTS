#!/usr/bin/env python3
"""Tối ưu asset "Giấy báo nhập học" — CHẠY MỖI KHI THAY ẢNH letterhead.

Ba ảnh trong ``app/assets/letters/`` được nhúng LẠI vào TỪNG bản PDF phát ra,
nên dung lượng của chúng nhân lên theo số giấy đã phát × thời gian lưu trữ.
Ảnh gốc user gửi là PNG 24-bit ~363 KB ⇒ mỗi giấy 540 KB, trong đó 67% chỉ là
ba tấm ảnh giống hệt nhau.

CÁCH TIẾT KIỆM ĐÚNG cho loại ảnh này là GIẢM SỐ MÀU, không phải giảm độ phân
giải: letterhead là đồ hoạ phẳng (đỏ/xanh/trắng + viền anti-alias), nên hạ
xuống vài chục màu làm entropy sụp và Flate của ReportLab nén tốt hơn hẳn —
trong khi kích thước pixel (tức ĐỘ NÉT KHI IN) không đổi một chút nào.

Đo thực tế trên bộ ảnh 19-07 (in A4, header 305 DPI):
    giữ nguyên            363 KB asset → 540 KB/giấy
    giảm còn 250 DPI      295 KB       → 434 KB   (−20%, MẤT nét)
    giảm còn 200 DPI      211 KB       → 312 KB   (−42%, MẤT nét)
    quantize 64/32/32     279 KB       → 247 KB   (−54%, GIỮ nét)  ← chọn
    quantize 16 đồng loạt 151 KB       → 175 KB   (−68%, logo bắt đầu vỡ)

Số màu chọn theo ngưỡng RMSE < 2.0 so với bản gốc (dưới mức mắt thường phân
biệt được). Script tự dò mức thấp nhất đạt ngưỡng, nên khi thay ảnh mới nó
tự chọn lại — đừng hard-code số màu.

Dùng:
    docker compose exec backend python scripts/optimize_letter_assets.py
    docker compose exec backend python scripts/optimize_letter_assets.py --dry-run
"""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageChops, ImageStat

ASSET_DIR = Path(__file__).resolve().parent.parent / "app" / "assets" / "letters"
ASSETS = ("header.png", "footer.png", "signature.png")
CANDIDATE_COLORS = (8, 16, 32, 64, 128, 256)
RMSE_THRESHOLD = 2.0


def rmse(a: Image.Image, b: Image.Image) -> float:
    """Sai lệch trung bình bình phương giữa hai ảnh (0 = giống hệt)."""
    diff = ImageChops.difference(a.convert("RGB"), b.convert("RGB"))
    return (sum(v**2 for v in ImageStat.Stat(diff).rms) / 3) ** 0.5


def optimize(path: Path, dry_run: bool = False) -> tuple[int, int, int, float]:
    """Trả về (bytes_trước, bytes_sau, số_màu_đã_chọn, rmse)."""
    original = Image.open(path).convert("RGB")
    before = path.stat().st_size

    for colors in CANDIDATE_COLORS:
        # quantize rồi convert LẠI sang RGB: ta muốn giảm entropy chứ không
        # đổi sang palette mode (ReportLab sẽ tự bung palette ra RGB khi nhúng,
        # nên lưu indexed không giúp gì thêm).
        candidate = original.quantize(
            colors=colors, method=Image.MEDIANCUT
        ).convert("RGB")
        error = rmse(original, candidate)
        if error < RMSE_THRESHOLD:
            if not dry_run:
                candidate.save(path, optimize=True)
            after = path.stat().st_size if not dry_run else before
            return before, after, colors, error

    return before, before, 0, 0.0  # không mức nào đạt ngưỡng → giữ nguyên


def main() -> int:
    dry_run = "--dry-run" in sys.argv
    if not ASSET_DIR.is_dir():
        print(f"Không thấy thư mục asset: {ASSET_DIR}", file=sys.stderr)
        return 1

    total_before = total_after = 0
    print(f"{'asset':<16} {'trước':>9} {'sau':>9} {'màu':>5} {'RMSE':>6}")
    print("-" * 50)
    for name in ASSETS:
        path = ASSET_DIR / name
        if not path.is_file():
            print(f"{name:<16} (thiếu — bỏ qua)")
            continue
        before, after, colors, error = optimize(path, dry_run)
        total_before += before
        total_after += after
        note = "giữ nguyên" if not colors else f"{colors:>5} {error:>6.2f}"
        print(f"{name:<16} {before/1024:>8.0f}K {after/1024:>8.0f}K {note}")

    saved = total_before - total_after
    pct = (saved / total_before * 100) if total_before else 0
    print("-" * 50)
    print(
        f"{'TỔNG':<16} {total_before/1024:>8.0f}K {total_after/1024:>8.0f}K"
        f"   tiết kiệm {saved/1024:.0f}K ({pct:.0f}%)"
    )
    if dry_run:
        print("\n(--dry-run: chưa ghi đè file nào)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
