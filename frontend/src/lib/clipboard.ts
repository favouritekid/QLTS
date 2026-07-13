// src/lib/clipboard.ts
/**
 * Sao chép text vào clipboard — CÓ FALLBACK cho insecure context.
 *
 * `navigator.clipboard` chỉ tồn tại trên SECURE CONTEXT (HTTPS hoặc localhost).
 * Khi truy cập qua IP LAN HTTP (vd http://192.168.88.125:3000 — dùng test trên
 * điện thoại) thì `navigator.clipboard` là `undefined` → mọi nút copy (SĐT, magic
 * link, mã…) hỏng. Hàm này thử Clipboard API trước, thất bại thì fallback về
 * `document.execCommand('copy')` (chạy được trên HTTP). Trả `true/false` thành/bại
 * để caller báo toast.
 *
 * Lưu ý: prod chạy HTTPS nên dùng đường Clipboard API chuẩn; fallback chủ yếu cứu
 * luồng test LAN + phone.
 */
export async function copyToClipboard(text: string): Promise<boolean> {
  // Đường chuẩn (secure context).
  if (typeof navigator !== "undefined" && navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(text);
      return true;
    } catch {
      // Một số trình duyệt vẫn chặn quyền dù secure → rơi xuống fallback.
    }
  }

  // Fallback execCommand cho insecure/HTTP.
  if (typeof document === "undefined") return false;

  const textarea = document.createElement("textarea");
  textarea.value = text;
  textarea.setAttribute("readonly", "");
  // Ẩn khỏi tầm nhìn nhưng vẫn selectable (position:fixed tránh cuộn nhảy).
  textarea.style.position = "fixed";
  textarea.style.top = "0";
  textarea.style.left = "0";
  textarea.style.width = "1px";
  textarea.style.height = "1px";
  textarea.style.padding = "0";
  textarea.style.border = "none";
  textarea.style.opacity = "0";
  textarea.style.pointerEvents = "none";
  document.body.appendChild(textarea);

  const selection = document.getSelection();
  const savedRange =
    selection && selection.rangeCount > 0 ? selection.getRangeAt(0) : null;

  let ok = false;
  try {
    textarea.focus();
    textarea.select();
    textarea.setSelectionRange(0, text.length); // iOS cần range tường minh
    ok = document.execCommand("copy");
  } catch {
    ok = false;
  } finally {
    document.body.removeChild(textarea);
    // Khôi phục vùng chọn của người dùng nếu có.
    if (savedRange && selection) {
      selection.removeAllRanges();
      selection.addRange(savedRange);
    }
  }

  return ok;
}
