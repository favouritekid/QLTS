import Link from "next/link"
import { ArrowRight, BadgePercent, CreditCard, Landmark, WalletCards } from "lucide-react"

import { Button } from "@/components/ui/button"
import {
  DemoImage,
  PublicAdmissionsPageHero,
  PublicAdmissionsShell,
  SectionHeading,
  pageShellClass,
} from "@/components/public/PublicAdmissionsShell"
import {
  publicAdmissionsMedia,
  publicCostFaq,
  publicPaymentSteps,
  publicScholarshipPolicies,
  publicTuitionBands,
} from "@/lib/public-admissions/site"
import type {
  PublicAdmissionsMoney,
  PublicAdmissionsTuitionResponse,
} from "@/types/public-admissions.types"

interface PublicTuitionAidPageProps {
  catalog?: PublicAdmissionsTuitionResponse | null
}

function normalizeMoney(value: PublicAdmissionsMoney): number | null {
  if (value === null || value === undefined || value === "") {
    return null
  }

  const parsed = typeof value === "number" ? value : Number(value)
  return Number.isFinite(parsed) ? parsed : null
}

function formatCurrency(value: PublicAdmissionsMoney): string | null {
  const normalized = normalizeMoney(value)
  if (normalized === null) {
    return null
  }

  return new Intl.NumberFormat("vi-VN", {
    style: "currency",
    currency: "VND",
    maximumFractionDigits: 0,
  }).format(normalized)
}

function formatRange(min: PublicAdmissionsMoney, max: PublicAdmissionsMoney): string | null {
  const normalizedMin = normalizeMoney(min)
  const normalizedMax = normalizeMoney(max)

  if (normalizedMin === null && normalizedMax === null) {
    return null
  }

  if (normalizedMin !== null && normalizedMax !== null) {
    if (normalizedMin === normalizedMax) {
      return formatCurrency(normalizedMin)
    }
    return `${formatCurrency(normalizedMin)} - ${formatCurrency(normalizedMax)}`
  }

  return formatCurrency(normalizedMin ?? normalizedMax)
}

function formatYears(years: number[]): string {
  if (years.length === 0) {
    return "Đang cập nhật"
  }

  const orderedYears = [...years].sort((a, b) => b - a)
  return orderedYears.length === 1 ? `Năm ${orderedYears[0]}` : `${orderedYears[orderedYears.length - 1]} - ${orderedYears[0]}`
}

function formatDiscountValue(type: string, value: PublicAdmissionsMoney): string {
  const normalized = normalizeMoney(value)
  if (normalized === null) {
    return "Đang cập nhật"
  }

  if (type === "percentage") {
    return `${normalized}%`
  }

  return formatCurrency(normalized) ?? "Đang cập nhật"
}

function formatValidityRange(validFrom: string | null, validTo: string | null): string {
  if (!validFrom && !validTo) {
    return "Không giới hạn thời gian hiệu lực"
  }

  if (validFrom && validTo) {
    return `Hiệu lực ${validFrom} - ${validTo}`
  }

  if (validFrom) {
    return `Hiệu lực từ ${validFrom}`
  }

  return `Hiệu lực đến ${validTo}`
}

export default function PublicTuitionAidPage({ catalog }: PublicTuitionAidPageProps) {
  const liveCatalog = catalog && (catalog.degree_levels.length > 0 || catalog.offerings.length > 0) ? catalog : null
  const liveDegreeLevels = liveCatalog?.degree_levels ?? []
  const livePolicies = liveCatalog?.discount_policies ?? []

  const samplesByDegreeLevel = new Map<string, string[]>()
  if (liveCatalog) {
    for (const item of liveCatalog.offerings) {
      const current = samplesByDegreeLevel.get(item.degree_level) ?? []
      const label = `${item.program_name} (${item.offering_type})`
      if (!current.includes(label) && current.length < 4) {
        current.push(label)
      }
      samplesByDegreeLevel.set(item.degree_level, current)
    }
  }

  const heroHighlights = liveCatalog
    ? [
        `${liveCatalog.summary.offering_count} hệ đào tạo có học phí public`,
        `${liveCatalog.summary.policy_count} chính sách ưu đãi active`,
        liveCatalog.summary.latest_academic_year
          ? `Dữ liệu năm ${liveCatalog.summary.latest_academic_year}`
          : "Dữ liệu tài chính public",
      ]
    : ["Khung học phí tham chiếu", "Học bổng đầu vào", "Mốc giữ chỗ và thanh toán"]

  return (
    <PublicAdmissionsShell activePath="/tuyen-sinh/hoc-phi-hoc-bong">
      <PublicAdmissionsPageHero
        eyebrow="Fees & Aid"
        title="Xem khung học phí, học bổng đầu vào và lộ trình thanh toán"
        description="Phụ huynh và thí sinh thường muốn thấy chi phí học tập ở ngay tầng thông tin đầu tiên. Trang này gom mức học phí tham chiếu, chính sách học bổng và các mốc thanh toán quan trọng trên cùng một luồng."
        asset="scholarshipAward"
        captionTitle={
          liveCatalog
            ? "Học phí và chính sách ưu đãi đang áp dụng cho năm tuyển sinh hiện hành"
            : "Thông tin học phí và hỗ trợ tài chính tham khảo"
        }
        captionDescription={
          liveCatalog
            ? "Mức học phí theo hệ đào tạo và các chính sách giảm học phí, học bổng đang được áp dụng cho các chương trình đã công bố."
            : "Danh mục đang được cập nhật. Vui lòng quay lại sau hoặc liên hệ phòng tuyển sinh để biết thêm chi tiết."
        }
        highlights={heroHighlights}
        actions={[
          { label: "Xem ngành học", href: "/tuyen-sinh/nganh-hoc" },
          { label: "Xem phương thức", href: "/tuyen-sinh/phuong-thuc", variant: "outline" },
        ]}
      />

      <section className="py-12 sm:py-20">
        <div className={`${pageShellClass} space-y-8 sm:space-y-10`}>
          <SectionHeading
            eyebrow={liveDegreeLevels.length > 0 ? "Live Tuition" : "Tuition"}
            title={
              liveDegreeLevels.length > 0
                ? "Khung học phí đang công bố theo bậc học"
                : "Khung học phí nên được chia theo cụm chương trình để dễ đọc"
            }
            description={
              liveDegreeLevels.length > 0
                ? "Khối này đang lấy từ OfferingAcademicInfo đã publish. Người dùng sẽ thấy khoảng học phí theo bậc học, số hệ đào tạo đang mở và một vài ví dụ chương trình đang hiện trên public portal."
                : "Ở public site, mục tiêu không phải thay thế bảng học phí chi tiết của backend. Mục tiêu là giúp người xem có kỳ vọng đúng về mặt chi phí trước khi đi sâu vào từng chương trình."
            }
          />

          {liveDegreeLevels.length > 0 ? (
            <div className="grid gap-4 xl:grid-cols-2">
              {liveDegreeLevels.map((band) => {
                const samplePrograms = samplesByDegreeLevel.get(band.degree_level) ?? []

                return (
                  <article
                    key={band.degree_level}
                    className="rounded-[24px] border border-border/70 bg-card p-5 shadow-sm sm:p-6"
                  >
                    <div className="flex items-start justify-between gap-4">
                      <div className="flex size-11 items-center justify-center rounded-2xl bg-info-50 text-info-700 sm:size-12">
                        <WalletCards className="size-5" />
                      </div>
                      <span className="rounded-full bg-warning-50 px-3 py-1 text-xs font-semibold text-warning-700">
                        {formatRange(band.semester_1_tuition_min ?? band.tuition_min, band.semester_1_tuition_max ?? band.tuition_max) ?? "Đang cập nhật"}
                      </span>
                    </div>

                    <h3 className="mt-4 text-xl font-semibold tracking-tight font-display">{band.degree_level}</h3>
                    <p className="mt-3 text-sm leading-6 text-muted-foreground">
                      {band.published_offering_count} hệ đào tạo đang công bố học phí public. Phạm vi dữ liệu: {formatYears(band.academic_years)}.
                    </p>

                    <ul className="mt-5 space-y-3">
                      <li className="flex items-start gap-3 text-sm text-foreground">
                        <span className="mt-1 size-2 rounded-full bg-success" />
                        <span className="leading-6">
                          Khoảng học phí hiện có: {formatRange(band.semester_1_tuition_min ?? band.tuition_min, band.semester_1_tuition_max ?? band.tuition_max) ?? "Đang cập nhật"}
                        </span>
                      </li>
                      <li className="flex items-start gap-3 text-sm text-foreground">
                        <span className="mt-1 size-2 rounded-full bg-success" />
                        <span className="leading-6">Số hệ đào tạo đang hiển thị: {band.published_offering_count}</span>
                      </li>
                      {samplePrograms.length > 0 ? (
                        <li className="flex items-start gap-3 text-sm text-foreground">
                          <span className="mt-1 size-2 rounded-full bg-success" />
                          <span className="leading-6">Ví dụ chương trình: {samplePrograms.join(", ")}</span>
                        </li>
                      ) : null}
                    </ul>
                  </article>
                )
              })}
            </div>
          ) : (
            <div className="grid gap-4 xl:grid-cols-2">
              {publicTuitionBands.map((band) => (
                <article
                  key={band.title}
                  className="rounded-[24px] border border-border/70 bg-card p-5 shadow-sm sm:p-6"
                >
                  <div className="flex items-start justify-between gap-4">
                    <div className="flex size-11 items-center justify-center rounded-2xl bg-info-50 text-info-700 sm:size-12">
                      <WalletCards className="size-5" />
                    </div>
                    <span className="rounded-full bg-warning-50 px-3 py-1 text-xs font-semibold text-warning-700">
                      {band.range}
                    </span>
                  </div>

                  <h3 className="mt-4 text-xl font-semibold tracking-tight font-display">{band.title}</h3>
                  <p className="mt-3 text-sm leading-6 text-muted-foreground">{band.note}</p>

                  <ul className="mt-5 space-y-3">
                    {band.includes.map((item) => (
                      <li key={item} className="flex items-start gap-3 text-sm text-foreground">
                        <span className="mt-1 size-2 rounded-full bg-success" />
                        <span className="leading-6">{item}</span>
                      </li>
                    ))}
                  </ul>
                </article>
              ))}
            </div>
          )}
        </div>
      </section>

      <section className="border-y border-border/70 bg-gradient-to-b from-background to-info-50/45 py-12 sm:py-20">
        <div className={`${pageShellClass} space-y-8 sm:space-y-10`}>
          <SectionHeading
            eyebrow={livePolicies.length > 0 ? "Live Policies" : "Scholarships"}
            title={
              livePolicies.length > 0
                ? "Chính sách ưu đãi học phí đang áp dụng"
                : "Học bổng đầu vào và hỗ trợ tài chính"
            }
            description={
              livePolicies.length > 0
                ? "Các chính sách giảm học phí và học bổng đang được áp dụng cho các chương trình đã công bố tuyển sinh."
                : "Thông tin học bổng, miễn giảm và hỗ trợ tài chính giúp phụ huynh và thí sinh dễ cân đối chi phí học tập."
            }
          />

          {livePolicies.length > 0 ? (
            <div className="grid gap-4 lg:grid-cols-3">
              {livePolicies.map((policy, index) => (
                <article
                  key={policy.id}
                  className="rounded-[20px] border border-border/70 bg-card p-5 shadow-sm sm:rounded-[24px] sm:p-6"
                >
                  <div className="flex items-center justify-between gap-4">
                    <div className="flex size-11 items-center justify-center rounded-2xl bg-success-50 text-success-700 sm:size-12">
                      {index % 3 === 0 ? <BadgePercent className="size-5" /> : index % 3 === 1 ? <Landmark className="size-5" /> : <CreditCard className="size-5" />}
                    </div>
                    <span className="text-sm font-semibold text-primary">
                      {formatDiscountValue(policy.discount_type, policy.discount_value)}
                    </span>
                  </div>

                  <h3 className="mt-4 text-lg font-semibold tracking-tight font-display sm:text-xl">{policy.name}</h3>
                  <p className="mt-3 text-sm leading-6 text-muted-foreground">
                    {policy.description || `Mã chính sách ${policy.code} đang được tham chiếu bởi học phí public.`}
                  </p>

                  <ul className="mt-5 space-y-3">
                    <li className="flex items-start gap-3 text-sm text-foreground">
                      <span className="mt-1 size-2 rounded-full bg-success" />
                      <span className="leading-6">{formatValidityRange(policy.valid_from, policy.valid_to)}</span>
                    </li>
                    <li className="flex items-start gap-3 text-sm text-foreground">
                      <span className="mt-1 size-2 rounded-full bg-success" />
                      <span className="leading-6">{policy.is_stackable ? "Có thể cộng dồn với ưu đãi khác" : "Không cộng dồn với ưu đãi khác"}</span>
                    </li>
                    <li className="flex items-start gap-3 text-sm text-foreground">
                      <span className="mt-1 size-2 rounded-full bg-success" />
                      <span className="leading-6">Ưu tiên áp dụng: mức {policy.priority}</span>
                    </li>
                  </ul>
                </article>
              ))}
            </div>
          ) : (
            <div className="grid gap-4 lg:grid-cols-3">
              {publicScholarshipPolicies.map((policy, index) => (
                <article
                  key={policy.title}
                  className="rounded-[20px] border border-border/70 bg-card p-5 shadow-sm sm:rounded-[24px] sm:p-6"
                >
                  <div className="flex items-center justify-between gap-4">
                    <div className="flex size-11 items-center justify-center rounded-2xl bg-success-50 text-success-700 sm:size-12">
                      {index === 0 ? <BadgePercent className="size-5" /> : index === 1 ? <Landmark className="size-5" /> : <CreditCard className="size-5" />}
                    </div>
                    <span className="text-sm font-semibold text-primary">{policy.value}</span>
                  </div>

                  <h3 className="mt-4 text-lg font-semibold tracking-tight font-display sm:text-xl">{policy.title}</h3>
                  <p className="mt-3 text-sm leading-6 text-muted-foreground">{policy.criteria}</p>

                  <ul className="mt-5 space-y-3">
                    {policy.notes.map((note) => (
                      <li key={note} className="flex items-start gap-3 text-sm text-foreground">
                        <span className="mt-1 size-2 rounded-full bg-success" />
                        <span className="leading-6">{note}</span>
                      </li>
                    ))}
                  </ul>
                </article>
              ))}
            </div>
          )}
        </div>
      </section>

      <section className="py-12 sm:py-20">
        <div className={`${pageShellClass} space-y-8 sm:space-y-10`}>
          <SectionHeading
            eyebrow="Payment Journey"
            title="Mốc chi phí nên được kể như một hành trình, không phải một khối văn bản"
            description="Các mốc thanh toán quan trọng từ xác nhận nhập học đến hoàn tất học phí theo từng kỳ."
          />

          <div className="grid gap-4 lg:grid-cols-4">
            {publicPaymentSteps.map((step, index) => (
              <article
                key={step.title}
                className="rounded-[20px] border border-border/70 bg-card p-5 shadow-sm sm:rounded-[24px] sm:p-6"
              >
                <div className="flex items-center justify-between gap-4">
                  <span className="rounded-full bg-primary/10 px-3 py-1 text-xs font-semibold uppercase tracking-[0.18em] text-primary">
                    0{index + 1}
                  </span>
                  <span className="text-sm font-medium text-muted-foreground">{step.timing}</span>
                </div>
                <h3 className="mt-4 text-lg font-semibold tracking-tight font-display sm:text-xl">{step.title}</h3>
                <p className="mt-3 text-sm leading-6 text-muted-foreground">{step.description}</p>
              </article>
            ))}
          </div>
        </div>
      </section>

      <section className="border-t border-border/70 bg-gradient-to-b from-background to-warning-50/50 py-12 sm:py-20">
        <div className={`${pageShellClass} grid gap-6 lg:grid-cols-[0.9fr_1.1fr]`}>
          <article className="overflow-hidden rounded-[24px] border border-border/70 bg-card shadow-sm">
            <DemoImage asset={publicAdmissionsMedia.heroCampus} className="aspect-[4/3] w-full object-cover" />
          </article>

          <div className="space-y-6">
            <article className="rounded-[24px] border border-border/70 bg-card p-6 shadow-sm">
              <p className="text-sm font-semibold uppercase tracking-[0.2em] text-primary">Common Questions</p>
              <div className="mt-4 space-y-4">
                {publicCostFaq.map((item) => (
                  <div key={item.question} className="rounded-[18px] border border-border/70 bg-background p-4">
                    <h3 className="text-base font-semibold tracking-tight font-display">{item.question}</h3>
                    <p className="mt-2 text-sm leading-6 text-muted-foreground">{item.answer}</p>
                  </div>
                ))}
              </div>
            </article>

            <article className="rounded-[24px] border border-border/70 bg-card p-6 shadow-sm">
              <h2 className="text-2xl font-semibold tracking-tight font-display sm:text-3xl">
                Đã có đủ bốn lớp thông tin cốt lõi cho public site tuyển sinh
              </h2>
              <p className="mt-3 text-sm leading-7 text-muted-foreground sm:text-base">
                Từ đây, bước hợp lý tiếp theo là mở thêm public contract cho timeline thanh toán, FAQ chuyên sâu
                hoặc chuẩn hóa canonical route và SEO metadata để hoàn thiện public site ở mức production-ready.
              </p>

              <div className="mt-6 flex flex-col gap-3 sm:flex-row">
                <Button asChild size="lg" className="touch-target">
                  <Link href="/">
                    Về trang chủ
                    <ArrowRight />
                  </Link>
                </Button>
                <Button asChild variant="outline" size="lg" className="touch-target">
                  <Link href="/tuyen-sinh/phuong-thuc">Xem lại phương thức</Link>
                </Button>
              </div>
            </article>
          </div>
        </div>
      </section>
    </PublicAdmissionsShell>
  )
}
