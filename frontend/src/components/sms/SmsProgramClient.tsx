// src/components/sms/SmsProgramClient.tsx
"use client"

import Link from "next/link"
import { useQuery } from "@tanstack/react-query"
import {
  ArrowRight,
  Check,
  ChevronLeft,
  Clock,
  GraduationCap,
  HeartHandshake,
  MessageCircle,
  Phone,
  TrendingUp,
} from "lucide-react"

import { getSmsLanding } from "@/lib/api/sms"
import { useSmsDwellTracker } from "@/hooks/useSmsDwellTracker"

import { programGlyph } from "./programIcon"
import {
  DiscountBadge,
  HeroImage,
  SmsErrorCard,
  SmsFooter,
  SmsHeader,
  SmsPage,
  ZaloLink,
} from "./SmsChrome"
import { dedupeByName } from "./smsPrograms"
import {
  ADMISSION_DEADLINE_LABEL,
  GENERIC_CONSIDER_IF,
  GENERIC_FAQ,
  GENERIC_GOOD_IF,
  GENERIC_TRENDS,
  isStrongTuition,
  programEditorial,
  programTuition,
  SMS_HOTLINE_TEL,
  tuitionLevelLabel,
  tuitionTier,
} from "./smsContent"

/**
 * Landing tuyển sinh tier-2 (trang ngành — nơi ĐO CHÍNH dwell). IDENTITY ngành
 * (tên/trình độ/mã) THẬT từ BE (`useSmsDwellTracker` đo theo majorProgramId);
 * nội dung (tagline/giới thiệu/môn học/nghề) là EDITORIAL (smsContent). Thu lead
 * = CTA Gọi/Zalo THẬT + nút "Đăng ký ngành này" cuộn về khối #reg của tier-1
 * (KHÔNG thu PII qua browser — nối intake sau khi có OK pháp lý §16.9).
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

  if (isLoading) {
    return (
      <SmsPage>
        <div role="status" aria-label="Đang tải" className="animate-pulse">
          <div className="border-sms-line flex items-center justify-between border-b px-5 py-4 lg:px-11">
            <div className="bg-sms-surface-alt h-10 w-40 rounded-lg" />
          </div>
          <div className="grid gap-9 px-6 py-8 md:grid-cols-2 lg:px-11">
            <div className="space-y-4">
              <div className="bg-sms-surface-alt h-6 w-32 rounded" />
              <div className="bg-sms-surface-alt h-10 w-2/3 rounded" />
              <div className="bg-sms-surface-alt h-20 w-full rounded" />
            </div>
            <div className="bg-sms-surface-alt hidden h-64 rounded-2xl md:block" />
          </div>
        </div>
      </SmsPage>
    )
  }

  if (isError || !data || !program) {
    return (
      <SmsPage>
        <SmsErrorCard
          title="Không tìm thấy ngành"
          message="Ngành không tồn tại hoặc liên kết đã hết hạn."
          action={
            <Link
              href={`/lp/${encodeURIComponent(code)}`}
              className="bg-sms-500 hover:bg-sms-700 flex h-11 items-center justify-center gap-2 rounded-xl px-5 text-sm font-semibold text-white transition-colors"
            >
              <ChevronLeft className="h-4 w-4" /> Về danh mục ngành
            </Link>
          }
        />
      </SmsPage>
    )
  }

  const ed = programEditorial(program.name)
  const Icon = programGlyph(program.name).Icon // member access, không call trực tiếp
  const regHref = `/lp/${encodeURIComponent(code)}#reg`
  // 4 khối mới: dùng nội dung riêng nếu có, không thì fallback generic (mọi
  // ngành vẫn trả lời đủ "có hợp không / xu hướng / FAQ").
  const goodIf = ed.goodIf ?? GENERIC_GOOD_IF
  const considerIf = ed.considerIf ?? GENERIC_CONSIDER_IF
  const trends = ed.trends ?? GENERIC_TRENDS
  const faq = ed.faq ?? GENERIC_FAQ
  // Học phí THẬT theo mã ngành (null → khối generic fallback).
  const tuition = programTuition(program.code)
  // Badge/TL;DR/sidebar suy TỪ HỌC PHÍ THẬT (không từ is_heavy): miễn 100% (hệ
  // TC/THCS) → giảm 70% → ưu đãi 30%.
  const tuitionLevel = tuitionTier(program.code)
  const policyValue = tuitionLevelLabel(tuitionLevel, "card")
  const strongTuition = isStrongTuition(tuitionLevel)
  // "Ngành khác": KHỬ TRÙNG theo tên (biến thể CĐ/TC cùng tên = 1 mục), loại
  // ngành hiện tại, lấy tối đa 4 tên khác nhau (link tới biến thể đầu gặp).
  const others = dedupeByName(data.programs, [program.name]).slice(0, 4)

  return (
    <SmsPage>
      <SmsHeader
        schoolName={data.school_name}
        homeHref={`/lp/${encodeURIComponent(code)}`}
        registerHref={regHref}
      />

      {/* Breadcrumb */}
      <nav className="text-sms-ink-muted px-6 pt-4 text-[13px] lg:px-11">
        <Link href={`/lp/${encodeURIComponent(code)}`} className="text-sms-500">
          Trang chủ
        </Link>
        <span className="mx-2">›</span>
        <Link
          href={`/lp/${encodeURIComponent(code)}#prog`}
          className="text-sms-500"
        >
          Ngành đào tạo
        </Link>
        <span className="mx-2">›</span>
        <span className="text-sms-ink-soft">{program.name}</span>
      </nav>

      <main>
      {/* Hero */}
      <section className="grid items-center gap-9 px-6 pb-10 pt-6 md:grid-cols-[1.1fr_.9fr] lg:px-11">
        <div>
          <div className="mb-3.5 flex flex-wrap items-center gap-2.5">
            <span className="bg-sms-pill text-sms-pill-ink rounded-full px-3 py-1.5 text-[12.5px] font-bold">
              {ed.group}
            </span>
            <DiscountBadge level={tuitionLevel} size="hero" />
            <span className="text-sms-ink-muted text-[12.5px] font-medium">
              Mã ngành: {program.code}
            </span>
          </div>
          <h1 className="text-sms-700 text-3xl font-extrabold leading-[1.12] md:text-[40px]">
            {program.name}
          </h1>
          <p className="text-sms-ink-body mt-3.5 max-w-xl text-base leading-relaxed">
            {ed.tagline}
          </p>
          <div className="mt-5 flex flex-wrap gap-3">
            <Link
              href={regHref}
              className="bg-sms-gold-m3 text-sms-gold-m3-ink inline-flex items-center gap-2 rounded-xl px-6 py-3.5 text-[15px] font-extrabold transition-opacity hover:opacity-90"
            >
              Đăng ký ngành này <ArrowRight className="h-4 w-4" />
            </Link>
            <a
              href={SMS_HOTLINE_TEL}
              className="bg-sms-pill text-sms-500 inline-flex items-center gap-2 rounded-xl px-5 py-3.5 text-[15px] font-bold transition-opacity hover:opacity-90"
            >
              <Phone className="h-4 w-4" /> Tư vấn
            </a>
          </div>
        </div>
        <div className="border-sms-line relative h-[220px] overflow-hidden rounded-2xl border md:h-[280px]">
          <HeroImage
            src={ed.image}
            alt={`Sinh viên ngành ${program.name} — ${data.school_name}`}
            fallback={
              <>
                <div
                  aria-hidden
                  className="h-full w-full"
                  style={{
                    background:
                      "repeating-linear-gradient(135deg,#e6edf9 0 14px,#f2f5fb 14px 28px)",
                  }}
                />
                <Icon
                  aria-hidden
                  strokeWidth={1.25}
                  className="text-sms-500 absolute -right-6 -top-6 h-40 w-40 opacity-[0.12]"
                />
              </>
            }
          />
          <span className="absolute inset-x-0 bottom-0 bg-gradient-to-t from-black/55 to-transparent p-4 text-[13px] font-semibold text-white">
            Cơ sở vật chất hiện đại — học đi đôi với thực hành
          </span>
        </div>
      </section>

      {/* Trong 30 giây — TL;DR quét nhanh */}
      <section className="px-6 pb-10 lg:px-11">
        <div className="grid grid-cols-2 gap-3.5 md:grid-cols-4">
          {[
            { label: "Trình độ", value: program.degree_level },
            { label: "Thời gian đào tạo", value: ed.duration },
            { label: "Hình thức xét tuyển", value: "Xét học bạ THPT" },
            {
              label: "Ưu đãi học phí",
              value: policyValue,
              flame: strongTuition,
            },
          ].map((f) => (
            <div
              key={f.label}
              className="bg-sms-surface-alt border-sms-line rounded-xl border px-5 py-4"
            >
              <div className="text-sms-ink-muted mb-1 text-xs">{f.label}</div>
              <div
                className={`text-[15px] font-bold ${
                  f.flame ? "text-sms-flame-accent" : "text-sms-ink-strong"
                }`}
              >
                {f.value}
              </div>
            </div>
          ))}
        </div>
      </section>

      {/* Body 2 cột */}
      <section className="grid items-start gap-10 px-6 pb-12 lg:grid-cols-[1.5fr_1fr] lg:px-11">
        <div>
          <h2 className="text-sms-700 mb-3 text-xl font-extrabold md:text-[22px]">
            Giới thiệu ngành
          </h2>
          <p className="text-sms-ink-body mb-7 text-[15px] leading-[1.75]">
            {ed.intro}
          </p>

          <h2 className="text-sms-700 mb-3.5 text-xl font-extrabold md:text-[22px]">
            Bạn sẽ được học gì?
          </h2>
          <div className="mb-7 flex flex-col gap-2.5">
            {ed.subjects.map((s) => (
              <div
                key={s}
                className="bg-sms-surface-alt border-sms-line flex items-start gap-3 rounded-lg border px-4 py-3"
              >
                <span className="bg-sms-500 mt-0.5 flex h-[22px] w-[22px] shrink-0 items-center justify-center rounded-md text-white">
                  <Check className="h-3.5 w-3.5" strokeWidth={3} />
                </span>
                <span className="text-[14.5px] leading-snug text-[#28324a]">
                  {s}
                </span>
              </div>
            ))}
          </div>

          <h2 className="text-sms-700 mb-3.5 text-xl font-extrabold md:text-[22px]">
            Cơ hội nghề nghiệp
          </h2>
          <div className="grid gap-3 sm:grid-cols-2">
            {ed.careers.map((c) => (
              <div
                key={c}
                className="border-sms-line flex items-center gap-2.5 rounded-lg border px-4 py-3"
              >
                <span className="bg-sms-flame-accent h-2 w-2 shrink-0 rounded-full" />
                <span className="text-sm text-[#28324a]">{c}</span>
              </div>
            ))}
          </div>
        </div>

        {/* Sidebar sticky */}
        <aside className="flex flex-col gap-4 self-start lg:sticky lg:top-5">
          <div className="from-sms-700 to-sms-500 rounded-2xl bg-gradient-to-br p-6 text-white">
            <div className="text-lg font-extrabold">Quan tâm ngành này?</div>
            <p className="mt-1.5 text-[13.5px] leading-relaxed text-white/80">
              Gọi hotline để được tư vấn — hướng dẫn hồ sơ chi tiết, hoàn toàn
              miễn phí.
            </p>
            <Link
              href={regHref}
              className="bg-sms-gold-m3 text-sms-gold-m3-ink mt-4 block rounded-xl py-3.5 text-center text-[15px] font-extrabold transition-opacity hover:opacity-90"
            >
              Đăng ký xét tuyển
            </Link>
            <div className="mt-2.5 flex gap-2">
              <a
                href={SMS_HOTLINE_TEL}
                className="inline-flex flex-1 items-center justify-center gap-1.5 rounded-lg border border-white/25 bg-white/15 py-3 text-[13px] font-bold text-white transition-colors hover:bg-white/25"
              >
                <Phone className="h-4 w-4" /> Hotline
              </a>
              <ZaloLink className="inline-flex flex-1 items-center justify-center gap-1.5 rounded-lg border border-white/25 bg-white/15 py-3 text-[13px] font-bold text-white transition-colors hover:bg-white/25">
                <MessageCircle className="h-4 w-4" /> Zalo
              </ZaloLink>
            </div>
          </div>
          <div className="from-[#fff7e0] to-[#ffeec2] border-sms-gold-line rounded-2xl border bg-gradient-to-br px-5 py-4">
            <div className="text-sms-gold-ink flex items-center gap-2 text-sm font-bold">
              <Clock className="h-4 w-4" /> Ưu đãi có hạn
            </div>
            <p className="mt-1.5 text-[13px] leading-relaxed text-[#9a7b3a]">
              <b className="text-[#b8560f]">
                {tuitionLevelLabel(tuitionLevel, "hero")}
              </b>{" "}
              áp dụng cho hồ sơ đăng ký trước{" "}
              <b className="text-[#b8560f]">{ADMISSION_DEADLINE_LABEL}</b>.
            </p>
          </div>
        </aside>
      </section>

      {/* Mình có phù hợp không? */}
      <section className="bg-sms-surface-low border-sms-line border-t px-6 py-12 lg:px-11">
        <div className="mb-6 flex items-center gap-2.5">
          <span className="bg-sms-pill text-sms-pill-ink flex h-9 w-9 items-center justify-center rounded-xl">
            <HeartHandshake className="h-5 w-5" />
          </span>
          <h2 className="text-sms-700 text-xl font-extrabold md:text-[22px]">
            Ngành này có hợp với bạn không?
          </h2>
        </div>
        <div className="grid gap-4 md:grid-cols-2">
          <div className="border-sms-line bg-sms-card rounded-2xl border p-6">
            <div className="mb-3 text-sm font-bold text-[#167a53]">
              Hợp nếu bạn…
            </div>
            <div className="flex flex-col gap-2.5">
              {goodIf.map((g) => (
                <div key={g} className="flex items-start gap-2.5">
                  <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-md bg-[#e2f4ec] text-[#167a53]">
                    <Check className="h-3.5 w-3.5" strokeWidth={3} />
                  </span>
                  <span className="text-[14px] leading-snug text-[#28324a]">
                    {g}
                  </span>
                </div>
              ))}
            </div>
          </div>
          <div className="border-sms-line bg-sms-card rounded-2xl border p-6">
            <div className="text-sms-flame-accent mb-3 text-sm font-bold">
              Cân nhắc nếu bạn…
            </div>
            <div className="flex flex-col gap-2.5">
              {considerIf.map((c) => (
                <div key={c} className="flex items-start gap-2.5">
                  <span className="bg-sms-flame-accent mt-2 h-1.5 w-1.5 shrink-0 rounded-full" />
                  <span className="text-[14px] leading-snug text-[#28324a]">
                    {c}
                  </span>
                </div>
              ))}
            </div>
          </div>
        </div>
      </section>

      {/* Xu hướng việc làm */}
      <section className="px-6 py-12 lg:px-11">
        <div className="mb-6 flex items-center gap-2.5">
          <span className="bg-sms-pill text-sms-pill-ink flex h-9 w-9 items-center justify-center rounded-xl">
            <TrendingUp className="h-5 w-5" />
          </span>
          <h2 className="text-sms-700 text-xl font-extrabold md:text-[22px]">
            Xu hướng việc làm
          </h2>
        </div>
        <div className="grid gap-3 sm:grid-cols-2">
          {trends.map((t) => (
            <div
              key={t}
              className="border-sms-line bg-sms-surface-alt flex items-start gap-3 rounded-xl border px-4 py-3.5"
            >
              <TrendingUp className="text-sms-500 mt-0.5 h-4 w-4 shrink-0" />
              <span className="text-[14px] leading-snug text-[#28324a]">{t}</span>
            </div>
          ))}
        </div>
      </section>

      {/* Học phí & hỗ trợ */}
      <section className="bg-sms-surface-low border-sms-line border-t px-6 py-12 lg:px-11">
        <div className="mb-6 flex items-center gap-2.5">
          <span className="bg-sms-pill text-sms-pill-ink flex h-9 w-9 items-center justify-center rounded-xl">
            <GraduationCap className="h-5 w-5" />
          </span>
          <h2 className="text-sms-700 text-xl font-extrabold md:text-[22px]">
            Học phí & hỗ trợ
          </h2>
        </div>
        <div className="grid gap-4 md:grid-cols-2">
          <div className="border-sms-line bg-sms-card flex flex-col gap-3 rounded-2xl border p-6">
            {tuition ? (
              <>
                <div className="border-sms-line flex items-baseline justify-between border-b pb-2.5">
                  <span className="text-sms-ink-soft text-[13px]">
                    Tổng học phí toàn khóa
                  </span>
                  <span className="text-sms-ink-strong text-[15px] font-bold tabular-nums">
                    {tuition.total}
                  </span>
                </div>
                <div className="flex flex-col gap-2.5">
                  {tuition.tiers.map((t) => {
                    const free = t.kind === "free"
                    const fullPrice = t.kind === "none"
                    return (
                      <div
                        key={t.label}
                        className={`rounded-xl p-3.5 ${
                          free
                            ? "from-sms-flame-from to-sms-flame-to bg-gradient-to-br text-white"
                            : "bg-sms-surface-alt border-sms-line border"
                        }`}
                      >
                        <div className="flex items-baseline justify-between gap-3">
                          <span
                            className={`text-[13px] font-semibold ${free ? "text-white/90" : "text-sms-ink-soft"}`}
                          >
                            {t.label}
                          </span>
                          <span
                            className={`text-[18px] font-extrabold tabular-nums ${
                              free
                                ? "text-white"
                                : fullPrice
                                  ? "text-sms-ink-strong"
                                  : "text-sms-flame-accent"
                            }`}
                          >
                            {t.pay}
                          </span>
                        </div>
                        <div
                          className={`mt-0.5 text-[12px] leading-snug ${free ? "text-white/85" : "text-sms-ink-muted"}`}
                        >
                          {t.note}
                        </div>
                      </div>
                    )
                  })}
                </div>
              </>
            ) : (
              <div className="bg-sms-gold-soft border-sms-gold-line rounded-xl border p-4">
                <div className="text-sms-gold-ink text-[15px] font-extrabold">
                  Học bổng đầu vào đến 100% kỳ I
                </div>
                <div className="text-sms-gold-ink mt-1 text-[13px] leading-relaxed opacity-90">
                  Dành cho thí sinh điểm cao và diện hộ nghèo, cận nghèo.
                </div>
              </div>
            )}
            <div className="text-sms-ink-body flex flex-col gap-2 text-[13.5px]">
              <div className="flex items-start gap-2.5">
                <Check className="text-sms-500 mt-0.5 h-4 w-4 shrink-0" />
                Miễn giảm học phí theo chính sách hộ nghèo, dân tộc thiểu số.
              </div>
              <div className="flex items-start gap-2.5">
                <Check className="text-sms-500 mt-0.5 h-4 w-4 shrink-0" />
                Đóng học phí theo kỳ; hỗ trợ trả góp cho hoàn cảnh khó khăn.
              </div>
            </div>
          </div>
          <div className="border-sms-line bg-sms-card rounded-2xl border p-6">
            <div className="text-sms-ink-strong mb-1.5 text-[15px] font-bold">
              Mức lương & doanh nghiệp đối tác
            </div>
            <p className="text-sms-ink-soft text-[13.5px] leading-relaxed">
              Mức thu nhập tham khảo và danh sách doanh nghiệp đối tác tuyển dụng
              của ngành thay đổi theo từng kỳ. Gọi hotline để được cung cấp con
              số và cam kết việc làm cụ thể, cập nhật nhất.
            </p>
            <a
              href={SMS_HOTLINE_TEL}
              className="bg-sms-pill text-sms-500 mt-4 inline-flex items-center gap-2 rounded-xl px-5 py-3 text-[14px] font-bold transition-opacity hover:opacity-90"
            >
              <Phone className="h-4 w-4" /> Gọi để biết mức lương & việc làm
            </a>
          </div>
        </div>
      </section>

      {/* Hỏi – Đáp */}
      <section className="px-6 py-12 lg:px-11">
        <h2 className="text-sms-700 mb-6 text-xl font-extrabold md:text-[22px]">
          Hỏi – Đáp
        </h2>
        <div className="flex flex-col gap-3">
          {faq.map((f) => (
            <div
              key={f.q}
              className="border-sms-line bg-sms-card rounded-2xl border p-5"
            >
              <div className="text-sms-ink-strong mb-1.5 text-[15px] font-bold">
                {f.q}
              </div>
              <p className="text-sms-ink-body text-[14px] leading-relaxed">
                {f.a}
              </p>
            </div>
          ))}
        </div>
      </section>

      {/* Ngành khác */}
      {others.length > 0 && (
        <section className="bg-sms-surface-low border-sms-line border-t px-6 py-10 lg:px-11">
          <h2 className="text-sms-700 mb-5 text-xl font-extrabold md:text-[22px]">
            Các ngành khác
          </h2>
          <div className="grid grid-cols-2 gap-3.5 md:grid-cols-4">
            {others.map((o) => (
              <Link
                key={o.id}
                href={`/lp/${encodeURIComponent(code)}/nganh/${o.id}`}
                className="border-sms-line bg-sms-card hover:border-sms-500 block rounded-xl border p-4 transition-all hover:shadow-md"
              >
                <div className="text-sms-ink-muted mb-1.5 text-[11.5px]">
                  {programEditorial(o.name).group}
                </div>
                <div className="text-sms-ink-strong text-[14.5px] font-semibold leading-tight">
                  {o.name}
                </div>
                <div className="text-sms-500 mt-2 text-[12px] font-semibold">
                  Xem chi tiết →
                </div>
              </Link>
            ))}
          </div>
        </section>
      )}
      </main>

      {/* Consent + footer */}
      <p className="text-sms-ink-muted bg-sms-surface-low border-sms-line border-t px-6 py-5 text-center text-xs leading-relaxed lg:px-11">
        {data.consent_notice}
      </p>
      <SmsFooter schoolName={data.school_name} />
    </SmsPage>
  )
}
