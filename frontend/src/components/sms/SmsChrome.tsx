// src/components/sms/SmsChrome.tsx
// Primitive trình bày DÙNG CHUNG cho landing SMS 2 tầng (tier-1 hub +
// tier-2 trang ngành). Trước đây chrome (khung trang / header / footer /
// thẻ lỗi / nút Zalo / badge giảm giá) bị chép byte-identical ở cả hai file
// → gom về đây để đổi 1 chỗ, tránh drift. Thuần trình bày, KHÔNG hook động
// (render được cả server/client) → không cần "use client".
import Link from "next/link"
import { GraduationCap, Phone } from "lucide-react"

import {
  COPYRIGHT_YEAR,
  FONT_STACK,
  SCHOOL_ADDRESS,
  SMS_HOTLINE,
  SMS_HOTLINE_TEL,
  SMS_SUB_BRAND,
  SMS_ZALO_ENABLED,
  SMS_ZALO_URL,
} from "./smsContent"

/** Khung trang: nền ngoài + khung trắng 1180px căn giữa + font thương hiệu.
 *  Byte-identical ở cả hai tầng trước khi tách. */
export function SmsPage({ children }: { children: React.ReactNode }) {
  return (
    <div className="bg-sms-bg min-h-screen" style={{ fontFamily: FONT_STACK }}>
      <div className="bg-sms-card mx-auto max-w-[1180px]">{children}</div>
    </div>
  )
}

/** Header thương hiệu: logo + tên trường + dòng phụ + hotline + nút "Đăng ký".
 *  `homeHref` có → brand là <Link> về trang chủ (tier-2); không có → <div>
 *  (tier-1 đang ở trang chủ). `registerHref` là đích nút CTA (#reg cùng trang
 *  ở tier-1, /lp/{code}#reg xuyên trang ở tier-2) — luôn dùng <Link>. */
export function SmsHeader({
  schoolName,
  homeHref,
  registerHref,
}: {
  schoolName: string
  homeHref?: string
  registerHref: string
}) {
  const brandInner = (
    <>
      <span className="from-sms-500 to-sms-700 flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br text-white shadow-sm">
        <GraduationCap className="h-5 w-5" />
      </span>
      <span className="min-w-0 leading-tight">
        <span className="text-sms-ink block truncate text-[15px] font-extrabold">
          {schoolName}
        </span>
        <span className="text-sms-ink-muted block text-[11px] font-medium tracking-wider">
          {SMS_SUB_BRAND}
        </span>
      </span>
    </>
  )
  return (
    <header className="border-sms-line flex items-center justify-between border-b px-5 py-4 lg:px-11">
      {homeHref ? (
        <Link href={homeHref} className="flex min-w-0 items-center gap-3">
          {brandInner}
        </Link>
      ) : (
        <div className="flex min-w-0 items-center gap-3">{brandInner}</div>
      )}
      <div className="flex items-center gap-2.5">
        <a
          href={SMS_HOTLINE_TEL}
          className="border-sms-100 text-sms-500 hidden items-center gap-1.5 rounded-lg border px-3.5 py-2 text-[13.5px] font-bold sm:inline-flex"
        >
          <Phone className="h-4 w-4" /> {SMS_HOTLINE}
        </a>
        <Link
          href={registerHref}
          className="bg-sms-500 rounded-lg px-4 py-2.5 text-[13.5px] font-bold text-white transition-opacity hover:opacity-90"
        >
          Đăng ký ngay
        </Link>
      </div>
    </header>
  )
}

/** Footer tối: © năm + tên trường + địa chỉ. Byte-identical ở cả hai tầng. */
export function SmsFooter({ schoolName }: { schoolName: string }) {
  return (
    <footer className="bg-sms-900 flex flex-wrap items-center justify-between gap-2 px-6 py-5 text-xs text-[#8ea3c9] lg:px-11">
      <span>
        © {COPYRIGHT_YEAR} {schoolName}
      </span>
      <span>{SCHOOL_ADDRESS}</span>
    </footer>
  )
}

/** Thẻ lỗi/không tìm thấy (biểu tượng ⏳ + tiêu đề + mô tả + hành động tùy chọn).
 *  Dùng khi query lỗi / hết hạn (tier-1) hoặc không thấy ngành (tier-2). */
export function SmsErrorCard({
  title,
  message,
  action,
}: {
  title: string
  message: string
  action?: React.ReactNode
}) {
  return (
    <div className="flex min-h-screen flex-col items-center justify-center px-9 text-center">
      <div className="mb-5 flex h-16 w-16 items-center justify-center rounded-2xl bg-red-50 text-3xl">
        ⏳
      </div>
      <h1 className="text-sms-ink-strong mb-1.5 text-lg font-bold">{title}</h1>
      <p
        className={`text-sms-ink-soft text-sm leading-relaxed ${action ? "mb-6" : ""}`}
      >
        {message}
      </p>
      {action}
    </div>
  )
}

/** Nút/link Zalo an toàn: GATE `SMS_ZALO_ENABLED` (link chưa cấu hình → không
 *  render, tránh CTA chết) + `target=_blank rel=noreferrer` gom 1 chỗ (khỏi
 *  quên → hết rủi ro tab-nabbing). `className`/`children` do nơi gọi quyết định
 *  (mỗi tầng style khác nhau). */
export function ZaloLink({
  className,
  children,
  ariaLabel,
}: {
  className: string
  children: React.ReactNode
  ariaLabel?: string
}) {
  if (!SMS_ZALO_ENABLED) return null
  return (
    <a
      href={SMS_ZALO_URL}
      target="_blank"
      rel="noreferrer"
      aria-label={ariaLabel}
      className={className}
    >
      {children}
    </a>
  )
}

/** Badge chính sách học phí — suy TỪ CỜ THẬT `isHeavy` của BE (KHÔNG đoán tay):
 *  nghề nặng nhọc/độc hại/nguy hiểm được miễn giảm 70% học phí theo NĐ 81/2021
 *  → badge flame "Giảm 70% học phí"; ngành thường → pill vàng "Học bổng đầu vào"
 *  (học bổng đến 100% kỳ I — vẫn là móc tài chính thật). `size`: "card" (thẻ
 *  tier-1, gọn) hoặc "hero" (hero tier-2). */
export function DiscountBadge({
  isHeavy,
  size,
}: {
  isHeavy: boolean
  size: "card" | "hero"
}) {
  const label = isHeavy
    ? size === "card"
      ? "Giảm 70%"
      : "Giảm 70% học phí"
    : size === "card"
      ? "Học bổng"
      : "Học bổng đầu vào"
  const color = isHeavy
    ? "from-sms-flame-from to-sms-flame-to bg-gradient-to-br text-white"
    : "bg-sms-gold-soft text-sms-gold-ink"
  const shape =
    size === "card"
      ? "inline-block w-fit rounded-md px-2.5 py-1 text-[11px] font-extrabold"
      : "rounded-full px-3 py-1.5 text-[12.5px] font-bold"
  return <span className={`${shape} ${color}`}>{label}</span>
}
