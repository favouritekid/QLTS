/**
 * Render một "thẻ VietQR" đầy đủ thông tin (canvas → PNG) để officer chia sẻ
 * cho học viên / phụ huynh.
 *
 * Vì sao TỰ vẽ ở FE thay vì tải ảnh từ vietqr.io: giữ đúng triết lý tự-sinh-QR
 * cục bộ (miễn phí, không phụ thuộc dịch vụ ngoài) và KHÔNG gửi số TK / số tiền
 * / nội dung CK (chứa tên học viên = PII) ra bên thứ ba. Mã QR "trần" do backend
 * render (`VietQRResponse.qr_image_base64`) chỉ có ô QR — thiếu số tiền / tên
 * chủ TK / ngân hàng nên học viên ít tin tưởng khi quét. Thẻ này bổ sung các
 * thông tin đó quanh mã QR.
 */

import { formatVND } from "@/lib/zod/finance"
import type { VietQRResponse } from "@/types/finance.types"

// BIN (Napas) → tên ngân hàng đầy đủ. Trường thường dùng 1 ngân hàng cố định
// nên chỉ cần phủ các ngân hàng phổ biến; BIN lạ rơi về nhãn "BIN xxxxxx".
const BANK_NAMES: Record<string, string> = {
  "970436": "Ngân hàng TMCP Ngoại thương Việt Nam (Vietcombank)",
  "970418": "Ngân hàng TMCP Đầu tư và Phát triển Việt Nam (BIDV)",
  "970405": "Ngân hàng Nông nghiệp và PTNT Việt Nam (Agribank)",
  "970415": "Ngân hàng TMCP Công thương Việt Nam (VietinBank)",
  "970422": "Ngân hàng TMCP Quân đội (MB)",
  "970407": "Ngân hàng TMCP Kỹ thương Việt Nam (Techcombank)",
  "970416": "Ngân hàng TMCP Á Châu (ACB)",
  "970432": "Ngân hàng TMCP Việt Nam Thịnh Vượng (VPBank)",
  "970423": "Ngân hàng TMCP Tiên Phong (TPBank)",
  "970403": "Ngân hàng TMCP Sài Gòn Thương Tín (Sacombank)",
  "970443": "Ngân hàng TMCP Sài Gòn - Hà Nội (SHB)",
  "970431": "Ngân hàng TMCP Xuất Nhập khẩu Việt Nam (Eximbank)",
  "970426": "Ngân hàng TMCP Hàng Hải Việt Nam (MSB)",
  "970441": "Ngân hàng TMCP Quốc tế Việt Nam (VIB)",
  "970448": "Ngân hàng TMCP Phương Đông (OCB)",
  "970437": "Ngân hàng TMCP Phát triển TP.HCM (HDBank)",
  "970429": "Ngân hàng TMCP Sài Gòn (SCB)",
  "970409": "Ngân hàng TMCP Bắc Á (BacABank)",
  "970425": "Ngân hàng TMCP An Bình (ABBANK)",
  "970412": "Ngân hàng TMCP Đại Chúng Việt Nam (PVcomBank)",
  "970440": "Ngân hàng TMCP Đông Nam Á (SeABank)",
  "970419": "Ngân hàng TMCP Quốc Dân (NCB)",
  "970433": "Ngân hàng TMCP Việt Nam Thương Tín (VietBank)",
  "970438": "Ngân hàng TMCP Bảo Việt (BaoVietBank)",
  "970406": "Ngân hàng TMCP Đông Á (DongABank)",
  "970424": "Ngân hàng Shinhan Việt Nam (Shinhan Bank)",
  "970430": "Ngân hàng TMCP Xăng dầu Petrolimex (PGBank)",
  "970452": "Ngân hàng TMCP Kiên Long (KienLongBank)",
  "970457": "Ngân hàng Woori Việt Nam (Woori Bank)",
  "970454": "Ngân hàng TMCP Bản Việt (BVBank)",
}

export function bankNameFromBin(bin: string): string {
  return BANK_NAMES[bin] ?? `Ngân hàng (BIN ${bin})`
}

function loadImage(src: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const img = new Image()
    img.onload = () => resolve(img)
    img.onerror = () => reject(new Error("Không tải được ảnh QR"))
    img.src = src
  })
}

/** Ngắt dòng text theo bề rộng tối đa (canvas) với font cho trước. */
function wrapText(
  ctx: CanvasRenderingContext2D,
  text: string,
  maxWidth: number,
  font: string,
): string[] {
  ctx.font = font
  const words = text.split(" ")
  const lines: string[] = []
  let current = ""
  for (const word of words) {
    const candidate = current ? `${current} ${word}` : word
    if (ctx.measureText(candidate).width > maxWidth && current) {
      lines.push(current)
      current = word
    } else {
      current = candidate
    }
  }
  if (current) lines.push(current)
  return lines
}

/**
 * Vẽ thẻ VietQR (mã QR + thông tin chuyển khoản) và trả về PNG blob.
 * Ném lỗi nếu môi trường không có canvas 2D (caller fallback / báo lỗi).
 */
export async function renderVietQRCard(data: VietQRResponse): Promise<Blob> {
  const qrImg = await loadImage(`data:image/png;base64,${data.qr_image_base64}`)

  const W = 680
  const PAD = 44
  const QR = 400
  const LINE_H = 34

  const canvas = document.createElement("canvas")
  canvas.width = W
  const ctx = canvas.getContext("2d")
  if (!ctx) throw new Error("Trình duyệt không hỗ trợ canvas 2D")

  const infoFont = "22px sans-serif"
  const infoFontStrong = "bold 22px sans-serif"
  const maxTextW = W - PAD * 2

  const rows: Array<{ text: string; strong?: boolean }> = [
    { text: `Số tiền: ${formatVND(data.amount)}`, strong: true },
    { text: `Nội dung CK: ${data.content}` },
    { text: `Tên chủ TK: ${data.bank_account.account_name}` },
    { text: `Số TK: ${data.bank_account.account_number}`, strong: true },
    { text: bankNameFromBin(data.bank_account.bank_bin) },
  ]

  // Đo trước để tính chiều cao chính xác (nội dung CK có thể dài, xuống dòng).
  const wrapped = rows.map((r) => ({
    ...r,
    lines: wrapText(ctx, r.text, maxTextW, r.strong ? infoFontStrong : infoFont),
  }))
  const infoLines = wrapped.reduce((n, r) => n + r.lines.length, 0)

  const titleH = 92
  const qrTop = titleH
  const hintH = 46
  const infoTop = qrTop + QR + hintH
  const H = infoTop + infoLines * LINE_H + PAD
  canvas.height = H // ⚠️ reset toàn bộ state context → set lại style khi vẽ

  // Nền + viền.
  ctx.fillStyle = "#ffffff"
  ctx.fillRect(0, 0, W, H)
  ctx.strokeStyle = "#1d4ed8"
  ctx.lineWidth = 6
  ctx.strokeRect(10, 10, W - 20, H - 20)

  // Tiêu đề.
  ctx.textAlign = "center"
  ctx.fillStyle = "#0f172a"
  ctx.font = "bold 34px sans-serif"
  ctx.fillText("CHUYỂN KHOẢN HỌC PHÍ", W / 2, 60)

  // Mã QR.
  ctx.drawImage(qrImg, (W - QR) / 2, qrTop, QR, QR)

  // Gợi ý quét.
  ctx.fillStyle = "#64748b"
  ctx.font = "18px sans-serif"
  ctx.fillText(
    "Quét mã bằng ứng dụng ngân hàng để chuyển khoản",
    W / 2,
    qrTop + QR + 30,
  )

  // Thông tin (căn giữa như thẻ VietQR chuẩn).
  let y = infoTop + 26
  for (const r of wrapped) {
    ctx.font = r.strong ? infoFontStrong : infoFont
    ctx.fillStyle = r.strong ? "#0f172a" : "#334155"
    for (const line of r.lines) {
      ctx.fillText(line, W / 2, y)
      y += LINE_H
    }
  }

  return await new Promise<Blob>((resolve, reject) => {
    canvas.toBlob(
      (blob) => (blob ? resolve(blob) : reject(new Error("Không tạo được ảnh PNG"))),
      "image/png",
    )
  })
}
