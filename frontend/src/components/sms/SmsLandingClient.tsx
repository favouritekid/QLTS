// src/components/sms/SmsLandingClient.tsx
"use client"

import { useState } from "react"
import Link from "next/link"
import { useMutation, useQuery } from "@tanstack/react-query"
import {
  ArrowRight,
  BellOff,
  CheckCircle2,
  ChevronRight,
  GraduationCap,
  Loader2,
  PenLine,
  Phone,
} from "lucide-react"

import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog"
import { getSmsLanding, postSmsOptOut } from "@/lib/api/sms"

import { programEditorial, SMS_HOTLINE, SMS_HOTLINE_TEL } from "./smsContent"

const HERO_GLOW: React.CSSProperties = {
  background:
    "radial-gradient(circle, rgba(254,166,25,.22) 0%, rgba(254,166,25,0) 70%)",
}

function Page({ children }: { children: React.ReactNode }) {
  return (
    <div className="bg-sms-bg min-h-screen">
      <div className="relative mx-auto max-w-md">{children}</div>
    </div>
  )
}

function scrollToPrograms() {
  document.getElementById("nganh")?.scrollIntoView({ behavior: "smooth" })
}

/**
 * Landing chốt (tier-1 = hub ngành). IDENTITY ngành (id/tên/trình độ) là thật từ
 * BE để đo lường; badge/teaser học phí là editorial (smsContent). `body` render
 * plain text (whitespace-pre-line → chống XSS). Opt-out idempotent qua AlertDialog.
 */
export function SmsLandingClient({ code }: { code: string }) {
  const [optedOut, setOptedOut] = useState(false)

  const { data, isLoading, isError } = useQuery({
    queryKey: ["sms-landing", code],
    queryFn: () => getSmsLanding(code),
    retry: false,
  })

  const optOut = useMutation({
    mutationFn: () => postSmsOptOut(code),
    onSuccess: () => setOptedOut(true),
  })

  if (isLoading) {
    return (
      <Page>
        <div role="status" aria-label="Đang tải" className="animate-pulse">
          <div className="from-sms-700 to-sms-500 bg-gradient-to-br px-5 pb-8 pt-14">
            <div className="mb-5 h-4 w-1/2 rounded bg-white/25" />
            <div className="h-6 w-11/12 rounded bg-white/25" />
            <div className="mt-2 h-6 w-3/4 rounded bg-white/25" />
          </div>
          <div className="grid grid-cols-2 gap-3 p-4">
            {[0, 1, 2, 3].map((i) => (
              <div key={i} className="bg-sms-surface-high h-[168px] rounded-xl" />
            ))}
          </div>
        </div>
      </Page>
    )
  }

  if (isError || !data) {
    return (
      <Page>
        <div className="flex min-h-screen flex-col items-center justify-center px-9 text-center">
          <div className="mb-5 flex h-16 w-16 items-center justify-center rounded-2xl bg-red-50 text-3xl">
            ⏳
          </div>
          <h1 className="text-sms-ink-strong mb-1.5 text-lg font-bold">
            Liên kết đã hết hạn
          </h1>
          <p className="text-sms-ink-soft text-sm leading-relaxed">
            Đường dẫn tuyển sinh này không hợp lệ hoặc không còn hiệu lực. Vui
            lòng kiểm tra lại liên kết trong tin nhắn.
          </p>
        </div>
      </Page>
    )
  }

  const isOptedOut = optedOut || data.already_opted_out

  return (
    <Page>
      {/* Top app bar */}
      <header className="bg-sms-bg/85 border-sms-line/40 sticky top-0 z-40 flex items-center justify-between border-b px-4 py-2.5 backdrop-blur-md">
        <div className="flex min-w-0 items-center gap-2">
          <GraduationCap className="text-sms-ink h-5 w-5 shrink-0" />
          <span className="text-sms-ink truncate text-[15px] font-bold">
            {data.school_name}
          </span>
        </div>
        <a
          href={SMS_HOTLINE_TEL}
          aria-label="Gọi hotline"
          className="text-sms-ink-soft hover:text-sms-ink shrink-0 rounded-full p-1.5 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sms-500"
        >
          <Phone className="h-5 w-5" />
        </a>
      </header>

      <main className="pb-24">
        {/* Hero */}
        <section className="from-sms-700 to-sms-500 relative overflow-hidden bg-gradient-to-br px-5 pb-9 pt-9 text-white">
          <div aria-hidden className="absolute -right-10 -top-10 h-56 w-56 rounded-full" style={HERO_GLOW} />
          <div className="relative">
            <div className="mb-4 flex items-center gap-2">
              <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-white/15 text-lg backdrop-blur-md">
                🎓
              </span>
              <span className="text-sm font-semibold text-white/90">
                {data.school_name}
              </span>
            </div>
            <h1 className="text-[26px] font-extrabold leading-tight tracking-tight">
              {data.headline || "Chọn ngành — xem học phí, phương thức & hồ sơ trong 1 phút"}
            </h1>
            <p className="mt-2.5 whitespace-pre-line text-sm leading-relaxed text-white/80">
              {data.body ||
                "Bắt đầu hành trình nghề nghiệp tương lai với lộ trình đào tạo thực tế và hiện đại."}
            </p>
          </div>
        </section>

        {/* CTA ngoài (nếu chiến dịch có) */}
        {data.cta_label && data.cta_url && (
          <div className="px-4 pt-4">
            <a
              href={data.cta_url}
              target="_blank"
              rel="noreferrer"
              className="bg-sms-gold-m3 text-sms-gold-m3-ink flex h-12 w-full items-center justify-center rounded-xl px-4 text-base font-bold transition-opacity hover:opacity-90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sms-gold-500 focus-visible:ring-offset-2"
            >
              {data.cta_label}
            </a>
          </div>
        )}

        {/* Danh mục ngành */}
        {data.programs.length > 0 ? (
          <section id="nganh" className="scroll-mt-16 px-4 pt-6">
            <div className="mb-3 flex items-baseline justify-between px-0.5">
              <h2 className="text-sms-ink-strong text-lg font-bold">
                Ngành đang tuyển
              </h2>
              <span className="text-sms-ink-soft text-xs">
                {data.programs.length} ngành
              </span>
            </div>
            <ul className="grid grid-cols-2 gap-3">
              {data.programs.map((p) => {
                const ed = programEditorial(p.name)
                return (
                  <li key={p.id}>
                    <Link
                      href={`/lp/${encodeURIComponent(code)}/nganh/${p.id}`}
                      className="border-sms-line/40 bg-sms-card flex min-h-[168px] flex-col rounded-xl border p-3.5 shadow-sm transition-transform active:scale-[.97] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sms-500"
                    >
                      <div className="mb-3 flex items-start justify-between">
                        <span className="bg-sms-50 flex h-11 w-11 items-center justify-center rounded-xl text-xl">
                          {ed.icon}
                        </span>
                        {ed.badge === "hot" && (
                          <span className="rounded-full bg-red-600 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider text-white">
                            Hot
                          </span>
                        )}
                        {ed.badge === "open" && (
                          <span className="bg-sms-gold-m3 text-sms-gold-m3-ink rounded-full px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider">
                            Đang tuyển
                          </span>
                        )}
                      </div>
                      <h3 className="text-sms-ink-strong line-clamp-2 text-[15px] font-bold leading-tight">
                        {p.name}
                      </h3>
                      <div className="mt-auto pt-2">
                        <span className="bg-sms-pill text-sms-pill-ink mb-1.5 inline-block rounded-md px-2 py-0.5 text-[11px] font-semibold">
                          {p.degree_level}
                        </span>
                        <div className="flex items-center justify-between">
                          <span className="text-sms-ink-soft truncate text-[11px] italic">
                            {ed.tuitionTeaser}
                          </span>
                          <ChevronRight className="text-sms-line h-4 w-4 shrink-0" />
                        </div>
                      </div>
                    </Link>
                  </li>
                )
              })}
            </ul>
          </section>
        ) : (
          <section className="px-9 py-14 text-center">
            <div className="bg-sms-50 mx-auto mb-4 flex h-16 w-16 items-center justify-center rounded-2xl text-3xl">
              📂
            </div>
            <div className="text-sms-ink-strong mb-1.5 text-base font-bold">
              Chưa có ngành tuyển sinh
            </div>
            <p className="text-sms-ink-soft text-sm leading-relaxed">
              Kỳ tuyển sinh mới sẽ sớm được mở. Vui lòng quay lại sau.
            </p>
          </section>
        )}

        {/* Promo card */}
        <section className="px-4 pt-6">
          <a
            href={SMS_HOTLINE_TEL}
            className="bg-sms-600 relative flex items-center gap-4 overflow-hidden rounded-xl p-4 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sms-500 focus-visible:ring-offset-2"
          >
            <div className="absolute -right-6 -top-6 h-24 w-24 rounded-full bg-white/10" />
            <div className="relative z-10 min-w-0">
              <p className="text-sm font-semibold text-white">
                Cần hỗ trợ chọn ngành?
              </p>
              <p className="text-xs text-white/80">
                Gọi {SMS_HOTLINE} — chuyên viên tư vấn hỗ trợ bạn.
              </p>
            </div>
            <span className="relative z-10 ml-auto flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-white shadow-md">
              <ArrowRight className="text-sms-600 h-5 w-5" />
            </span>
          </a>
        </section>

        {/* Footer consent + opt-out */}
        <footer className="mt-8 px-4 pb-6">
          <div className="border-sms-line/50 border-t pt-4">
            <p className="text-sms-ink-soft mb-3.5 text-xs leading-relaxed">
              {data.consent_notice}
            </p>
            {isOptedOut ? (
              <div className="flex items-center gap-2 rounded-xl border border-emerald-200 bg-emerald-50 px-3.5 py-3 text-sm font-medium text-emerald-800">
                <CheckCircle2 className="h-4 w-4 shrink-0 text-emerald-600" /> Đã
                hủy nhận tin từ {data.school_name}.
              </div>
            ) : (
              <AlertDialog>
                <AlertDialogTrigger asChild>
                  <button
                    type="button"
                    disabled={optOut.isPending}
                    className="border-sms-line bg-sms-card text-sms-ink-soft flex h-11 w-full items-center justify-center gap-2 rounded-xl border text-sm font-semibold transition-colors hover:bg-sms-surface-low focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sms-500 disabled:opacity-50"
                  >
                    {optOut.isPending ? (
                      <Loader2 className="h-4 w-4 animate-spin" />
                    ) : (
                      <BellOff className="h-4 w-4" />
                    )}
                    Hủy nhận tin
                  </button>
                </AlertDialogTrigger>
                <AlertDialogContent>
                  <AlertDialogHeader>
                    <AlertDialogTitle>Hủy nhận tin?</AlertDialogTitle>
                    <AlertDialogDescription>
                      Bạn chắc chắn muốn ngừng nhận tin quảng cáo tuyển sinh từ{" "}
                      {data.school_name}?
                    </AlertDialogDescription>
                  </AlertDialogHeader>
                  <AlertDialogFooter>
                    <AlertDialogCancel>Không</AlertDialogCancel>
                    <AlertDialogAction onClick={() => optOut.mutate()}>
                      Hủy nhận tin
                    </AlertDialogAction>
                  </AlertDialogFooter>
                </AlertDialogContent>
              </AlertDialog>
            )}
            {optOut.isError && (
              <p className="mt-2 text-xs text-red-600">
                Không thể hủy lúc này. Vui lòng thử lại.
              </p>
            )}
            <p className="text-sms-line mt-4 text-center text-[10px]">
              © {data.school_name}. Bảo lưu mọi quyền.
            </p>
          </div>
        </footer>
      </main>

      {/* Bottom nav */}
      <nav className="fixed inset-x-0 bottom-0 z-40">
        <div className="border-sms-line/60 bg-sms-card/95 mx-auto flex max-w-md items-center gap-2 border-t px-4 py-2.5 backdrop-blur-md">
          <button
            type="button"
            onClick={scrollToPrograms}
            className="text-sms-ink-soft flex flex-1 items-center justify-center gap-1.5 rounded-xl py-2.5 text-sm font-semibold transition-colors hover:bg-sms-surface-low"
          >
            <PenLine className="h-4 w-4" /> Đăng ký tư vấn
          </button>
          <a
            href={SMS_HOTLINE_TEL}
            className="bg-sms-gold-m3 text-sms-gold-m3-ink flex flex-1 items-center justify-center gap-1.5 rounded-xl py-2.5 text-sm font-bold transition-opacity hover:opacity-90"
          >
            <Phone className="h-4 w-4" /> Gọi ngay
          </a>
        </div>
      </nav>
    </Page>
  )
}
