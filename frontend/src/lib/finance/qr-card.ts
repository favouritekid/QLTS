/**
 * Render một "thẻ VietQR" đầy đủ thông tin (canvas → PNG) để officer chia sẻ
 * cho học viên / phụ huynh.
 *
 * Vì sao TỰ vẽ ở FE thay vì tải ảnh từ vietqr.io: giữ đúng triết lý tự-sinh-QR
 * cục bộ (miễn phí, không phụ thuộc dịch vụ ngoài) và KHÔNG gửi số TK / số tiền
 * / nội dung CK (chứa tên học viên = PII) ra bên thứ ba. Mã QR "trần" do backend
 * render (`VietQRResponse.qr_image_base64`) chỉ có ô QR — thiếu số tiền / tên
 * chủ TK / ngân hàng nên học viên ít tin tưởng khi quét. Thẻ này bổ sung các
 * thông tin đó quanh mã QR. Tên ngân hàng lấy từ `bank_account.bank_name` do BE
 * trả (nguồn duy nhất) — FE không tự map BIN→tên.
 */

import { formatVND } from "@/lib/zod/finance"
import type { VietQRResponse } from "@/types/finance.types"

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
    { text: data.bank_account.bank_name },
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
