// src/components/sms/SmsLandingClient.tsx
"use client"

import { useEffect, useMemo, useState } from "react"
import Link from "next/link"
import { useMutation, useQuery } from "@tanstack/react-query"
import {
  ArrowRight,
  BellOff,
  Check,
  CheckCircle2,
  Clock,
  Loader2,
  MessageCircle,
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

import {
  DiscountBadge,
  HeroImage,
  SmsErrorCard,
  SmsFooter,
  SmsHeader,
  SmsPage,
  ZaloLink,
} from "./SmsChrome"
import { groupPrograms, type ProgramCardVM } from "./smsPrograms"
import {
  ADMISSION_DEADLINE,
  ADMISSION_DEADLINE_LABEL,
  HERO_BADGE,
  HERO_HEADLINE_ACCENT,
  HERO_HEADLINE_LEAD,
  HERO_HEADLINE_TAIL,
  HERO_SUBTITLE,
  isStrongTuition,
  OFFERS,
  REG_CHECKLIST,
  SCHOOL_HERO_IMAGE,
  SMS_HOTLINE,
  SMS_HOTLINE_TEL,
  STATS,
  TESTIMONIALS,
} from "./smsContent"

const STRIPE_OVERLAY: React.CSSProperties = {
  background:
    "repeating-linear-gradient(135deg,rgba(255,255,255,.06) 0 14px,transparent 14px 28px)",
}

/** Đếm ngược tới hạn nộp; clamp ≥ 0, `expired` khi đã quá hạn. `Date.now()` chỉ
 *  gọi trên CLIENT: lazy-init guard `typeof window` → SSR/prerender trả null (né
 *  dynamicIO/cacheComponents cấm API động lúc prerender → dev bail 404), client
 *  có ngay giá trị (không nháy). Effect chỉ đặt interval — setState trong callback
 *  (async), KHÔNG gọi đồng bộ trong thân effect (né cascading-render). */
function useCountdown(target: string) {
  const [now, setNow] = useState<number | null>(() =>
    typeof window === "undefined" ? null : Date.now(),
  )
  useEffect(() => {
    const targetMs = new Date(target).getTime()
    const id = setInterval(() => {
      const n = Date.now()
      setNow(n)
      if (n >= targetMs) clearInterval(id) // quá hạn → ngừng tick (khỏi phí)
    }, 1000)
    return () => clearInterval(id)
  }, [target])
  const targetMs = new Date(target).getTime() // input cố định → deterministic
  const pad = (n: number) => String(n).padStart(2, "0")
  if (now === null) {
    return { expired: false, d: 0, h: "00", m: "00", s: "00" }
  }
  const diff = Math.max(0, targetMs - now)
  return {
    expired: diff <= 0,
    d: Math.floor(diff / 86_400_000),
    h: pad(Math.floor(diff / 3_600_000) % 24),
    m: pad(Math.floor(diff / 60_000) % 60),
    s: pad(Math.floor(diff / 1000) % 60),
  }
}

/**
 * Thẻ đếm ngược — LEAF riêng: interval 1s chỉ re-render component này, KHÔNG kéo
 * cả SmsLandingClient re-render (tránh groupPrograms + 21 card render lại/giây).
 */
function CountdownCard() {
  const cd = useCountdown(ADMISSION_DEADLINE)
  return (
    <div className="from-[#fff7e0] to-[#ffeec2] border-sms-gold-line mb-5 rounded-xl border bg-gradient-to-br px-4 py-3.5">
      {cd.expired ? (
        <div className="text-sms-gold-ink flex items-center gap-2 text-[13px] font-semibold">
          <Clock className="h-4 w-4" /> Liên hệ ngay để được tư vấn hồ sơ tuyển
          sinh.
        </div>
      ) : (
        <>
          <div className="text-sms-gold-ink mb-2.5 flex items-center gap-1.5 text-[12.5px] font-bold">
            <Clock className="h-4 w-4" /> Còn lại để đăng ký xét tuyển đợt 1{" "}
            <span className="text-[#b8560f]">(hạn {ADMISSION_DEADLINE_LABEL})</span>
          </div>
          <div className="flex gap-2">
            {[
              { v: String(cd.d), l: "NGÀY" },
              { v: cd.h, l: "GIỜ" },
              { v: cd.m, l: "PHÚT" },
              { v: cd.s, l: "GIÂY", warn: true },
            ].map((u) => (
              <div
                key={u.l}
                className={`flex-1 rounded-lg px-1 py-2 text-center ${
                  u.warn
                    ? "bg-[#b8560f] text-white"
                    : "bg-sms-gold-m3-ink text-sms-gold-m3"
                }`}
              >
                <div className="text-2xl font-extrabold leading-none tabular-nums">
                  {u.v}
                </div>
                <div className="mt-1 text-[10px] tracking-widest opacity-80">
                  {u.l}
                </div>
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  )
}

function ProgramCard({ code, vm }: { code: string; vm: ProgramCardVM }) {
  const { name, variants } = vm
  const Icon = vm.Icon // member access (không phải call trực tiếp làm JSX-type)
  const hot = isStrongTuition(vm.level) // ưu đãi lớn (miễn 100%/giảm 70%) → viền cam
  const single = variants.length === 1
  const cardCls = `group relative flex min-h-[126px] flex-col overflow-hidden rounded-2xl border bg-sms-card p-4 shadow-sm transition-all focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sms-500 ${
    hot
      ? "border-sms-flame-line hover:border-sms-flame-accent"
      : "border-sms-line hover:border-sms-500"
  } ${single ? "hover:-translate-y-1 hover:shadow-lg" : "hover:shadow-md"}`

  const decor = (
    <Icon
      aria-hidden
      strokeWidth={1.5}
      className={`pointer-events-none absolute -bottom-4 -right-4 h-24 w-24 ${
        hot ? "text-sms-flame-accent opacity-10" : "text-sms-500 opacity-[0.08]"
      }`}
    />
  )
  const head = (
    <>
      <DiscountBadge level={vm.level} size="card" />
      <h3 className="text-sms-ink-strong mt-3 line-clamp-3 text-[15px] font-semibold leading-tight">
        {name}
      </h3>
    </>
  )

  // 1 trình độ → click CẢ THẺ (như mockup); nhiều trình độ → chip mỗi trình độ
  // (KHÔNG lồng <Link> trong <Link>: thẻ đa trình độ là <div>, chip là <Link>).
  if (single) {
    const v = variants[0]
    return (
      <Link
        href={`/lp/${encodeURIComponent(code)}/nganh/${v.id}`}
        className={cardCls}
      >
        {decor}
        <div className="relative z-10 flex h-full flex-col">
          {head}
          <div className="mt-auto pt-2">
            <span className="text-sms-ink-muted mb-1 block text-[11px] font-medium">
              {v.degreeLevel}
            </span>
            <span
              className={`text-[12px] font-semibold ${hot ? "text-sms-flame-accent" : "text-sms-500"}`}
            >
              Xem chi tiết →
            </span>
          </div>
        </div>
      </Link>
    )
  }
  return (
    <div className={cardCls}>
      {decor}
      <div className="relative z-10 flex h-full flex-col">
        {head}
        <div className="mt-auto flex flex-wrap gap-1.5 pt-3">
          {variants.map((v) => (
            <Link
              key={v.id}
              href={`/lp/${encodeURIComponent(code)}/nganh/${v.id}`}
              className="border-sms-line text-sms-500 hover:border-sms-500 hover:bg-sms-50 inline-flex items-center gap-1 rounded-lg border px-2.5 py-1 text-[12px] font-semibold transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sms-500"
            >
              {v.degreeLevel} →
            </Link>
          ))}
        </div>
      </div>
    </div>
  )
}

/**
 * Landing tuyển sinh tier-1 (hub ngành). IDENTITY ngành (id/tên/trình độ/mã) là
 * THẬT từ BE để đo lường; nội dung marketing (nhóm/ưu đãi/tagline) là editorial
 * (smsContent). Thu lead = CTA Gọi/Zalo THẬT (KHÔNG thu PII qua browser — nối
 * intake là task riêng sau khi có OK pháp lý §16.9). Opt-out NĐ91 idempotent.
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

  // Gom ngành 1 lần theo tham chiếu programs (hook PHẢI trước early-return).
  const groups = useMemo(
    () => groupPrograms(data?.programs ?? []),
    [data?.programs],
  )

  if (isLoading) {
    return (
      <SmsPage>
        <div role="status" aria-label="Đang tải" className="animate-pulse">
          <div className="from-sms-700 to-sms-500 bg-gradient-to-b px-6 pb-16 pt-10 lg:px-11">
            <div className="mb-5 h-4 w-40 rounded bg-white/25" />
            <div className="h-9 w-3/4 rounded bg-white/25" />
            <div className="mt-3 h-9 w-1/2 rounded bg-white/25" />
          </div>
          <div className="grid grid-cols-2 gap-3 p-6 md:grid-cols-4 lg:px-11">
            {[0, 1, 2, 3].map((i) => (
              <div key={i} className="bg-sms-surface-alt h-32 rounded-2xl" />
            ))}
          </div>
        </div>
      </SmsPage>
    )
  }

  if (isError || !data) {
    return (
      <SmsPage>
        <SmsErrorCard
          title="Liên kết đã hết hạn"
          message="Đường dẫn tuyển sinh này không hợp lệ hoặc không còn hiệu lực. Vui lòng kiểm tra lại liên kết trong tin nhắn."
        />
      </SmsPage>
    )
  }

  const isOptedOut = optedOut || data.already_opted_out

  return (
    <SmsPage>
      <SmsHeader schoolName={data.school_name} registerHref="#reg" />

      <main>
        {/* Hero */}
        <section className="from-sms-700 to-sms-500 relative overflow-hidden bg-gradient-to-b px-6 pb-16 pt-10 lg:px-11">
          <div aria-hidden className="absolute inset-0" style={STRIPE_OVERLAY} />
          <div className="relative grid items-center gap-9 md:grid-cols-[1.15fr_.85fr]">
            <div className="text-white">
              <span className="inline-block rounded-full bg-white/15 px-3.5 py-1.5 text-xs font-semibold backdrop-blur">
                {HERO_BADGE}
              </span>
              {data.headline ? (
                <h1 className="mt-4 whitespace-pre-line text-3xl font-extrabold leading-[1.1] tracking-tight md:text-[44px]">
                  {data.headline}
                </h1>
              ) : (
                <h1 className="mt-4 text-3xl font-extrabold leading-[1.1] tracking-tight md:text-[44px]">
                  {HERO_HEADLINE_LEAD}
                  <br />
                  {HERO_HEADLINE_TAIL}{" "}
                  <span className="text-sms-gold-m3">{HERO_HEADLINE_ACCENT}</span>
                </h1>
              )}
              <p className="mt-3.5 max-w-lg whitespace-pre-line text-[15px] leading-relaxed text-white/80">
                {data.body || HERO_SUBTITLE}
              </p>
              <div className="mt-6 flex flex-wrap gap-3">
                <a
                  href="#reg"
                  className="bg-sms-gold-m3 text-sms-gold-m3-ink inline-flex items-center gap-2 rounded-xl px-6 py-3.5 text-[15px] font-extrabold transition-opacity hover:opacity-90"
                >
                  Đăng ký xét tuyển <ArrowRight className="h-4 w-4" />
                </a>
                {data.programs.length > 0 && (
                  <a
                    href="#prog"
                    className="inline-flex items-center gap-2 rounded-xl border border-white/30 bg-white/10 px-5 py-3.5 text-[15px] font-bold text-white transition-colors hover:bg-white/20"
                  >
                    Xem các ngành
                  </a>
                )}
                {/* CTA ngoài do chiến dịch cấu hình (BE đã lọc allowlist host). */}
                {data.cta_label && data.cta_url && (
                  <a
                    href={data.cta_url}
                    target="_blank"
                    rel="noreferrer"
                    className="inline-flex items-center gap-2 rounded-xl border border-white/30 bg-white/10 px-5 py-3.5 text-[15px] font-bold text-white transition-colors hover:bg-white/20"
                  >
                    {data.cta_label}
                  </a>
                )}
              </div>
            </div>
            <div className="h-[200px] overflow-hidden rounded-2xl border border-white/25 md:h-[300px]">
              <HeroImage
                src={SCHOOL_HERO_IMAGE}
                alt={`Sinh viên ${data.school_name}`}
              />
            </div>
          </div>
        </section>

        {/* Stats overlap */}
        <section className="relative -mt-9 px-6 lg:px-11">
          <div className="border-sms-line bg-sms-line overflow-hidden rounded-2xl border shadow-[0_14px_40px_rgba(11,61,145,.14)]">
            <div className="grid grid-cols-2 gap-px md:grid-cols-4">
              {STATS.map((s) => (
                <div key={s.k} className="bg-sms-card px-4 py-6 text-center">
                  <div className="text-sms-500 text-[30px] font-extrabold leading-none">
                    {s.k}
                  </div>
                  <div className="text-sms-ink-soft mt-2 text-[12.5px] leading-snug">
                    {s.v}
                  </div>
                </div>
              ))}
            </div>
          </div>
        </section>

        {/* Programs */}
        {data.programs.length > 0 ? (
          <section id="prog" className="px-6 py-14 lg:px-11">
            <div className="mb-7 text-center">
              <h2 className="text-sms-700 text-2xl font-extrabold md:text-[32px]">
                Khám phá các ngành học
              </h2>
              <p className="text-sms-ink-soft mt-2 text-[14.5px]">
                Chọn khối ngành phù hợp với đam mê của bạn
              </p>
            </div>
            <div className="mb-7 flex flex-wrap justify-center gap-5">
              <span className="text-sms-ink-body flex items-center gap-2 text-[13px]">
                <span className="from-sms-flame-from to-sms-flame-to h-3.5 w-3.5 rounded bg-gradient-to-br" />
                <b>Giảm 70% – miễn 100% học phí</b> (tùy ngành &amp; diện xét
                tuyển)
              </span>
              <span className="text-sms-ink-body flex items-center gap-2 text-[13px]">
                <span className="bg-sms-gold-soft border-sms-gold-line h-3.5 w-3.5 rounded border" />
                Ưu đãi <b>30%</b> · Học bổng đầu vào
              </span>
            </div>

            <div className="flex flex-col gap-6">
              {groups.map(({ group, items }) => (
                <div key={group}>
                  <div className="bg-sms-pill text-sms-pill-ink mb-3.5 inline-flex items-center rounded-full px-4 py-2 text-sm font-bold">
                    {group}
                  </div>
                  <div className="grid grid-cols-2 gap-3.5 md:grid-cols-4">
                    {items.map((vm) => (
                      <ProgramCard key={vm.name} code={code} vm={vm} />
                    ))}
                  </div>
                </div>
              ))}
            </div>
          </section>
        ) : (
          <section className="px-9 py-16 text-center">
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

        {/* Offers */}
        <section className="px-6 pb-14 lg:px-11">
          <div className="grid gap-4 md:grid-cols-3">
            {OFFERS.map((o) => (
              <div
                key={o.n}
                className="border-sms-100 rounded-2xl border bg-gradient-to-br from-[#f4f8ff] to-[#eaf1fd] p-6"
              >
                <div className="bg-sms-500 mb-3.5 flex h-11 w-11 items-center justify-center rounded-xl text-base font-extrabold text-white">
                  {o.n}
                </div>
                <div className="text-sms-700 mb-1.5 text-[17px] font-bold">
                  {o.t}
                </div>
                <div className="text-sms-ink-soft text-[13.5px] leading-relaxed">
                  {o.d}
                </div>
              </div>
            ))}
          </div>
        </section>

        {/* Testimonials */}
        <section className="bg-sms-surface-low px-6 py-12 lg:px-11">
          <h2 className="text-sms-700 mb-6 text-center text-2xl font-extrabold md:text-[28px]">
            Câu chuyện thành công
          </h2>
          <div className="grid gap-4 md:grid-cols-3">
            {TESTIMONIALS.map((t) => (
              <div
                key={t.name}
                className="border-sms-line bg-sms-card rounded-2xl border p-6"
              >
                <div className="mb-3.5 flex items-center gap-3">
                  <span
                    aria-hidden
                    className="border-sms-100 h-11 w-11 rounded-full border"
                    style={{
                      background:
                        "repeating-linear-gradient(135deg,#dbe7fb 0 8px,#eaf1fd 8px 16px)",
                    }}
                  />
                  <span className="leading-tight">
                    <span className="text-sms-ink-strong block text-sm font-bold">
                      {t.name}
                    </span>
                    <span className="text-sms-ink-muted block text-[11.5px]">
                      {t.role}
                    </span>
                  </span>
                </div>
                <p className="text-sms-ink-body text-sm leading-relaxed">
                  “{t.q}”
                </p>
              </div>
            ))}
          </div>
        </section>

        {/* Registration — CTA Gọi/Zalo THẬT (KHÔNG thu PII qua browser) */}
        <section id="reg" className="bg-sms-700 px-6 py-14 lg:px-11">
          <div className="grid items-center gap-10 md:grid-cols-2">
            <div className="text-white">
              <h2 className="text-2xl font-extrabold md:text-[32px]">
                Đăng ký ngay hôm nay
              </h2>
              <p className="mt-3 max-w-md text-[15px] leading-relaxed text-white/80">
                Gọi hotline để được đội ngũ tư vấn tuyển sinh hướng dẫn hồ sơ chi
                tiết. Hoàn toàn miễn phí.
              </p>
              <div className="mt-5 flex flex-col gap-3">
                {REG_CHECKLIST.map((c) => (
                  <div key={c} className="flex items-center gap-2.5 text-sm text-white/85">
                    <Check className="text-sms-gold-m3 h-4 w-4 shrink-0" /> {c}
                  </div>
                ))}
              </div>
            </div>

            <div className="bg-sms-card rounded-2xl p-6 shadow-xl">
              <CountdownCard />

              {/* CTA thật — không form PII */}
              <a
                href={SMS_HOTLINE_TEL}
                className="bg-sms-gold-m3 text-sms-gold-m3-ink flex items-center justify-center gap-2.5 rounded-xl py-4 text-base font-extrabold transition-opacity hover:opacity-90"
              >
                <Phone className="h-5 w-5" /> Gọi hotline {SMS_HOTLINE}
              </a>
              <ZaloLink className="border-sms-line text-sms-500 mt-2.5 flex items-center justify-center gap-2.5 rounded-xl border py-3.5 text-[15px] font-bold transition-colors hover:bg-sms-surface-low">
                <MessageCircle className="h-5 w-5" /> Chat Zalo tư vấn
              </ZaloLink>
              <p className="text-sms-ink-muted mt-3 text-center text-xs leading-relaxed">
                Tư vấn viên phản hồi trong vòng 24h.
              </p>
            </div>
          </div>
        </section>

        {/* Sticky bar ĐẶT TRONG <main> → tự bỏ ghim khi main kết thúc, KHÔNG che
            khối opt-out (NĐ91) + footer nằm SAU main ở cuối trang. */}
        <div className="border-sms-line bg-sms-card/95 sticky bottom-0 z-40 flex items-center justify-between gap-3 border-t px-5 py-3 shadow-[0_-6px_20px_rgba(11,61,145,.08)] backdrop-blur lg:px-11">
          <div className="text-sms-700 hidden text-sm font-bold sm:block">
            Sẵn sàng nhập học 2026?{" "}
            <span className="text-sms-ink-soft font-medium">
              Hạn nộp hồ sơ {ADMISSION_DEADLINE_LABEL}
            </span>
          </div>
          <div className="flex flex-1 items-center justify-end gap-2">
            <a
              href={SMS_HOTLINE_TEL}
              aria-label={`Gọi hotline ${SMS_HOTLINE}`}
              className="border-sms-100 text-sms-500 inline-flex items-center gap-1.5 rounded-lg border px-3.5 py-2.5 text-[13.5px] font-bold"
            >
              <Phone className="h-4 w-4" />{" "}
              <span className="hidden sm:inline">Hotline</span>
            </a>
            <ZaloLink
              ariaLabel="Chat Zalo tư vấn"
              className="inline-flex items-center gap-1.5 rounded-lg border border-[#b6d4ff] px-3.5 py-2.5 text-[13.5px] font-bold text-[#0068ff]"
            >
              <MessageCircle className="h-4 w-4" />{" "}
              <span className="hidden sm:inline">Zalo</span>
            </ZaloLink>
            <a
              href="#reg"
              className="bg-sms-500 rounded-lg px-4 py-2.5 text-[13.5px] font-bold text-white transition-opacity hover:opacity-90"
            >
              Đăng ký ngay
            </a>
          </div>
        </div>
      </main>

      {/* Consent + opt-out (NĐ91) */}
      <section className="bg-sms-surface-low border-sms-line border-t px-6 py-6 lg:px-11">
        <p className="text-sms-ink-soft mx-auto mb-3.5 max-w-3xl text-xs leading-relaxed">
          {data.consent_notice}
        </p>
        <div className="mx-auto max-w-md">
          {isOptedOut ? (
            <div className="flex items-center gap-2 rounded-xl border border-emerald-200 bg-emerald-50 px-3.5 py-3 text-sm font-medium text-emerald-800">
              <CheckCircle2 className="h-4 w-4 shrink-0 text-emerald-600" /> Đã hủy
              nhận tin từ {data.school_name}.
            </div>
          ) : (
            <AlertDialog>
              <AlertDialogTrigger asChild>
                <button
                  type="button"
                  disabled={optOut.isPending}
                  className="border-sms-line bg-sms-card text-sms-ink-soft hover:bg-sms-surface-low flex h-11 w-full items-center justify-center gap-2 rounded-xl border text-sm font-semibold transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sms-500 disabled:opacity-50"
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
            <p className="mt-2 text-center text-xs text-red-600">
              Không thể hủy lúc này. Vui lòng thử lại.
            </p>
          )}
        </div>
      </section>

      <SmsFooter schoolName={data.school_name} />
    </SmsPage>
  )
}
