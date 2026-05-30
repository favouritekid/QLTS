import Link from "next/link"
import { ArrowRight, FileCheck2, FolderKanban, ShieldCheck, Upload } from "lucide-react"

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
  publicDocumentBuckets,
} from "@/lib/public-admissions/site"
import { getFormatLabel } from "@/lib/utils/admission-helpers"
import type {
  PublicAdmissionsDocumentRequirement,
  PublicAdmissionsDocumentsResponse,
} from "@/types/public-admissions.types"

interface PublicDocumentsPageProps {
  catalog?: PublicAdmissionsDocumentsResponse | null
}

// ADM-031.7 follow-up: use the shared `getFormatLabel` so applicant-facing
// public docs and officer DocumentsTab agree on enum copy. Returns null
// when the value is missing so the JSX can short-circuit the badge.
function formatSubmissionFormat(value: string | null): string | null {
  if (!value) {
    return null
  }
  return getFormatLabel(value)
}

function dedupeDocuments(
  documents: PublicAdmissionsDocumentRequirement[],
): PublicAdmissionsDocumentRequirement[] {
  const byDocumentType = new Map<number, PublicAdmissionsDocumentRequirement>()

  for (const item of documents) {
    byDocumentType.set(item.document_type_id, item)
  }

  return [...byDocumentType.values()].sort((a, b) => {
    if (a.display_order !== b.display_order) {
      return a.display_order - b.display_order
    }
    return a.document_type_name.localeCompare(b.document_type_name, "vi")
  })
}

function DocumentRequirementList({
  documents,
}: {
  documents: PublicAdmissionsDocumentRequirement[]
}) {
  return (
    <ul className="space-y-3">
      {documents.map((document) => {
        const submissionFormat = formatSubmissionFormat(document.submission_format)

        return (
          <li
            key={`${document.document_type_id}-${document.source}`}
            className="rounded-[18px] border border-border/70 bg-background p-4"
          >
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div className="space-y-1">
                <p className="text-sm font-semibold text-foreground">{document.document_type_name}</p>
                {document.document_type_description ? (
                  <p className="text-sm leading-6 text-muted-foreground">
                    {document.document_type_description}
                  </p>
                ) : null}
              </div>

              <div className="flex flex-wrap gap-2">
                <span className="rounded-full bg-muted px-3 py-1 text-xs font-medium text-foreground">
                  {document.is_mandatory ? "Bắt buộc" : "Khuyến khích"}
                </span>
                <span className="rounded-full bg-muted px-3 py-1 text-xs font-medium text-foreground">
                  {document.requires_upload ? "Cần upload" : "Checklist đối chiếu"}
                </span>
                {submissionFormat ? (
                  <span className="rounded-full bg-primary/10 px-3 py-1 text-xs font-medium text-primary">
                    {submissionFormat}
                  </span>
                ) : null}
              </div>
            </div>
          </li>
        )
      })}
    </ul>
  )
}

export default function PublicDocumentsPage({ catalog }: PublicDocumentsPageProps) {
  const liveCatalog = catalog && catalog.offering_types.length > 0 ? catalog : null
  const offeringTypes = liveCatalog?.offering_types ?? []

  const allLiveDocuments = liveCatalog
    ? dedupeDocuments(
        offeringTypes.flatMap((item) => [
          ...item.shared_documents,
          // §9: gộp cả lớp audience để section "chuẩn bị theo nhóm việc" không
          // bỏ sót giấy academic (đã tách khỏi shared_documents).
          ...item.audience_layers.flatMap((layer) => layer.documents),
          ...item.method_documents.flatMap((method) => method.documents),
        ]),
      )
    : []
  const uploadDocuments = allLiveDocuments.filter((item) => item.requires_upload)
  const checklistDocuments = allLiveDocuments.filter((item) => !item.requires_upload)
  const overrideDocuments = liveCatalog
    ? dedupeDocuments(
        offeringTypes.flatMap((item) =>
          item.method_documents
            .filter((method) => method.source === "method_override")
            .flatMap((method) => method.documents)
        ),
      )
    : []

  const heroHighlights = liveCatalog
    ? [
        `${liveCatalog.summary.offering_type_count} hệ đào tạo có checklist`,
        `${liveCatalog.summary.method_count} phương thức có hồ sơ public`,
        `${liveCatalog.summary.document_type_count} loại giấy tờ đang dùng`,
      ]
    : ["Checklist theo hệ", "Override theo phương thức", "Giấy tờ cần upload"]

  return (
    <PublicAdmissionsShell activePath="/tuyen-sinh/ho-so">
      <PublicAdmissionsPageHero
        eyebrow="Admissions Documents"
        title="Xem checklist hồ sơ theo hệ đào tạo và phương thức xét tuyển"
        description="Trang này giúp thí sinh và phụ huynh biết chính xác cần chuẩn bị giấy tờ gì, giấy tờ nào phải upload và khi nào bộ hồ sơ thay đổi theo từng phương thức."
        asset="documentsDesk"
        captionTitle={
          liveCatalog
            ? "Checklist hồ sơ theo hệ đào tạo và phương thức xét tuyển hiện hành"
            : "Danh mục hồ sơ cần chuẩn bị tham khảo"
        }
        captionDescription={
          liveCatalog
            ? "Hồ sơ chung theo hệ đào tạo và yêu cầu riêng theo từng phương thức xét tuyển được cập nhật theo danh mục tuyển sinh hiện hành."
            : "Danh mục đang được cập nhật. Vui lòng quay lại sau hoặc liên hệ phòng tuyển sinh để biết thêm chi tiết."
        }
        highlights={heroHighlights}
        actions={[
          { label: "Quay lại phương thức", href: "/tuyen-sinh/phuong-thuc" },
          { label: "Xem học phí & học bổng", href: "/tuyen-sinh/hoc-phi-hoc-bong", variant: "outline" },
        ]}
      />

      <section className="py-12 sm:py-20">
        <div className={`${pageShellClass} space-y-8 sm:space-y-10`}>
          <SectionHeading
            eyebrow={liveCatalog ? "Live Checklists" : "Documents"}
            title={
              liveCatalog
                ? "Checklist hồ sơ đang công bố theo từng hệ đào tạo"
                : "Checklist hồ sơ nên được chia theo từng lớp rõ ràng"
            }
            description={
              liveCatalog
                ? "Dữ liệu dưới đây đang phản ánh checklist thực tế đã được publish trên public portal. Thí sinh sẽ thấy bộ hồ sơ mặc định theo hệ đào tạo và các thay đổi riêng theo từng phương thức khi có override."
                : "Ngay cả khi chưa có dữ liệu thật, public site vẫn nên tách rõ hồ sơ chung, hồ sơ theo phương thức và hồ sơ hoàn tất nhập học để người dùng dễ chuẩn bị."
            }
          />

          {liveCatalog ? (
            <div className="space-y-6">
              {offeringTypes.map((checklist) => (
                <article
                  key={checklist.offering_type_id}
                  className="rounded-[28px] border border-border/70 bg-card p-5 shadow-sm sm:p-6"
                >
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="rounded-full bg-info-50 px-3 py-1 text-xs font-semibold uppercase tracking-[0.18em] text-info-700">
                      {checklist.offering_type_name}
                    </span>
                    <span className="rounded-full bg-muted px-3 py-1 text-xs font-medium text-foreground">
                      {checklist.public_program_count} chương trình
                    </span>
                    <span className="rounded-full bg-muted px-3 py-1 text-xs font-medium text-foreground">
                      {checklist.public_offering_count} hệ đào tạo public
                    </span>
                    <span className="rounded-full bg-muted px-3 py-1 text-xs font-medium text-foreground">
                      {checklist.public_method_count} phương thức liên quan
                    </span>
                  </div>

                  {checklist.sample_programs.length > 0 ? (
                    <p className="mt-3 text-sm leading-6 text-muted-foreground">
                      Ví dụ chương trình đang dùng checklist này: {checklist.sample_programs.join(", ")}.
                    </p>
                  ) : null}

                  <div className="mt-6 grid gap-6 xl:grid-cols-[0.9fr_1.1fr]">
                    <div className="space-y-4">
                      <div className="flex items-center gap-3">
                        <div className="flex size-10 items-center justify-center rounded-2xl bg-warning-50 text-warning-700">
                          <FileCheck2 className="size-5" />
                        </div>
                        <div>
                          <h3 className="text-lg font-semibold tracking-tight font-display">
                            Hồ sơ mặc định theo hệ đào tạo
                          </h3>
                          <p className="text-sm text-muted-foreground">
                            Áp dụng cho các phương thức chưa có cấu hình override riêng.
                          </p>
                        </div>
                      </div>

                      {checklist.shared_documents.length > 0 ? (
                        <DocumentRequirementList documents={checklist.shared_documents} />
                      ) : (
                        <div className="rounded-[18px] border border-dashed border-border/80 bg-background p-4 text-sm leading-6 text-muted-foreground">
                          Hệ đào tạo này hiện chưa có checklist mặc định public.
                        </div>
                      )}

                      {/* §9: lớp giấy tờ theo đối tượng/trình độ (Tốt nghiệp
                          THCS / THPT) — tách rõ để TS thấy đúng bộ mình cần. */}
                      {checklist.audience_layers.map((layer) => (
                        <div key={layer.audience} className="space-y-3 pt-2">
                          <div className="flex flex-wrap items-center gap-2">
                            <span className="rounded-full bg-info-50 px-3 py-1 text-xs font-semibold text-info-700">
                              {layer.audience_label}
                            </span>
                            <span className="text-xs text-muted-foreground">
                              Bổ sung cho thí sinh thuộc đối tượng này
                            </span>
                          </div>
                          <DocumentRequirementList documents={layer.documents} />
                        </div>
                      ))}
                    </div>

                    <div className="space-y-4">
                      <div className="flex items-center gap-3">
                        <div className="flex size-10 items-center justify-center rounded-2xl bg-primary/10 text-primary">
                          <ShieldCheck className="size-5" />
                        </div>
                        <div>
                          <h3 className="text-lg font-semibold tracking-tight font-display">
                            Điều chỉnh theo từng phương thức
                          </h3>
                          <p className="text-sm text-muted-foreground">
                            Khi backend có method-specific config, checklist sẽ override bộ mặc định.
                          </p>
                        </div>
                      </div>

                      {checklist.method_documents.length > 0 ? (
                        <div className="grid gap-4">
                          {checklist.method_documents.map((method) => (
                            <article
                              key={`${checklist.offering_type_id}-${method.method_id}`}
                              className="rounded-[20px] border border-border/70 bg-background p-4"
                            >
                              <div className="flex flex-wrap items-center justify-between gap-3">
                                <div>
                                  <p className="text-sm font-semibold text-foreground">{method.method_name}</p>
                                  <p className="text-sm leading-6 text-muted-foreground">
                                    {method.public_program_count} chương trình, {method.public_offering_count} hệ đào tạo,
                                    {` ${method.public_path_count} lộ trình public`}
                                  </p>
                                </div>

                                <span className="rounded-full bg-primary/10 px-3 py-1 text-xs font-semibold uppercase tracking-[0.18em] text-primary">
                                  {method.source === "method_override" ? "Override riêng" : "Dùng bộ mặc định"}
                                </span>
                              </div>

                              <div className="mt-4">
                                <DocumentRequirementList documents={method.documents} />
                              </div>
                            </article>
                          ))}
                        </div>
                      ) : (
                        <div className="rounded-[18px] border border-dashed border-border/80 bg-background p-4 text-sm leading-6 text-muted-foreground">
                          Chưa có phương thức nào của hệ đào tạo này được public cùng checklist hồ sơ.
                        </div>
                      )}
                    </div>
                  </div>
                </article>
              ))}
            </div>
          ) : (
            <div className="grid gap-4 lg:grid-cols-3">
              {publicDocumentBuckets.map((bucket, index) => (
                <article
                  key={bucket.title}
                  className="rounded-[20px] border border-border/70 bg-card p-5 shadow-sm sm:rounded-[24px] sm:p-6"
                >
                  <div className="flex items-center justify-between gap-4">
                    <div className="flex size-11 items-center justify-center rounded-2xl bg-warning-50 text-warning-700 sm:size-12">
                      {index === 0 ? <FileCheck2 className="size-5" /> : index === 1 ? <FolderKanban className="size-5" /> : <ShieldCheck className="size-5" />}
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
          )}
        </div>
      </section>

      <section className="border-y border-border/70 bg-gradient-to-b from-background to-info-50/45 py-12 sm:py-20">
        <div className={`${pageShellClass} space-y-8 sm:space-y-10`}>
          <SectionHeading
            eyebrow={liveCatalog ? "Preparation Tips" : "Preparation"}
            title={
              liveCatalog
                ? "Nhìn nhanh bộ hồ sơ theo nhóm việc cần chuẩn bị"
                : "Chuẩn bị hồ sơ gọn hơn nếu chia theo nhóm việc"
            }
            description={
              liveCatalog
                ? "Khối này đang tổng hợp từ checklist public thật để người học thấy nhanh tài liệu nào thường phải upload, tài liệu nào chỉ cần đối chiếu và mục nào dễ thay đổi theo phương thức."
                : "Ngay cả khi chưa nối dữ liệu thật, public site vẫn nên hướng dẫn người học chuẩn bị hồ sơ theo nhóm việc thay vì một danh sách dài."
            }
          />

          {liveCatalog ? (
            <div className="grid gap-4 lg:grid-cols-3">
              {[
                {
                  title: "Tài liệu thường phải upload",
                  description: "Những giấy tờ xuất hiện trong checklist với yêu cầu tải file lên hệ thống.",
                  items: uploadDocuments,
                  icon: Upload,
                },
                {
                  title: "Tài liệu chủ yếu để đối chiếu",
                  description: "Các giấy tờ có thể được yêu cầu kiểm tra checklist hoặc nộp bản cứng sau.",
                  items: checklistDocuments,
                  icon: FolderKanban,
                },
                {
                  title: "Tài liệu thay đổi theo phương thức",
                  description: "Những giấy tờ chỉ xuất hiện khi method-specific override được cấu hình.",
                  items: overrideDocuments,
                  icon: ShieldCheck,
                },
              ].map((bucket, index) => {
                const Icon = bucket.icon

                return (
                  <article
                    key={bucket.title}
                    className="rounded-[20px] border border-border/70 bg-card p-5 shadow-sm sm:rounded-[24px] sm:p-6"
                  >
                    <div className="flex items-center justify-between gap-4">
                      <div className="flex size-11 items-center justify-center rounded-2xl bg-info-50 text-info-700 sm:size-12">
                        <Icon className="size-5" />
                      </div>
                      <span className="text-sm font-semibold text-muted-foreground">0{index + 1}</span>
                    </div>
                    <h3 className="mt-4 text-lg font-semibold tracking-tight font-display sm:text-xl">{bucket.title}</h3>
                    <p className="mt-3 text-sm leading-6 text-muted-foreground">{bucket.description}</p>
                    <div className="mt-5 flex flex-wrap gap-2">
                      {bucket.items.length > 0 ? (
                        bucket.items.slice(0, 8).map((item) => (
                          <span
                            key={`${bucket.title}-${item.document_type_id}`}
                            className="rounded-full bg-muted px-3 py-1 text-xs font-medium text-foreground"
                          >
                            {item.document_type_name}
                          </span>
                        ))
                      ) : (
                        <span className="text-sm text-muted-foreground">Đang cập nhật theo cấu hình public.</span>
                      )}
                    </div>
                  </article>
                )
              })}
            </div>
          ) : (
            <div className="grid gap-4 lg:grid-cols-3">
              {publicDocumentBuckets.map((bucket, index) => (
                <article
                  key={`${bucket.title}-fallback`}
                  className="rounded-[20px] border border-border/70 bg-card p-5 shadow-sm sm:rounded-[24px] sm:p-6"
                >
                  <div className="flex items-center justify-between gap-4">
                    <div className="flex size-11 items-center justify-center rounded-2xl bg-info-50 text-info-700 sm:size-12">
                      {index === 0 ? <Upload className="size-5" /> : index === 1 ? <FolderKanban className="size-5" /> : <ShieldCheck className="size-5" />}
                    </div>
                    <span className="text-sm font-semibold text-muted-foreground">0{index + 1}</span>
                  </div>
                  <h3 className="mt-4 text-lg font-semibold tracking-tight font-display sm:text-xl">{bucket.title}</h3>
                  <p className="mt-3 text-sm leading-6 text-muted-foreground">{bucket.description}</p>
                  <div className="mt-5 flex flex-wrap gap-2">
                    {bucket.items.map((item) => (
                      <span key={item} className="rounded-full bg-muted px-3 py-1 text-xs font-medium text-foreground">
                        {item}
                      </span>
                    ))}
                  </div>
                </article>
              ))}
            </div>
          )}
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
              Khi checklist hồ sơ đã rõ, phụ huynh thường chuyển sang so sánh học phí và ưu đãi đầu vào
            </h2>
            <p className="mt-3 text-sm leading-7 text-muted-foreground sm:text-base">
              Public site nên dẫn tiếp sang trang học phí và học bổng để người học cân đối chi phí, xem chính
              sách ưu đãi active và chuẩn bị quyết định nộp hồ sơ hoàn chỉnh.
            </p>

            <div className="mt-6 flex flex-col gap-3 sm:flex-row">
              <Button asChild size="lg" className="touch-target">
                <Link href="/tuyen-sinh/hoc-phi-hoc-bong">
                  Sang trang học phí
                  <ArrowRight />
                </Link>
              </Button>
              <Button asChild variant="outline" size="lg" className="touch-target">
                <Link href="/tuyen-sinh/phuong-thuc">Xem lại phương thức</Link>
              </Button>
            </div>
          </article>
        </div>
      </section>
    </PublicAdmissionsShell>
  )
}
