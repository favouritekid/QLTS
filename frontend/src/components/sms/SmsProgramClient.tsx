// src/components/sms/SmsProgramClient.tsx
"use client"

import { useState } from "react"
import Link from "next/link"
import { useQuery } from "@tanstack/react-query"
import {
  Briefcase,
  CalendarClock,
  CheckCircle2,
  ChevronLeft,
  ClipboardCheck,
  FileText,
  GraduationCap,
  Loader2,
  Phone,
  Smartphone,
  Sparkles,
  Wallet,
} from "lucide-react"

import { getSmsLanding } from "@/lib/api/sms"
import { useSmsDwellTracker } from "@/hooks/useSmsDwellTracker"

import { programEditorial, SMS_HOTLINE_TEL } from "./smsContent"

const HERO_GLOW: React.CSSProperties = {
  background:
    "radial-gradient(circle, rgba(254,166,25,.20) 0%, rgba(254,166,25,0) 70%)",
}

function Page({ children }: { children: React.ReactNode }) {
  return (
    <div className="bg-sms-bg min-h-screen">
      <div className="relative mx-auto max-w-md">{children}</div>
    </div>
  )
}

function SectionCard({
  icon,
  title,
  className,
  children,
}: {
  icon: React.ReactNode
  title: string
  className?: string
  children: React.ReactNode
}) {
  return (
    <div
      className={`border-sms-line/40 bg-sms-card rounded-xl border p-4 shadow-sm ${className ?? ""}`}
    >
      <div className="mb-2.5 flex items-center gap-2">
        <span className="text-sms-ink">{icon}</span>
        <h2 className="text-sms-ink-strong text-[17px] font-semibold">{title}</h2>
      </div>
      {children}
    </div>
  )
}

/**
 * Landing chốt (tier-2 = trang ngành, nơi ĐO CHÍNH dwell). IDENTITY ngành là
 * thật từ BE (`useSmsDwellTracker` đo theo majorProgramId); nội dung học phí/
 * phương thức/hồ sơ/đợt là EDITORIAL (smsContent — chỉnh được, không phải BE).
 * Form chốt lead: UI + đủ state; submit MÔ PHỎNG — nối `/api/public/leads/intake`
 * sau khi có OK gate pháp lý §16.9 (disclosure/DPIA/consent).
 */
export function SmsProgramClient({
  code,
  majorProgramId,
}: {
  code: string
  majorProgramId: number
}) {
  const { data, isLoading, isError } = useQuery({
    queryKey: ["sms-landing", code],
    queryFn: () => getSmsLanding(code),
    retry: false,
  })

  const program = data?.programs.find((p) => p.id === majorProgramId)
  useSmsDwellTracker(code, majorProgramId, Boolean(program))

  // --- Form chốt lead (submit mô phỏng cho tới khi nối intake) ---
  const [status, setStatus] = useState<"idle" | "sending" | "success" | "error">(
    "idle",
  )
  const [phone, setPhone] = useState("")
  const [agree, setAgree] = useState(true)

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault()
    const digits = phone.replace(/\D/g, "")
    if (!agree || digits.length < 10) {
      setStatus("error")
      return
    }
    setStatus("sending")
    // TODO(§16.9): sau khi có OK pháp lý, thay bằng submit thật:
    //   await postLeadIntake({ code, program_id: majorProgramId, phone, ... })
    await new Promise((r) => setTimeout(r, 1200))
    setStatus("success")
  }

  if (isLoading) {
    return (
      <Page>
        <div role="status" aria-label="Đang tải" className="animate-pulse">
          <div className="from-sms-700 to-sms-500 bg-gradient-to-br px-5 pb-9 pt-11">
            <div className="mb-4 h-14 w-14 rounded-2xl bg-white/20" />
            <div className="h-7 w-2/3 rounded bg-white/25" />
          </div>
          <div className="space-y-3 p-4">
            <div className="bg-sms-surface-high h-28 rounded-xl" />
            <div className="bg-sms-surface-high h-24 rounded-xl" />
          </div>
        </div>
      </Page>
    )
  }

  if (isError || !data || !program) {
    return (
      <Page>
        <div className="flex min-h-screen flex-col items-center justify-center px-9 text-center">
          <div className="mb-5 flex h-16 w-16 items-center justify-center rounded-2xl bg-red-50 text-3xl">
            ⏳
          </div>
          <h1 className="text-sms-ink-strong mb-1.5 text-lg font-bold">
            Không tìm thấy ngành
          </h1>
          <p className="text-sms-ink-soft mb-6 text-sm leading-relaxed">
            Ngành không tồn tại hoặc liên kết đã hết hạn.
          </p>
          <Link
            href={`/lp/${encodeURIComponent(code)}`}
            className="bg-sms-600 flex h-11 items-center justify-center gap-2 rounded-xl px-5 text-sm font-semibold text-white transition-colors hover:bg-sms-700"
          >
            <ChevronLeft className="h-4 w-4" /> Về danh mục ngành
          </Link>
        </div>
      </Page>
    )
  }

  const ed = programEditorial(program.name)

  return (
    <Page>
      {/* Top bar */}
      <header className="bg-sms-bg/85 border-sms-line/40 sticky top-0 z-40 flex items-center justify-between border-b px-4 py-2.5 backdrop-blur-md">
        <Link
          href={`/lp/${encodeURIComponent(code)}`}
          className="text-sms-ink flex items-center gap-1 text-sm font-semibold hover:opacity-80"
        >
          <ChevronLeft className="h-5 w-5" /> Xem ngành khác
        </Link>
        <div className="flex items-center gap-1.5">
          <GraduationCap className="text-sms-ink h-5 w-5" />
        </div>
      </header>

      <main className="pb-[228px]">
        {/* Hero ngành */}
        <section className="from-sms-700 to-sms-500 relative overflow-hidden bg-gradient-to-br px-5 pb-9 pt-8 text-white">
          <div aria-hidden className="absolute -right-12 -top-8 h-52 w-52 rounded-full" style={HERO_GLOW} />
          <div className="relative flex flex-col items-start gap-3">
            <span className="flex h-16 w-16 items-center justify-center rounded-2xl bg-white/15 text-3xl backdrop-blur-md">
              {ed.icon}
            </span>
            <div className="flex flex-wrap items-center gap-2">
              <span className="bg-sms-gold-m3 text-sms-gold-m3-ink rounded-full px-3 py-0.5 text-[11px] font-semibold">
                {program.degree_level}
              </span>
              <span className="text-[11px] font-medium text-white/80">
                Mã ngành: {program.code}
              </span>
            </div>
            <h1 className="text-[28px] font-extrabold leading-tight tracking-tight">
              {program.name}
            </h1>
          </div>
        </section>

        {/* Bento sections (nội dung editorial) */}
        <section className="-mt-4 flex flex-col gap-3 px-4">
          <SectionCard
            icon={<Briefcase className="h-5 w-5" />}
            title="Học xong làm gì?"
            className="shadow-md"
          >
            <ul className="flex flex-col gap-2">
              {ed.careers.map((c, i) => (
                <li key={i} className="text-sms-ink-soft flex gap-2 text-[15px] leading-relaxed">
                  <span className="text-sms-600 font-bold">›</span> {c}
                </li>
              ))}
            </ul>
          </SectionCard>

          <SectionCard
            icon={<Wallet className="h-5 w-5" />}
            title="Học phí & học bổng"
            className="border-sms-gold-m3 border-l-4"
          >
            <div className="border-sms-line/60 mb-2 flex items-center justify-between border-b pb-2">
              <span className="text-sms-ink-soft text-xs">Học phí</span>
              <span className="text-sms-ink text-[15px] font-bold">
                {ed.tuitionPerTerm}
              </span>
            </div>
            <p className="bg-sms-gold-50 rounded-lg px-3 py-2 text-sm leading-relaxed text-[#7a4a00]">
              🎁 {ed.scholarship}
            </p>
          </SectionCard>

          <SectionCard
            icon={<ClipboardCheck className="h-5 w-5" />}
            title="Phương thức xét tuyển"
          >
            <ul className="flex flex-col gap-2">
              {ed.methods.map((m, i) => (
                <li key={i} className="text-sms-ink-soft flex items-center gap-2 text-[15px]">
                  <CheckCircle2 className="text-sms-green h-4 w-4 shrink-0" /> {m}
                </li>
              ))}
            </ul>
          </SectionCard>

          <SectionCard
            icon={<FileText className="h-5 w-5" />}
            title="Hồ sơ cần chuẩn bị"
          >
            <ul className="flex flex-col gap-2">
              {ed.documents.map((d, i) => (
                <li key={i} className="text-sms-ink-soft flex gap-2.5 text-[15px] leading-snug">
                  <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-md bg-emerald-50 text-[12px] font-extrabold text-emerald-600">
                    ✓
                  </span>
                  {d}
                </li>
              ))}
            </ul>
          </SectionCard>

          <div className="bg-sms-surface-high border-sms-500/10 rounded-xl border p-4">
            <div className="mb-2.5 flex items-center gap-2">
              <CalendarClock className="text-sms-ink h-5 w-5" />
              <h2 className="text-sms-ink-strong text-[17px] font-semibold">
                Đợt & hạn nộp
              </h2>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-sms-ink-soft text-[15px]">{ed.roundLabel}</span>
              <span className="rounded-lg bg-[#FFDAD6] px-3 py-1 text-[11px] font-bold text-[#93000A]">
                {ed.roundDeadline}
              </span>
            </div>
          </div>
        </section>

        {/* Visual anchor (gradient nhẹ thay ảnh stock — nhanh, không lộ nguồn) */}
        <div className="px-4 pt-4">
          <div className="from-sms-800 to-sms-500 relative flex h-40 items-end overflow-hidden rounded-2xl bg-gradient-to-br p-4 shadow-md">
            <Sparkles className="absolute right-3 top-3 h-16 w-16 text-white/15" />
            <p className="relative text-sm font-semibold text-white">
              Cơ sở vật chất hiện đại — học đi đôi với thực hành
            </p>
          </div>
        </div>

        {/* Footer consent */}
        <p className="text-sms-ink-soft mt-6 px-4 text-center text-xs leading-relaxed">
          {data.consent_notice}
        </p>
      </main>

      {/* Sticky CTA — form chốt lead (submit mô phỏng) */}
      <div className="border-sms-line/50 bg-sms-card/95 fixed inset-x-0 bottom-0 z-50 mx-auto max-w-md rounded-t-2xl border-t px-4 py-3.5 shadow-[0_-8px_30px_rgba(15,23,42,.12)] backdrop-blur-xl">
        {status === "success" ? (
          <div className="flex items-center gap-3 rounded-xl border border-emerald-300 bg-emerald-50 px-4 py-3.5">
            <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-emerald-600 text-lg font-bold text-white">
              ✓
            </span>
            <div>
              <div className="text-[15px] font-bold text-emerald-900">
                Đã ghi nhận thành công!
              </div>
              <div className="text-[13px] leading-snug text-emerald-700">
                Nhà trường sẽ liên hệ tư vấn cho bạn sớm nhất.
              </div>
            </div>
          </div>
        ) : (
          <form onSubmit={onSubmit} className="flex flex-col gap-2.5">
            <div className="relative">
              <Smartphone className="text-sms-ink-soft pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2" />
              <input
                type="tel"
                inputMode="tel"
                value={phone}
                onChange={(e) => {
                  setPhone(e.target.value)
                  if (status === "error") setStatus("idle")
                }}
                placeholder="Nhập số điện thoại của bạn…"
                aria-label="Số điện thoại"
                className={`bg-sms-surface-low w-full rounded-xl border py-3 pl-9 pr-4 text-[15px] outline-none transition-colors focus:ring-2 focus:ring-sms-500 ${
                  status === "error" ? "border-red-500" : "border-sms-line"
                }`}
              />
            </div>
            <div className="grid grid-cols-5 gap-2">
              <button
                type="submit"
                disabled={status === "sending"}
                className="bg-sms-gold-m3 text-sms-gold-m3-ink col-span-3 flex items-center justify-center gap-2 rounded-xl py-3 text-[15px] font-bold transition-opacity hover:opacity-90 disabled:opacity-70"
              >
                {status === "sending" ? (
                  <>
                    <Loader2 className="h-4 w-4 animate-spin" /> Đang gửi…
                  </>
                ) : (
                  "Đăng ký tư vấn"
                )}
              </button>
              <a
                href={SMS_HOTLINE_TEL}
                className="bg-sms-600 col-span-2 flex items-center justify-center gap-1.5 rounded-xl py-3 text-[15px] font-bold text-white transition-opacity hover:opacity-90"
              >
                <Phone className="h-4 w-4" /> Gọi ngay
              </a>
            </div>
            {status === "error" && (
              <p className="text-[12px] font-medium text-red-600">
                {agree
                  ? "Số điện thoại chưa hợp lệ (tối thiểu 10 số)."
                  : "Vui lòng đồng ý được liên hệ tư vấn."}
              </p>
            )}
            <label className="text-sms-ink-soft flex cursor-pointer select-none items-center gap-2 text-[12px]">
              <input
                type="checkbox"
                checked={agree}
                onChange={(e) => setAgree(e.target.checked)}
                className="accent-sms-600 h-4 w-4"
              />
              Tôi đồng ý được liên hệ tư vấn
            </label>
          </form>
        )}
      </div>
    </Page>
  )
}
