import Link from "next/link"
import { ArrowRight, BookCopy, FileCheck2, ShieldCheck } from "lucide-react"

import { Button } from "@/components/ui/button"
import {
  DemoImage,
  PublicAdmissionsPageHero,
  PublicAdmissionsShell,
  SectionHeading,
  pageShellClass,
} from "@/components/public/PublicAdmissionsShell"
import {
  publicAdmissionMethodsDetailed,
  publicAdmissionsMedia,
  publicDocumentBuckets,
  publicSubjectGroupHighlights,
} from "@/lib/public-admissions/site"
import type { PublicAdmissionsMethodsResponse } from "@/types/public-admissions.types"

interface PublicAdmissionMethodsPageProps {
  catalog?: PublicAdmissionsMethodsResponse | null
}

function buildMethodSignals(method: NonNullable<PublicAdmissionsMethodsResponse["methods"]>[number]) {
  const academicYears = [...method.academic_years].sort((a, b) => b - a)

  return [
    method.requires_gpa ? "Có dùng điều kiện học lực hoặc GPA" : "Không bắt buộc GPA trong cấu hình public hiện tại",
    method.requires_subject_scores ? "Có dùng điểm môn hoặc tổ hợp khi xét tuyển" : "Không bắt buộc nhập điểm môn trong cấu hình public hiện tại",
    academicYears.length > 0
      ? `Đang xuất hiện ở các năm ${academicYears.join(", ")}`
      : "Đang cập nhật năm tuyển sinh",
  ]
}

function buildMethodScope(method: NonNullable<PublicAdmissionsMethodsResponse["methods"]>[number]) {
  return [
    `${method.public_program_count} chương trình đang dùng`,
    `${method.public_offering_count} hệ đào tạo đang mở`,
    `${method.public_path_count} lộ trình public đang hiển thị`,
  ]
}

export default function PublicAdmissionMethodsPage({ catalog }: PublicAdmissionMethodsPageProps) {
  const liveCatalog = catalog && (catalog.methods.length > 0 || catalog.subject_groups.length > 0) ? catalog : null
  const liveMethods = liveCatalog?.methods ?? []
  const liveSubjectGroups = liveCatalog?.subject_groups ?? []

  const heroHighlights = liveCatalog
    ? [
        `${liveCatalog.summary.method_count} phương thức public`,
        `${liveCatalog.summary.subject_group_count} tổ hợp có liên kết`,
        `${liveCatalog.summary.public_path_count} lộ trình đang mở`,
      ]
    : ["4 phương thức chính", "Tổ hợp tham chiếu", "Checklist hồ sơ theo bước"]

  return (
    <PublicAdmissionsShell activePath="/tuyen-sinh/phuong-thuc">
      <PublicAdmissionsPageHero
        eyebrow="Admissions Methods"
        title="So sánh phương thức xét tuyển, tổ hợp và hồ sơ trên cùng một trang"
        description="Đây là lớp thông tin mà thí sinh thường tìm ngay sau khi chọn ngành. Trang nên giúp người học biết mình phù hợp với hướng nào, cần chuẩn bị gì và có thể nộp từ thời điểm nào."
        asset="documentsDesk"
        captionTitle={
          liveCatalog
            ? "Trang này đã nối dữ liệu thật cho AdmissionMethod và SubjectGroup ở các lộ trình public"
            : "Trang này đang là seeded content nhưng đã bám logic AdmissionMethod, SubjectGroup và ConfigDocumentType"
        }
        captionDescription={
          liveCatalog
            ? "Public site hiện chỉ hiển thị các phương thức và tổ hợp đang gắn với admission path active, visibility public. Checklist hồ sơ chi tiết đã được tách sang trang hồ sơ để dùng contract public riêng."
            : "Khi public API sẵn sàng, từng nhóm nội dung tại đây có thể nối sang phương thức xét tuyển, tổ hợp và checklist hồ sơ thực tế mà không cần đổi bố cục."
        }
        highlights={heroHighlights}
        actions={[
          { label: "Xem checklist hồ sơ", href: "/tuyen-sinh/ho-so" },
          { label: "Xem học phí & học bổng", href: "/tuyen-sinh/hoc-phi-hoc-bong", variant: "outline" },
        ]}
      />

      <section className="py-12 sm:py-20">
        <div className={`${pageShellClass} space-y-8 sm:space-y-10`}>
          <SectionHeading
            eyebrow={liveMethods.length > 0 ? "Live Methods" : "Methods"}
            title={
              liveMethods.length > 0
                ? "Các phương thức đang thực sự xuất hiện trên public portal"
                : "Bốn phương thức nên được trình bày rõ ràng ngay trên public site"
            }
            description={
              liveMethods.length > 0
                ? "Khối này đang lấy từ các admission path active và public ở backend. Người dùng sẽ thấy ngay phương thức nào đang được dùng, phạm vi xuất hiện của nó và các tín hiệu xét tuyển cơ bản."
                : "Người dùng không muốn tự giải mã thuật ngữ nội bộ. Họ muốn biết: phương thức này dành cho ai, đọc hồ sơ kiểu gì và cần chuẩn bị gì."
            }
          />

          {liveMethods.length > 0 ? (
            <div className="grid gap-4 xl:grid-cols-2">
              {liveMethods.map((method) => {
                const summary =
                  method.description ||
                  `Phương thức ${method.name.toLowerCase()} hiện đang được dùng ở ${method.public_program_count} chương trình và ${method.public_offering_count} hệ đào tạo trên public site.`

                return (
                  <article
                    key={method.id}
                    className="rounded-[24px] border border-border/70 bg-card p-5 shadow-sm sm:p-6"
                  >
                    <div className="flex items-start justify-between gap-4">
                      <div className="flex size-11 items-center justify-center rounded-2xl bg-info-50 text-info-700 sm:size-12">
                        <BookCopy className="size-5" />
                      </div>
                      <span className="rounded-full bg-primary/10 px-3 py-1 text-xs font-semibold uppercase tracking-[0.18em] text-primary">
                        {method.code}
                      </span>
                    </div>

                    <h3 className="mt-4 text-xl font-semibold tracking-tight font-display">{method.name}</h3>
                    <p className="mt-3 text-sm leading-6 text-muted-foreground">{summary}</p>

                    <div className="mt-5 grid gap-5 md:grid-cols-2">
                      <div className="space-y-3">
                        <p className="text-sm font-semibold text-foreground">Tín hiệu xét tuyển hiện có</p>
                        <ul className="space-y-3">
                          {buildMethodSignals(method).map((item) => (
                            <li key={item} className="flex items-start gap-3 text-sm text-foreground">
                              <span className="mt-1 size-2 rounded-full bg-success" />
                              <span className="leading-6">{item}</span>
                            </li>
                          ))}
                        </ul>
                      </div>

                      <div className="space-y-3">
                        <p className="text-sm font-semibold text-foreground">Phạm vi public hiện tại</p>
                        <ul className="space-y-3">
                          {buildMethodScope(method).map((item) => (
                            <li key={item} className="flex items-start gap-3 text-sm text-foreground">
                              <span className="mt-1 size-2 rounded-full bg-warning-500" />
                              <span className="leading-6">{item}</span>
                            </li>
                          ))}
                        </ul>
                      </div>
                    </div>
                  </article>
                )
              })}
            </div>
          ) : (
            <div className="grid gap-4 xl:grid-cols-2">
              {publicAdmissionMethodsDetailed.map((method) => (
                <article
                  key={method.title}
                  className="rounded-[24px] border border-border/70 bg-card p-5 shadow-sm sm:p-6"
                >
                  <div className="flex items-start justify-between gap-4">
                    <div className="flex size-11 items-center justify-center rounded-2xl bg-info-50 text-info-700 sm:size-12">
                      <BookCopy className="size-5" />
                    </div>
                    <span className="rounded-full bg-primary/10 px-3 py-1 text-xs font-semibold uppercase tracking-[0.18em] text-primary">
                      {method.audience}
                    </span>
                  </div>

                  <h3 className="mt-4 text-xl font-semibold tracking-tight font-display">{method.title}</h3>
                  <p className="mt-3 text-sm leading-6 text-muted-foreground">{method.summary}</p>

                  <div className="mt-5 grid gap-5 md:grid-cols-2">
                    <div className="space-y-3">
                      <p className="text-sm font-semibold text-foreground">Điều kiện cần kiểm tra</p>
                      <ul className="space-y-3">
                        {method.requirements.map((item) => (
                          <li key={item} className="flex items-start gap-3 text-sm text-foreground">
                            <span className="mt-1 size-2 rounded-full bg-success" />
                            <span className="leading-6">{item}</span>
                          </li>
                        ))}
                      </ul>
                    </div>

                    <div className="space-y-3">
                      <p className="text-sm font-semibold text-foreground">Hồ sơ nên chuẩn bị</p>
                      <ul className="space-y-3">
                        {method.documents.map((item) => (
                          <li key={item} className="flex items-start gap-3 text-sm text-foreground">
                            <span className="mt-1 size-2 rounded-full bg-warning-500" />
                            <span className="leading-6">{item}</span>
                          </li>
                        ))}
                      </ul>
                    </div>
                  </div>
                </article>
              ))}
            </div>
          )}
        </div>
      </section>

      <section className="border-y border-border/70 bg-gradient-to-b from-background to-info-50/45 py-12 sm:py-20">
        <div className={`${pageShellClass} space-y-8 sm:space-y-10`}>
          <SectionHeading
            eyebrow={liveSubjectGroups.length > 0 ? "Live Subject Groups" : "Subject Groups"}
            title={
              liveSubjectGroups.length > 0
                ? "Các tổ hợp hiện đang được liên kết với lộ trình public"
                : "Tổ hợp và điều kiện nên được mô tả theo ngữ cảnh người học"
            }
            description={
              liveSubjectGroups.length > 0
                ? "Dữ liệu tổ hợp đang phản ánh những subject group thật sự được criteria của các path public sử dụng. Điều này giúp public site tránh hiển thị các tổ hợp cấu hình nội bộ nhưng chưa áp dụng."
                : "Thí sinh thường không tìm một mã kỹ thuật đơn lẻ. Họ cần biết tổ hợp nào gắn với nhóm ngành nào và hồ sơ của mình nên đối chiếu ra sao."
            }
          />

          {liveSubjectGroups.length > 0 ? (
            <div className="grid gap-4 lg:grid-cols-3">
              {liveSubjectGroups.map((group) => (
                <article
                  key={group.id}
                  className="rounded-[20px] border border-border/70 bg-card p-5 shadow-sm sm:rounded-[24px] sm:p-6"
                >
                  <p className="text-sm font-semibold uppercase tracking-[0.18em] text-primary">{group.code}</p>
                  <h3 className="mt-4 text-lg font-semibold tracking-tight font-display sm:text-xl">{group.name}</h3>
                  <p className="mt-3 text-sm leading-6 text-muted-foreground">
                    Đang được dùng trong {group.public_path_count} lộ trình public
                    {group.method_codes.length > 0 ? ` qua các phương thức ${group.method_codes.join(", ")}.` : "."}
                  </p>
                  <div className="mt-4 flex flex-wrap gap-2">
                    {group.subjects.map((subject) => (
                      <span key={subject} className="rounded-full bg-muted px-3 py-1 text-xs font-medium text-foreground">
                        {subject}
                      </span>
                    ))}
                  </div>
                </article>
              ))}
            </div>
          ) : (
            <div className="grid gap-4 lg:grid-cols-3">
              {publicSubjectGroupHighlights.map((group) => (
                <article
                  key={group.code}
                  className="rounded-[20px] border border-border/70 bg-card p-5 shadow-sm sm:rounded-[24px] sm:p-6"
                >
                  <p className="text-sm font-semibold uppercase tracking-[0.18em] text-primary">{group.code}</p>
                  <h3 className="mt-4 text-lg font-semibold tracking-tight font-display sm:text-xl">{group.focus}</h3>
                  <p className="mt-3 text-sm leading-6 text-muted-foreground">{group.fit}</p>
                  <div className="mt-4 flex flex-wrap gap-2">
                    {group.subjects.map((subject) => (
                      <span key={subject} className="rounded-full bg-muted px-3 py-1 text-xs font-medium text-foreground">
                        {subject}
                      </span>
                    ))}
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
            eyebrow="Documents"
            title="Checklist hồ sơ nên chia theo từng giai đoạn, không dồn vào một danh sách dài"
            description="Khối này giữ vai trò teaser để người dùng hiểu mạch chuẩn bị hồ sơ. Checklist chi tiết theo hệ đào tạo và phương thức hiện đã được tách sang trang hồ sơ dùng contract public riêng."
          />

          <div className="grid gap-4 lg:grid-cols-3">
            {publicDocumentBuckets.map((bucket, index) => (
              <article
                key={bucket.title}
                className="rounded-[20px] border border-border/70 bg-card p-5 shadow-sm sm:rounded-[24px] sm:p-6"
              >
                <div className="flex items-center justify-between gap-4">
                  <div className="flex size-11 items-center justify-center rounded-2xl bg-warning-50 text-warning-700 sm:size-12">
                    {index === 0 ? <FileCheck2 className="size-5" /> : index === 1 ? <BookCopy className="size-5" /> : <ShieldCheck className="size-5" />}
                  </div>
                  <span className="text-sm font-semibold text-muted-foreground">0{index + 1}</span>
                </div>
                <h3 className="mt-4 text-lg font-semibold tracking-tight font-display sm:text-xl">{bucket.title}</h3>
                <p className="mt-3 text-sm leading-6 text-muted-foreground">{bucket.description}</p>
                <ul className="mt-5 space-y-3">
                  {bucket.items.map((item) => (
                    <li key={item} className="flex items-start gap-3 text-sm text-foreground">
                      <span className="mt-1 size-2 rounded-full bg-success" />
                      <span className="leading-6">{item}</span>
                    </li>
                  ))}
                </ul>
              </article>
            ))}
          </div>
        </div>
      </section>

      <section className="border-t border-border/70 bg-gradient-to-b from-background to-warning-50/50 py-12 sm:py-20">
        <div className={`${pageShellClass} grid gap-6 lg:grid-cols-[0.9fr_1.1fr]`}>
          <article className="overflow-hidden rounded-[24px] border border-border/70 bg-card shadow-sm">
            <DemoImage asset={publicAdmissionsMedia.classroomStudy} className="aspect-[4/3] w-full object-cover" />
          </article>

          <article className="rounded-[24px] border border-border/70 bg-card p-6 shadow-sm">
            <p className="text-sm font-semibold uppercase tracking-[0.2em] text-primary">Next Step</p>
            <h2 className="mt-3 text-2xl font-semibold tracking-tight font-display sm:text-3xl">
              Sau khi biết mình nộp theo hướng nào, bước tiếp theo là chốt checklist hồ sơ cần chuẩn bị
            </h2>
            <p className="mt-3 text-sm leading-7 text-muted-foreground sm:text-base">
              Public site nên dẫn mạch tự nhiên từ phương thức xét tuyển sang checklist hồ sơ theo hệ đào tạo
              và phương thức, để người học biết chính xác giấy tờ nào cần scan, giấy tờ nào chỉ phải đối chiếu
              hoặc nộp bổ sung sau khi đủ điều kiện.
            </p>

            <div className="mt-6 flex flex-col gap-3 sm:flex-row">
              <Button asChild size="lg" className="touch-target">
                <Link href="/tuyen-sinh/ho-so">
                  Sang trang hồ sơ
                  <ArrowRight />
                </Link>
              </Button>
              <Button asChild variant="outline" size="lg" className="touch-target">
                <Link href="/tuyen-sinh/hoc-phi-hoc-bong">Xem học phí & học bổng</Link>
              </Button>
            </div>
          </article>
        </div>
      </section>
    </PublicAdmissionsShell>
  )
}
