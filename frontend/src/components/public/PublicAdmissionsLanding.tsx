import Link from "next/link"
import type { LucideIcon } from "lucide-react"
import {
  ArrowRight,
  BadgeCheck,
  BookCopy,
  FileCheck2,
  Files,
  FolderKanban,
  GraduationCap,
  Layers3,
  Lightbulb,
  Route,
  ScrollText,
  ShieldCheck,
  Shapes,
  Sparkles,
  WalletCards,
} from "lucide-react"

import { Button } from "@/components/ui/button"
import {
  publicAdmissionsCategories,
  publicAdmissionsFaq,
  publicAdmissionsJourney,
  publicAdmissionsNav,
  publicAdmissionsSupportPanels,
} from "@/lib/public-admissions/catalog"

const pageShellClass = "mx-auto w-full max-w-[1400px] px-4 sm:px-8"

interface MediaAsset {
  src: string
  alt: string
  width: number
  height: number
  creditLabel: string
  creditHref: string
}

const demoMedia = {
  heroCampus: {
    src: "https://images.pexels.com/photos/31085764/pexels-photo-31085764.jpeg?auto=compress&cs=tinysrgb&w=1400",
    alt: "Khuôn viên đại học hiện đại với sinh viên sinh hoạt ngoài trời.",
    width: 1400,
    height: 875,
    creditLabel: "DΛVΞ GΛRCIΛ / Pexels",
    creditHref: "https://www.pexels.com/photo/modern-university-campus-with-students-outdoors-31085764/",
  },
  studentsWalk: {
    src: "https://images.pexels.com/photos/7973039/pexels-photo-7973039.jpeg?auto=compress&cs=tinysrgb&w=1200",
    alt: "Nhóm sinh viên đi bộ cùng nhau trong khuôn viên trường.",
    width: 1200,
    height: 800,
    creditLabel: "George Pak / Pexels",
    creditHref: "https://www.pexels.com/photo/university-students-walking-together-7973039/",
  },
  libraryStudy: {
    src: "https://images.pexels.com/photos/6549913/pexels-photo-6549913.jpeg?auto=compress&cs=tinysrgb&w=1200",
    alt: "Sinh viên học tập trong thư viện với laptop và sách.",
    width: 1200,
    height: 800,
    creditLabel: "Tima Miroshnichenko / Pexels",
    creditHref: "https://www.pexels.com/photo/college-students-studying-and-researching-6549913/",
  },
  classroomStudy: {
    src: "https://images.pexels.com/photos/8199165/pexels-photo-8199165.jpeg?auto=compress&cs=tinysrgb&w=1200",
    alt: "Sinh viên học tập trong giảng đường với máy tính và tài liệu.",
    width: 1200,
    height: 800,
    creditLabel: "Yan Krukau / Pexels",
    creditHref: "https://www.pexels.com/photo/college-students-studying-inside-a-classroom-8199165/",
  },
  documentsDesk: {
    src: "https://images.pexels.com/photos/7681333/pexels-photo-7681333.jpeg?auto=compress&cs=tinysrgb&w=1200",
    alt: "Người đang xem và sắp xếp hồ sơ giấy tờ trên bàn làm việc.",
    width: 1200,
    height: 800,
    creditLabel: "Karolina Grabowska / Pexels",
    creditHref: "https://www.pexels.com/photo/woman-sitting-beside-the-documents-7681333/",
  },
  scholarshipAward: {
    src: "https://images.pexels.com/photos/31772913/pexels-photo-31772913.jpeg?auto=compress&cs=tinysrgb&w=1200",
    alt: "Hình ảnh trao thưởng và chứng nhận cho học sinh trong buổi lễ.",
    width: 1200,
    height: 800,
    creditLabel: "Legacy of Fire / Pexels",
    creditHref: "https://www.pexels.com/photo/students-receiving-awards-at-school-ceremony-31772913/",
  },
} satisfies Record<string, MediaAsset>

const categoryIcons: Record<(typeof publicAdmissionsCategories)[number]["id"], LucideIcon> = {
  "degree-level": GraduationCap,
  "offering-type": Shapes,
  program: Layers3,
  "admission-method": BadgeCheck,
  "subject-group": BookCopy,
  "document-flow": Files,
  "admission-path": Route,
}

const journeyIcons: Record<(typeof publicAdmissionsJourney)[number]["id"], LucideIcon> = {
  discover: Sparkles,
  prepare: ScrollText,
  submit: FileCheck2,
  confirm: ShieldCheck,
}

const supportIcons: Record<(typeof publicAdmissionsSupportPanels)[number]["id"], LucideIcon> = {
  "tuition-aid": WalletCards,
  documents: FolderKanban,
  consulting: Lightbulb,
}

const supportMedia: Record<(typeof publicAdmissionsSupportPanels)[number]["id"], MediaAsset> = {
  "tuition-aid": demoMedia.scholarshipAward,
  documents: demoMedia.documentsDesk,
  consulting: demoMedia.classroomStudy,
}

function SectionHeading({
  eyebrow,
  title,
  description,
}: {
  eyebrow: string
  title: string
  description: string
}) {
  return (
    <div className="max-w-3xl space-y-3">
      <p className="text-xs font-semibold uppercase tracking-[0.22em] text-primary sm:text-sm">{eyebrow}</p>
      <h2 className="text-2xl font-bold tracking-tight text-foreground font-display sm:text-4xl">
        {title}
      </h2>
      <p className="text-sm leading-7 text-muted-foreground sm:text-lg">{description}</p>
    </div>
  )
}

function DemoImage({
  asset,
  className,
  eager = false,
}: {
  asset: MediaAsset
  className: string
  eager?: boolean
}) {
  return (
    // Temporary stock images stay on plain <img> so the page can work
    // without extra remote-image config or dev-server restarts.
    // eslint-disable-next-line @next/next/no-img-element
    <img
      src={asset.src}
      alt={asset.alt}
      width={asset.width}
      height={asset.height}
      className={className}
      loading={eager ? "eager" : "lazy"}
      fetchPriority={eager ? "high" : undefined}
      decoding="async"
      referrerPolicy="no-referrer"
    />
  )
}

export default function PublicAdmissionsLanding() {
  return (
    <div className="min-h-screen bg-background pb-8 text-foreground">
      <header className="sticky top-0 z-40 border-b border-border/70 bg-background/90 backdrop-blur">
        <div className={`${pageShellClass} flex h-16 items-center justify-between gap-3 sm:gap-6`}>
          <Link href="/" className="flex min-w-0 items-center gap-3 font-display text-base font-semibold tracking-tight sm:text-lg">
            <span className="flex size-10 items-center justify-center rounded-2xl bg-primary text-primary-foreground shadow-primary">
              Q
            </span>
            <span className="truncate">QLTS Admissions</span>
          </Link>

          <nav className="hidden items-center gap-6 lg:flex">
            {publicAdmissionsNav.map((item) => (
              <a
                key={item.href}
                href={item.href}
                className="text-sm font-medium text-muted-foreground transition-colors hover:text-foreground"
              >
                {item.label}
              </a>
            ))}
          </nav>

          <div className="flex items-center gap-2">
            <Button asChild variant="outline" size="lg" className="hidden sm:inline-flex touch-target px-4 text-sm">
              <Link href="/login">Cổng cán bộ</Link>
            </Button>
            <Button asChild size="lg" className="touch-target px-4 text-sm sm:px-5">
              <a href="#danh-muc">
                Xem chương trình
                <ArrowRight />
              </a>
            </Button>
          </div>
        </div>

        <div className="border-t border-border/60 bg-background/95 lg:hidden">
          <div className={`${pageShellClass} scroll-shadow-x overflow-x-auto py-3`}>
            <nav className="flex w-max gap-2" aria-label="Điều hướng nhanh tuyển sinh">
              {publicAdmissionsNav.map((item) => (
                <a
                  key={item.href}
                  href={item.href}
                  className="touch-target inline-flex items-center rounded-full border border-border bg-card px-4 text-sm font-medium text-foreground shadow-xs transition-colors hover:bg-muted"
                >
                  {item.label}
                </a>
              ))}
            </nav>
          </div>
        </div>
      </header>

      <main>
        <section className="relative overflow-hidden border-b border-border/70 bg-gradient-to-br from-info-50 via-background to-warning-50">
          <div className="absolute inset-0 bg-[radial-gradient(circle_at_top_right,_rgba(14,165,233,0.16),_transparent_28%),radial-gradient(circle_at_bottom_left,_rgba(245,158,11,0.12),_transparent_32%)]" />
          <div className={`${pageShellClass} relative py-12 sm:py-20 lg:py-28`}>
            <div className="grid items-start gap-8 lg:grid-cols-[1.1fr_0.9fr] lg:gap-10">
              <div className="space-y-6 sm:space-y-8 animate-in fade-in slide-in-from-bottom-4 duration-700">
                <div className="inline-flex items-center gap-2 rounded-full border border-primary/15 bg-background px-3 py-2 text-xs font-medium text-primary shadow-sm sm:px-4 sm:text-sm">
                  <Sparkles className="size-4" />
                  Tuyển sinh 2026
                </div>

                <div className="space-y-4 sm:space-y-5">
                  <h1 className="max-w-4xl text-3xl font-bold leading-tight tracking-tight text-foreground font-display sm:text-5xl lg:text-6xl">
                    Chọn chương trình phù hợp, xem phương thức xét tuyển và chuẩn bị hồ sơ đúng ngay từ đầu.
                  </h1>
                  <p className="max-w-2xl text-base leading-7 text-muted-foreground sm:text-xl sm:leading-8">
                    Khám phá chương trình đào tạo, điều kiện xét tuyển, học phí, học bổng và lộ trình
                    xác nhận nhập học trên một trang rõ ràng, dễ tra cứu cho cả thí sinh và phụ huynh.
                  </p>
                </div>

                <div className="flex flex-col gap-3 sm:flex-row">
                  <Button asChild size="lg" className="touch-target h-11 w-full justify-between px-5 text-sm sm:w-auto sm:justify-center sm:px-6">
                    <a href="#danh-muc">
                      Xem chương trình tuyển sinh
                      <ArrowRight />
                    </a>
                  </Button>
                  <Button asChild variant="outline" size="lg" className="touch-target h-11 w-full justify-between px-5 text-sm sm:w-auto sm:justify-center sm:px-6">
                    <a href="#ho-tro">Xem học phí và hỗ trợ</a>
                  </Button>
                </div>
              </div>

              <div className="space-y-4 animate-in fade-in zoom-in-95 duration-700">
                <article className="overflow-hidden rounded-[24px] border border-border/70 bg-card shadow-lg shadow-info-100/40 sm:rounded-[28px]">
                  <DemoImage
                    asset={demoMedia.heroCampus}
                    eager
                    className="aspect-[16/10] w-full object-cover"
                  />
                  <div className="space-y-2 p-4 sm:p-5">
                    <p className="text-xs font-semibold uppercase tracking-[0.2em] text-primary">Ảnh demo tạm thời</p>
                    <h2 className="text-xl font-semibold tracking-tight font-display sm:text-2xl">
                      Không gian học tập và môi trường sinh viên có thể được kể trực quan ngay từ hero.
                    </h2>
                    <p className="text-sm leading-6 text-muted-foreground">
                      Bộ ảnh test này chỉ dùng để kiểm tra bố cục. Khi có ảnh thật, mình có thể thay từng vị trí mà không cần đổi cấu trúc trang.
                    </p>
                  </div>
                </article>

                <div className="grid gap-4 sm:grid-cols-2">
                  {[
                    {
                      asset: demoMedia.studentsWalk,
                      title: "Đời sống sinh viên",
                      description: "Phù hợp cho thẻ chương trình, campus life hoặc hoạt động ngoại khóa.",
                    },
                    {
                      asset: demoMedia.libraryStudy,
                      title: "Không gian học tập",
                      description: "Hợp với khối ngành học, phương thức xét tuyển hoặc các section học thuật.",
                    },
                  ].map((item) => (
                    <article key={item.title} className="overflow-hidden rounded-[20px] border border-border/70 bg-card shadow-sm sm:rounded-[24px]">
                      <DemoImage
                        asset={item.asset}
                        className="aspect-[4/3] w-full object-cover"
                      />
                      <div className="space-y-2 p-4">
                        <h3 className="text-sm font-semibold text-foreground sm:text-base">{item.title}</h3>
                        <p className="text-sm leading-6 text-muted-foreground">{item.description}</p>
                      </div>
                    </article>
                  ))}
                </div>
              </div>
            </div>
          </div>
        </section>

        <section id="danh-muc" className="scroll-mt-32 py-12 sm:py-20">
          <div className={`${pageShellClass} space-y-8 sm:space-y-10`}>
            <SectionHeading
              eyebrow="Explore"
              title="Khám phá theo đúng nhóm thông tin mà thí sinh quan tâm nhất"
              description="Các danh mục này vừa thân thiện với người dùng, vừa đủ rõ để về sau nối sang dữ liệu tuyển sinh thực tế từ backend mà không phải đổi cấu trúc trang."
            />

            <div className="grid gap-4 sm:gap-5 md:grid-cols-2 xl:grid-cols-3">
              {publicAdmissionsCategories.map((category, index) => {
                const Icon = categoryIcons[category.id]
                const order = String(index + 1).padStart(2, "0")

                return (
                  <article
                    key={category.id}
                    className="group rounded-[20px] border border-border/70 bg-card p-5 shadow-sm transition-all duration-300 hover:-translate-y-1 hover:shadow-lg animate-in fade-in slide-in-from-bottom-4 sm:rounded-[24px] sm:p-6"
                    style={{ animationDelay: `${index * 70}ms` }}
                  >
                    <div className="flex items-start justify-between gap-4">
                      <div className="flex size-11 items-center justify-center rounded-2xl bg-info-50 text-info-700 sm:size-12">
                        <Icon className="size-5" />
                      </div>
                      <span className="text-sm font-semibold text-muted-foreground">{order}</span>
                    </div>

                    <h3 className="mt-4 text-lg font-semibold tracking-tight text-foreground font-display sm:mt-5 sm:text-xl">
                      {category.title}
                    </h3>
                    <p className="mt-3 text-sm leading-6 text-muted-foreground">{category.description}</p>

                    <div className="mt-4 flex flex-wrap gap-2 sm:mt-5">
                      {category.examples.map((example) => (
                        <span
                          key={example}
                          className="rounded-full bg-muted px-3 py-1 text-xs font-medium text-foreground"
                        >
                          {example}
                        </span>
                      ))}
                    </div>
                  </article>
                )
              })}
            </div>
          </div>
        </section>

        <section id="lo-trinh" className="scroll-mt-32 border-y border-border/70 bg-gradient-to-b from-background to-warning-50/60 py-12 sm:py-20">
          <div className={`${pageShellClass} space-y-8 sm:space-y-10`}>
            <SectionHeading
              eyebrow="Admissions Flow"
              title="Lộ trình từ tìm hiểu đến xác nhận nhập học"
              description="Một landing page tuyển sinh tốt không dừng ở bước giới thiệu chương trình, mà còn dẫn tiếp người học qua các bước chuẩn bị, nộp hồ sơ và xác nhận nhập học."
            />

            <div className="scroll-shadow-x -mx-4 overflow-x-auto px-4 sm:mx-0 sm:px-0 lg:overflow-visible">
              <div className="grid auto-cols-[85%] grid-flow-col gap-4 lg:grid-flow-row lg:grid-cols-4 lg:auto-cols-fr lg:gap-5">
                {publicAdmissionsJourney.map((step) => {
                  const Icon = journeyIcons[step.id]

                  return (
                    <article
                      key={step.id}
                      className="rounded-[20px] border border-border/70 bg-card p-5 shadow-sm sm:rounded-[24px] sm:p-6"
                    >
                      <div className="flex items-center justify-between gap-4">
                        <div className="flex size-11 items-center justify-center rounded-2xl bg-warning-50 text-warning-700 sm:size-12">
                          <Icon className="size-5" />
                        </div>
                        <span className="rounded-full bg-primary/10 px-3 py-1 text-xs font-semibold uppercase tracking-[0.18em] text-primary">
                          {step.status}
                        </span>
                      </div>

                      <h3 className="mt-4 text-lg font-semibold tracking-tight font-display sm:mt-5 sm:text-xl">{step.title}</h3>
                      <p className="mt-3 text-sm leading-6 text-muted-foreground">{step.description}</p>
                    </article>
                  )
                })}
              </div>
            </div>
          </div>
        </section>

        <section id="ho-tro" className="scroll-mt-32 py-12 sm:py-20">
          <div className={`${pageShellClass} space-y-8 sm:space-y-10`}>
            <SectionHeading
              eyebrow="Fees & Support"
              title="Học phí, học bổng, hồ sơ và tư vấn nên nằm cùng một mạch thông tin"
              description="Đây là nhóm nội dung mà phụ huynh và thí sinh thường tìm ngay sau khi xem chương trình. Khi đặt cạnh nhau, trang tuyển sinh sẽ giúp quyết định nhanh và tự tin hơn."
            />

            <div className="grid gap-4 sm:gap-5 lg:grid-cols-3">
              {publicAdmissionsSupportPanels.map((panel) => {
                const Icon = supportIcons[panel.id]
                const image = supportMedia[panel.id]

                return (
                  <article
                    key={panel.id}
                    className="overflow-hidden rounded-[20px] border border-border/70 bg-card shadow-sm sm:rounded-[24px]"
                  >
                    <DemoImage
                      asset={image}
                      className="aspect-[4/3] w-full object-cover"
                    />

                    <div className="p-5 sm:p-6">
                      <div className="flex size-11 items-center justify-center rounded-2xl bg-success-50 text-success-700 sm:size-12">
                        <Icon className="size-5" />
                      </div>

                      <h3 className="mt-4 text-lg font-semibold tracking-tight font-display sm:mt-5 sm:text-xl">{panel.title}</h3>
                      <p className="mt-3 text-sm leading-6 text-muted-foreground">{panel.description}</p>

                      <ul className="mt-4 space-y-3 sm:mt-5">
                        {panel.points.map((point) => (
                          <li key={point} className="flex items-start gap-3 text-sm text-foreground">
                            <span className="mt-1 size-2 rounded-full bg-success" />
                            <span className="leading-6">{point}</span>
                          </li>
                        ))}
                      </ul>
                    </div>
                  </article>
                )
              })}
            </div>
          </div>
        </section>

        <section id="faq" className="scroll-mt-32 border-t border-border/70 bg-gradient-to-b from-info-50/40 to-background py-12 sm:py-20">
          <div className={`${pageShellClass} space-y-8 sm:space-y-10`}>
            <SectionHeading
              eyebrow="Questions"
              title="Câu hỏi thí sinh và phụ huynh thường tìm trước khi nộp hồ sơ"
              description="Phần hỏi đáp ngắn giúp giảm việc phải nhảy qua nhiều bài viết khác nhau, đồng thời cũng là nền tốt để mở rộng sang trang FAQ chuyên sâu về sau."
            />

            <div className="grid gap-4 sm:gap-5 lg:grid-cols-2">
              {publicAdmissionsFaq.map((item) => (
                <article key={item.question} className="rounded-[20px] border border-border/70 bg-card p-5 shadow-sm sm:rounded-[24px] sm:p-6">
                  <h3 className="text-base font-semibold tracking-tight text-foreground font-display sm:text-lg">
                    {item.question}
                  </h3>
                  <p className="mt-3 text-sm leading-7 text-muted-foreground">{item.answer}</p>
                </article>
              ))}
            </div>

            <div className="rounded-[24px] border border-border/70 bg-card p-5 shadow-sm sm:p-6">
              <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
                <div className="space-y-2">
                  <p className="text-sm font-semibold text-foreground">Nguồn ảnh demo tạm thời</p>
                  <p className="text-sm leading-6 text-muted-foreground">
                    Bộ ảnh hiện tại lấy từ các ảnh stock miễn phí để bạn test bố cục. Khi có ảnh thật, mình có thể thay trực tiếp từng vị trí mà không cần sửa layout.
                  </p>
                </div>
                <div className="flex flex-wrap gap-2">
                  {Object.values(demoMedia).map((asset) => (
                    <a
                      key={asset.creditHref}
                      href={asset.creditHref}
                      target="_blank"
                      rel="noreferrer"
                      className="inline-flex items-center rounded-full border border-border bg-background px-3 py-2 text-xs font-medium text-foreground transition-colors hover:bg-muted"
                    >
                      {asset.creditLabel}
                    </a>
                  ))}
                </div>
              </div>
            </div>
          </div>
        </section>
      </main>

      <footer className="border-t border-border/70 bg-card py-8">
        <div className={`${pageShellClass} flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between`}>
          <div>
            <p className="text-lg font-semibold tracking-tight font-display">QLTS Admissions</p>
            <p className="mt-1 text-sm text-muted-foreground">
              Khám phá thông tin tuyển sinh, chuẩn bị hồ sơ và theo dõi các bước xác nhận nhập học trên cùng một trang.
            </p>
          </div>

          <div className="flex flex-col gap-3 sm:flex-row">
            <Button asChild variant="outline" size="lg" className="touch-target w-full sm:w-auto">
              <Link href="/login">Đăng nhập quản trị</Link>
            </Button>
            <Button asChild size="lg" className="touch-target w-full sm:w-auto">
              <a href="#danh-muc">
                Quay lại danh mục
                <ArrowRight />
              </a>
            </Button>
          </div>
        </div>
      </footer>
    </div>
  )
}
