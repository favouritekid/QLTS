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
  DemoImage,
  PublicAdmissionsShell,
  SectionHeading,
  pageShellClass,
} from "@/components/public/PublicAdmissionsShell"
import {
  publicAdmissionsCategories,
  publicAdmissionsFaq,
  publicAdmissionsJourney,
  publicAdmissionsNav,
  publicAdmissionsSupportPanels,
} from "@/lib/public-admissions/catalog"
import {
  publicAdmissionsFeaturedPages,
  publicAdmissionsMedia,
} from "@/lib/public-admissions/site"

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

const supportMedia: Record<(typeof publicAdmissionsSupportPanels)[number]["id"], keyof typeof publicAdmissionsMedia> = {
  "tuition-aid": "scholarshipAward",
  documents: "documentsDesk",
  consulting: "classroomStudy",
}

const categoryHref: Record<(typeof publicAdmissionsCategories)[number]["id"], string> = {
  "degree-level": "/tuyen-sinh/nganh-hoc",
  "offering-type": "/tuyen-sinh/nganh-hoc",
  program: "/tuyen-sinh/nganh-hoc",
  "admission-method": "/tuyen-sinh/phuong-thuc",
  "subject-group": "/tuyen-sinh/phuong-thuc",
  "document-flow": "/tuyen-sinh/ho-so",
  "admission-path": "/tuyen-sinh/phuong-thuc",
}

const supportHref: Record<(typeof publicAdmissionsSupportPanels)[number]["id"], string> = {
  "tuition-aid": "/tuyen-sinh/hoc-phi-hoc-bong",
  documents: "/tuyen-sinh/ho-so",
  consulting: "/tuyen-sinh/phuong-thuc",
}

export default function PublicAdmissionsLanding() {
  return (
    <PublicAdmissionsShell activePath="/">
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
                  Biến trang chủ thành cổng tuyển sinh public rõ ràng, dễ tra cứu và đủ sâu để dẫn tới quyết định nộp hồ sơ.
                </h1>
                <p className="max-w-2xl text-base leading-7 text-muted-foreground sm:text-xl sm:leading-8">
                  Homepage giờ đóng vai trò hub: giới thiệu tổng quan, định hướng cách tra cứu và dẫn sang ba trang
                  chi tiết về ngành học, phương thức xét tuyển, hồ sơ và học phí - học bổng.
                </p>
              </div>

              <div className="flex flex-col gap-3 sm:flex-row">
                <Button asChild size="lg" className="touch-target h-11 w-full justify-between px-5 text-sm sm:w-auto sm:justify-center sm:px-6">
                  <Link href="/tuyen-sinh/nganh-hoc">
                    Xem ngành học
                    <ArrowRight />
                  </Link>
                </Button>
                <Button asChild variant="outline" size="lg" className="touch-target h-11 w-full justify-between px-5 text-sm sm:w-auto sm:justify-center sm:px-6">
                  <Link href="/tuyen-sinh/hoc-phi-hoc-bong">Xem học phí và học bổng</Link>
                </Button>
              </div>
            </div>

            <div className="space-y-4 animate-in fade-in zoom-in-95 duration-700">
              <article className="overflow-hidden rounded-[24px] border border-border/70 bg-card shadow-lg shadow-info-100/40 sm:rounded-[28px]">
                <DemoImage asset={publicAdmissionsMedia.heroCampus} eager className="aspect-[16/10] w-full object-cover" />
                <div className="space-y-2 p-4 sm:p-5">
                  <p className="text-xs font-semibold uppercase tracking-[0.2em] text-primary">Public Admissions Hub</p>
                  <h2 className="text-xl font-semibold tracking-tight font-display sm:text-2xl">
                    Giữ homepage như một lớp định hướng, còn nội dung chi tiết được tách sang các trang con.
                  </h2>
                  <p className="text-sm leading-6 text-muted-foreground">
                    Cách tổ chức này giúp landing page gọn hơn, đồng thời mở đường cho từng route public dùng dữ liệu thật sau này.
                  </p>
                </div>
              </article>

              <div className="grid gap-4 sm:grid-cols-2">
                {[
                  {
                    asset: publicAdmissionsMedia.studentsWalk,
                    title: "Luồng khám phá",
                    description: "Trang chủ -> ngành học -> phương thức -> học phí & học bổng.",
                  },
                  {
                    asset: publicAdmissionsMedia.libraryStudy,
                    title: "Luồng dữ liệu",
                    description: "Có thể nối dần sang MajorProgram, AdmissionMethod và OfferingAcademicInfo.",
                  },
                ].map((item) => (
                  <article key={item.title} className="overflow-hidden rounded-[20px] border border-border/70 bg-card shadow-sm sm:rounded-[24px]">
                    <DemoImage asset={item.asset} className="aspect-[4/3] w-full object-cover" />
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

      <section className="border-b border-border/70 bg-background/95 py-4">
        <div className={`${pageShellClass} scroll-shadow-x overflow-x-auto`}>
          <nav className="flex w-max gap-2" aria-label="Điều hướng nhanh trong homepage tuyển sinh">
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
      </section>

      <section className="py-12 sm:py-20">
        <div className={`${pageShellClass} space-y-8 sm:space-y-10`}>
          <SectionHeading
            eyebrow="Destinations"
            title="Bốn trang con chính đã sẵn sàng để đi sâu hơn từ homepage"
            description="Thay vì dồn mọi thứ lên landing page, public site nên cho người dùng đi vào đúng lớp thông tin họ cần xem tiếp."
          />

          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
            {publicAdmissionsFeaturedPages.map((page) => (
              <article
                key={page.href}
                className="overflow-hidden rounded-[24px] border border-border/70 bg-card shadow-sm transition-all duration-300 hover:-translate-y-1 hover:shadow-lg"
              >
                <DemoImage asset={publicAdmissionsMedia[page.media]} className="aspect-[4/3] w-full object-cover" />
                <div className="space-y-3 p-5 sm:p-6">
                  <p className="text-xs font-semibold uppercase tracking-[0.2em] text-primary">{page.tag}</p>
                  <h3 className="text-xl font-semibold tracking-tight font-display">{page.title}</h3>
                  <p className="text-sm leading-6 text-muted-foreground">{page.description}</p>

                  <div className="flex flex-wrap gap-2">
                    {page.stats.map((item) => (
                      <span key={item} className="rounded-full bg-muted px-3 py-1 text-xs font-medium text-foreground">
                        {item}
                      </span>
                    ))}
                  </div>

                  <Button asChild variant="outline" size="lg" className="touch-target mt-2 w-full justify-between">
                    <Link href={page.href}>
                      Mở trang chi tiết
                      <ArrowRight />
                    </Link>
                  </Button>
                </div>
              </article>
            ))}
          </div>
        </div>
      </section>

      <section id="danh-muc" className="scroll-mt-32 border-y border-border/70 bg-gradient-to-b from-background to-info-50/45 py-12 sm:py-20">
        <div className={`${pageShellClass} space-y-8 sm:space-y-10`}>
          <SectionHeading
            eyebrow="Explore"
            title="Khám phá theo đúng nhóm thông tin mà thí sinh quan tâm nhất"
            description="Các danh mục này vẫn bám taxonomy backend, nhưng trên public site chúng nên đóng vai trò định hướng tới trang chi tiết phù hợp."
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

                  <Button asChild variant="ghost" size="lg" className="mt-4 w-full justify-between px-0 text-sm text-primary">
                    <Link href={categoryHref[category.id]}>
                      Đi tới trang liên quan
                      <ArrowRight />
                    </Link>
                  </Button>
                </article>
              )
            })}
          </div>
        </div>
      </section>

      <section id="lo-trinh" className="scroll-mt-32 py-12 sm:py-20">
        <div className={`${pageShellClass} space-y-8 sm:space-y-10`}>
          <SectionHeading
            eyebrow="Admissions Flow"
            title="Lộ trình từ tìm hiểu đến xác nhận nhập học"
            description="Landing page public nên cho thấy một flow rõ ràng để người dùng hiểu website này sẽ dẫn mình đi tiếp, không chỉ dừng ở một bài giới thiệu tổng quan."
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

      <section id="ho-tro" className="scroll-mt-32 border-y border-border/70 bg-gradient-to-b from-background to-warning-50/45 py-12 sm:py-20">
        <div className={`${pageShellClass} space-y-8 sm:space-y-10`}>
          <SectionHeading
            eyebrow="Fees & Support"
            title="Học phí, hồ sơ và tư vấn nên được nối sang lớp nội dung chi tiết"
            description="Ở landing page, các khối này chỉ cần đủ hấp dẫn để người dùng hiểu họ sẽ xem sâu hơn ở đâu tiếp theo."
          />

          <div className="grid gap-4 sm:gap-5 lg:grid-cols-3">
            {publicAdmissionsSupportPanels.map((panel) => {
              const Icon = supportIcons[panel.id]
              const image = publicAdmissionsMedia[supportMedia[panel.id]]

              return (
                <article
                  key={panel.id}
                  className="overflow-hidden rounded-[20px] border border-border/70 bg-card shadow-sm sm:rounded-[24px]"
                >
                  <DemoImage asset={image} className="aspect-[4/3] w-full object-cover" />

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

                    <Button asChild variant="ghost" size="lg" className="mt-4 w-full justify-between px-0 text-sm text-primary">
                      <Link href={supportHref[panel.id]}>
                        Mở nội dung chi tiết
                        <ArrowRight />
                      </Link>
                    </Button>
                  </div>
                </article>
              )
            })}
          </div>
        </div>
      </section>

      <section id="faq" className="scroll-mt-32 py-12 sm:py-20">
        <div className={`${pageShellClass} space-y-8 sm:space-y-10`}>
          <SectionHeading
            eyebrow="Questions"
            title="Câu hỏi thường gặp trước khi người học đi sâu vào các trang con"
            description="Phần FAQ ngắn này vẫn hữu ích ở homepage, nhưng từ đây người dùng nên có lối ra rõ ràng sang các trang chuyên sâu vừa được tách."
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

          <article className="rounded-[24px] border border-border/70 bg-card p-6 shadow-sm">
            <p className="text-sm font-semibold uppercase tracking-[0.2em] text-primary">Public Sitemap</p>
            <h2 className="mt-3 text-2xl font-semibold tracking-tight font-display sm:text-3xl">
              Từ homepage, người dùng hiện có thể đi tiếp tới 3 route công khai đầu tiên
            </h2>
            <div className="mt-6 flex flex-col gap-3 sm:flex-row">
              {publicAdmissionsFeaturedPages.map((page) => (
                <Button key={page.href} asChild variant="outline" size="lg" className="touch-target">
                  <Link href={page.href}>{page.title}</Link>
                </Button>
              ))}
            </div>
          </article>
        </div>
      </section>
    </PublicAdmissionsShell>
  )
}
