import Link from "next/link"
import { ArrowRight, BadgeCheck, GraduationCap, Layers3 } from "lucide-react"

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
  publicProgramClusters,
  publicProgramFormats,
  publicProgramSelectionSteps,
} from "@/lib/public-admissions/site"
import type {
  PublicAdmissionsMoney,
  PublicAdmissionsProgramsResponse,
} from "@/types/public-admissions.types"

interface PublicProgramsPageProps {
  catalog?: PublicAdmissionsProgramsResponse | null
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

function formatTuitionRange(min: PublicAdmissionsMoney, max: PublicAdmissionsMoney): string | null {
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

function formatScore(value: PublicAdmissionsMoney): string | null {
  const normalized = normalizeMoney(value)
  if (normalized === null) {
    return null
  }

  return normalized.toLocaleString("vi-VN", {
    minimumFractionDigits: normalized % 1 === 0 ? 0 : 2,
    maximumFractionDigits: 2,
  })
}

function formatAcademicYears(years: number[]): string | null {
  if (years.length === 0) {
    return null
  }

  const sorted = [...years].sort((a, b) => a - b);

  if (sorted.length === 1) {
    return `Năm ${sorted[0]}`
  }

  return `${sorted[sorted.length - 1]} - ${sorted[0]}`
}

export default function PublicProgramsPage({ catalog }: PublicProgramsPageProps) {
  const liveCatalog = catalog && catalog.degree_levels.length > 0 ? catalog : null
  const hasLiveCatalog = Boolean(liveCatalog)
  const heroHighlights = liveCatalog
    ? [
        `${liveCatalog.summary.program_count} chương trình đang public`,
        `${liveCatalog.summary.offering_count} hệ đào tạo đã công bố`,
        liveCatalog.summary.latest_academic_year
          ? `Dữ liệu năm ${liveCatalog.summary.latest_academic_year}`
          : "Dữ liệu công bố thật",
      ]
    : ["Bậc học rõ ràng", "Nhóm ngành dễ duyệt", "Gợi ý hệ đào tạo"]

  const heroCaptionTitle = hasLiveCatalog
    ? "Danh mục chương trình đào tạo đang tuyển sinh"
    : "Thông tin chương trình đào tạo tham khảo"

  const heroCaptionDescription = hasLiveCatalog
    ? "Chỉ những ngành, hệ đào tạo và thông tin năm học đã được công bố chính thức mới hiển thị trên trang này."
    : "Danh mục đang được cập nhật. Vui lòng quay lại sau hoặc liên hệ phòng tuyển sinh để biết thêm chi tiết."

  return (
    <PublicAdmissionsShell activePath="/tuyen-sinh/nganh-hoc">
      <PublicAdmissionsPageHero
        eyebrow="Programs"
        title="Xem ngành học theo cụm chương trình, bậc học và hệ đào tạo"
        description="Trang này là lớp nội dung chi tiết sau homepage: giúp thí sinh thu hẹp lựa chọn theo nhóm ngành, hình thức học và khung chi phí trước khi chuyển sang bước xem phương thức xét tuyển."
        asset="libraryStudy"
        captionTitle={heroCaptionTitle}
        captionDescription={heroCaptionDescription}
        highlights={heroHighlights}
        actions={[
          { label: "Xem phương thức xét tuyển", href: "/tuyen-sinh/phuong-thuc" },
          { label: "Xem học phí & học bổng", href: "/tuyen-sinh/hoc-phi-hoc-bong", variant: "outline" },
        ]}
      />

      <section className="py-12 sm:py-20">
        <div className={`${pageShellClass} space-y-8 sm:space-y-10`}>
          <SectionHeading
            eyebrow="How To Start"
            title="Nên bắt đầu từ đâu khi chọn ngành?"
            description="Thí sinh thường không bắt đầu từ tên ngành quá chi tiết. Họ thường đi theo lộ trình: bậc học, cách học, sau đó mới đến cụm chương trình gần với định hướng nghề nghiệp."
          />

          <div className="grid gap-4 lg:grid-cols-3">
            {publicProgramSelectionSteps.map((step, index) => (
              <article
                key={step.title}
                className="rounded-[20px] border border-border/70 bg-card p-5 shadow-sm sm:rounded-[24px] sm:p-6"
              >
                <div className="flex items-center justify-between gap-4">
                  <div className="flex size-11 items-center justify-center rounded-2xl bg-info-50 text-info-700 sm:size-12">
                    {index === 0 ? <GraduationCap className="size-5" /> : index === 1 ? <Layers3 className="size-5" /> : <BadgeCheck className="size-5" />}
                  </div>
                  <span className="text-sm font-semibold text-muted-foreground">0{index + 1}</span>
                </div>
                <h3 className="mt-4 text-lg font-semibold tracking-tight font-display sm:mt-5 sm:text-xl">{step.title}</h3>
                <p className="mt-3 text-sm leading-6 text-muted-foreground">{step.description}</p>
              </article>
            ))}
          </div>
        </div>
      </section>

      <section className="border-y border-border/70 bg-gradient-to-b from-background to-info-50/45 py-12 sm:py-20">
        <div className={`${pageShellClass} space-y-8 sm:space-y-10`}>
          <SectionHeading
            eyebrow={hasLiveCatalog ? "Live Catalog" : "Clusters"}
            title={
              hasLiveCatalog
                ? "Danh mục chương trình đang công bố trên public site"
                : "Bốn cụm chương trình nên xuất hiện nổi bật trên public site"
            }
            description={
              hasLiveCatalog
                ? "Khối này đang dùng dữ liệu thật từ backend. Public site chỉ hiển thị các ngành có hệ đào tạo active và thông tin năm học đã publish, để nội dung luôn bám sát danh mục tuyển sinh hiện hành."
                : "Thay vì bắt người dùng lật từng menu sâu, site public nên đưa các cụm ngành được quan tâm nhiều nhất lên tầng đầu để rút ngắn thời gian khám phá."
            }
          />

          {liveCatalog ? (
            <div className="space-y-6">
              <div className="flex flex-wrap gap-2">
                {liveCatalog.summary.offering_types.map((item) => (
                  <span key={item} className="rounded-full border border-border bg-card px-3 py-1 text-xs font-medium text-foreground">
                    {item}
                  </span>
                ))}
              </div>

              {liveCatalog.degree_levels.map((group) => {
                const groupTuitionRange = formatTuitionRange(group.tuition_min, group.tuition_max)
                const groupAcademicYears = formatAcademicYears(group.academic_years)

                return (
                  <article
                    key={group.degree_level}
                    className="rounded-[28px] border border-border/70 bg-card p-5 shadow-sm sm:p-6"
                  >
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="rounded-full bg-info-50 px-3 py-1 text-xs font-semibold uppercase tracking-[0.18em] text-info-700">
                        {group.degree_level}
                      </span>
                      <span className="rounded-full bg-muted px-3 py-1 text-xs font-medium text-foreground">
                        {group.program_count} chương trình
                      </span>
                      <span className="rounded-full bg-muted px-3 py-1 text-xs font-medium text-foreground">
                        {group.offering_count} hệ đào tạo
                      </span>
                      {groupTuitionRange ? (
                        <span className="rounded-full bg-warning-50 px-3 py-1 text-xs font-semibold text-warning-700">
                          {groupTuitionRange}
                        </span>
                      ) : null}
                    </div>

                    <p className="mt-3 text-sm leading-6 text-muted-foreground">
                      {group.offering_types.join(" • ")}
                      {groupAcademicYears ? ` | ${groupAcademicYears}` : ""}
                    </p>

                    <div className="mt-6 grid gap-4 xl:grid-cols-2">
                      {group.programs.map((program) => {
                        const programTuitionRange = formatTuitionRange(program.tuition_min, program.tuition_max)
                        const programAcademicYears = formatAcademicYears(program.academic_years)

                        return (
                          <article
                            key={program.id}
                            className="rounded-[24px] border border-border/70 bg-background p-5 shadow-xs"
                          >
                            <div className="flex flex-wrap items-start justify-between gap-3">
                              <div className="space-y-1">
                                <p className="text-xs font-semibold uppercase tracking-[0.18em] text-primary">
                                  Mã ngành {program.code}
                                </p>
                                <h3 className="text-xl font-semibold tracking-tight font-display">
                                  {program.name}
                                </h3>
                              </div>

                              {program.is_heavy ? (
                                <span className="rounded-full bg-warning-50 px-3 py-1 text-xs font-semibold text-warning-700">
                                  Chính sách ưu tiên riêng
                                </span>
                              ) : null}
                            </div>

                            <div className="mt-4 flex flex-wrap gap-2">
                              <span className="rounded-full border border-border px-3 py-1 text-xs font-medium text-foreground">
                                {program.offering_count} hệ đào tạo
                              </span>
                              {programAcademicYears ? (
                                <span className="rounded-full border border-border px-3 py-1 text-xs font-medium text-foreground">
                                  {programAcademicYears}
                                </span>
                              ) : null}
                              {programTuitionRange ? (
                                <span className="rounded-full border border-border px-3 py-1 text-xs font-medium text-foreground">
                                  {programTuitionRange}
                                </span>
                              ) : null}
                            </div>

                            <div className="mt-5 space-y-3">
                              {program.offerings.map((offering) => {
                                const tuitionLabel = formatCurrency(offering.academic_info.tuition_fee_per_year)
                                const quotaLabel =
                                  offering.academic_info.annual_admission_quota !== null
                                    ? `${offering.academic_info.annual_admission_quota} chỉ tiêu`
                                    : "Đang cập nhật"
                                const cutoffLabel = formatScore(offering.academic_info.cutoff_score_previous_year)

                                return (
                                  <div
                                    key={offering.id}
                                    className="rounded-[20px] border border-border/70 bg-card p-4"
                                  >
                                    <div className="flex flex-wrap items-center justify-between gap-2">
                                      <h4 className="text-sm font-semibold text-foreground">
                                        {offering.offering_type}
                                      </h4>
                                      <span className="rounded-full bg-info-50 px-3 py-1 text-xs font-medium text-info-700">
                                        Năm {offering.academic_info.academic_year}
                                      </span>
                                    </div>

                                    <div className="mt-3 grid gap-3 sm:grid-cols-2">
                                      <div>
                                        <p className="text-xs font-semibold uppercase tracking-[0.16em] text-muted-foreground">
                                          Học phí
                                        </p>
                                        <p className="mt-1 text-sm font-medium text-foreground">
                                          {tuitionLabel ?? "Đang cập nhật"}
                                        </p>
                                      </div>
                                      <div>
                                        <p className="text-xs font-semibold uppercase tracking-[0.16em] text-muted-foreground">
                                          Chỉ tiêu
                                        </p>
                                        <p className="mt-1 text-sm font-medium text-foreground">{quotaLabel}</p>
                                      </div>
                                      <div>
                                        <p className="text-xs font-semibold uppercase tracking-[0.16em] text-muted-foreground">
                                          Thời lượng
                                        </p>
                                        <p className="mt-1 text-sm font-medium text-foreground">
                                          {offering.duration_semesters ? `${offering.duration_semesters} học kỳ` : "Đang cập nhật"}
                                        </p>
                                      </div>
                                      <div>
                                        <p className="text-xs font-semibold uppercase tracking-[0.16em] text-muted-foreground">
                                          Điểm chuẩn năm trước
                                        </p>
                                        <p className="mt-1 text-sm font-medium text-foreground">
                                          {cutoffLabel ?? "Đang cập nhật"}
                                        </p>
                                      </div>
                                    </div>

                                    {offering.academic_info.target_audience ? (
                                      <p className="mt-4 text-sm leading-6 text-muted-foreground">
                                        {offering.academic_info.target_audience}
                                      </p>
                                    ) : null}

                                    {offering.admission_methods.length > 0 ? (
                                      <div className="mt-4 space-y-2">
                                        <p className="text-xs font-semibold uppercase tracking-[0.16em] text-muted-foreground">
                                          Phương thức đang public
                                        </p>
                                        <div className="flex flex-wrap gap-2">
                                          {offering.admission_methods.map((method) => (
                                            <span
                                              key={method.id}
                                              className="rounded-full bg-primary/10 px-3 py-1 text-xs font-medium text-primary"
                                            >
                                              {method.name}
                                            </span>
                                          ))}
                                        </div>
                                      </div>
                                    ) : (
                                      <p className="mt-4 text-xs font-medium text-muted-foreground">
                                        Phương thức xét tuyển cho hệ này đang được cập nhật trên public portal.
                                      </p>
                                    )}
                                  </div>
                                )
                              })}
                            </div>
                          </article>
                        )
                      })}
                    </div>
                  </article>
                )
              })}
            </div>
          ) : (
            <div className="grid gap-4 xl:grid-cols-2">
              {publicProgramClusters.map((cluster) => (
                <article
                  key={cluster.title}
                  className="rounded-[24px] border border-border/70 bg-card p-5 shadow-sm sm:p-6"
                >
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="rounded-full bg-info-50 px-3 py-1 text-xs font-semibold uppercase tracking-[0.18em] text-info-700">
                      {cluster.degreeLevel}
                    </span>
                    <span className="rounded-full bg-warning-50 px-3 py-1 text-xs font-semibold text-warning-700">
                      {cluster.tuitionRange}
                    </span>
                  </div>

                  <h3 className="mt-4 text-xl font-semibold tracking-tight font-display">{cluster.title}</h3>
                  <p className="mt-3 text-sm leading-6 text-muted-foreground">{cluster.summary}</p>

                  <div className="mt-5 grid gap-4 md:grid-cols-2">
                    <div className="space-y-3">
                      <p className="text-sm font-semibold text-foreground">Ví dụ chương trình</p>
                      <div className="flex flex-wrap gap-2">
                        {cluster.examples.map((example) => (
                          <span key={example} className="rounded-full bg-muted px-3 py-1 text-xs font-medium text-foreground">
                            {example}
                          </span>
                        ))}
                      </div>
                    </div>

                    <div className="space-y-3">
                      <p className="text-sm font-semibold text-foreground">Hệ đào tạo gợi ý</p>
                      <div className="flex flex-wrap gap-2">
                        {cluster.offeringTypes.map((item) => (
                          <span key={item} className="rounded-full border border-border px-3 py-1 text-xs font-medium text-foreground">
                            {item}
                          </span>
                        ))}
                      </div>
                    </div>
                  </div>

                  <div className="mt-5 space-y-3">
                    <p className="text-sm font-semibold text-foreground">Đầu ra nghề nghiệp tham khảo</p>
                    <ul className="grid gap-3 sm:grid-cols-2">
                      {cluster.outcomes.map((outcome) => (
                        <li key={outcome} className="flex items-start gap-3 text-sm text-foreground">
                          <span className="mt-1 size-2 rounded-full bg-success" />
                          <span className="leading-6">{outcome}</span>
                        </li>
                      ))}
                    </ul>
                  </div>
                </article>
              ))}
            </div>
          )}
        </div>
      </section>

      <section className="py-12 sm:py-20">
        <div className={`${pageShellClass} space-y-8 sm:space-y-10`}>
          <SectionHeading
            eyebrow="Formats"
            title="Hệ đào tạo nên được giải thích bằng ngữ cảnh, không chỉ là tên gọi"
            description="Ở public site, người dùng cần hiểu nhanh hình thức học nào hợp với bản thân. Cách viết này dễ đọc hơn nhiều so với chỉ hiển thị danh sách ConfigOfferingType."
          />

          <div className="grid gap-4 lg:grid-cols-3">
            {publicProgramFormats.map((format) => (
              <article
                key={format.title}
                className="rounded-[20px] border border-border/70 bg-card p-5 shadow-sm sm:rounded-[24px] sm:p-6"
              >
                <p className="text-sm font-semibold uppercase tracking-[0.18em] text-primary">{format.schedule}</p>
                <h3 className="mt-4 text-lg font-semibold tracking-tight font-display sm:text-xl">{format.title}</h3>
                <p className="mt-3 text-sm leading-6 text-muted-foreground">{format.description}</p>
                <p className="mt-4 text-sm leading-6 text-foreground">
                  <span className="font-semibold">Phù hợp với:</span> {format.bestFor}
                </p>
              </article>
            ))}
          </div>
        </div>
      </section>

      <section className="border-t border-border/70 bg-gradient-to-b from-background to-warning-50/50 py-12 sm:py-20">
        <div className={`${pageShellClass} grid gap-6 lg:grid-cols-[0.9fr_1.1fr]`}>
          <article className="overflow-hidden rounded-[24px] border border-border/70 bg-card shadow-sm">
            <DemoImage asset={publicAdmissionsMedia.studentsWalk} className="aspect-[4/3] w-full object-cover" />
          </article>

          <article className="rounded-[24px] border border-border/70 bg-card p-6 shadow-sm">
            <p className="text-sm font-semibold uppercase tracking-[0.2em] text-primary">Next Step</p>
            <h2 className="mt-3 text-2xl font-semibold tracking-tight font-display sm:text-3xl">
              Chọn được nhóm ngành rồi, bước tiếp theo là đối chiếu phương thức phù hợp
            </h2>
            <p className="mt-3 text-sm leading-7 text-muted-foreground sm:text-base">
              Khi thí sinh đã có 2-3 lựa chọn gần đúng, trang tiếp theo nên trả lời ngay: nộp bằng học bạ,
              điểm thi, bài thi riêng hay hồ sơ kết hợp; cần tổ hợp nào; và bộ hồ sơ nào phải chuẩn bị trước.
            </p>

            <div className="mt-6 flex flex-col gap-3 sm:flex-row">
              <Button asChild size="lg" className="touch-target">
                <Link href="/tuyen-sinh/phuong-thuc">
                  Sang trang phương thức
                  <ArrowRight />
                </Link>
              </Button>
              <Button asChild variant="outline" size="lg" className="touch-target">
                <Link href="/tuyen-sinh/hoc-phi-hoc-bong">Xem khung học phí</Link>
              </Button>
            </div>
          </article>
        </div>
      </section>
    </PublicAdmissionsShell>
  )
}
