import Link from "next/link"
import type { ReactNode } from "react"
import { ArrowRight } from "lucide-react"

import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"
import {
  publicAdmissionsMedia,
  publicAdmissionsPrimaryLinks,
  type PublicAdmissionsMediaAsset,
} from "@/lib/public-admissions/site"

export const pageShellClass = "mx-auto w-full max-w-[1400px] px-4 sm:px-8"

interface PublicAdmissionsShellProps {
  activePath: string
  children: ReactNode
}

interface SectionHeadingProps {
  eyebrow: string
  title: string
  description: string
  align?: "left" | "center"
}

interface DemoImageProps {
  asset: PublicAdmissionsMediaAsset
  className: string
  eager?: boolean
}

interface HeroAction {
  label: string
  href: string
  variant?: "default" | "outline"
}

interface PublicAdmissionsPageHeroProps {
  eyebrow: string
  title: string
  description: string
  asset: keyof typeof publicAdmissionsMedia
  captionTitle: string
  captionDescription: string
  highlights: readonly string[]
  actions: readonly HeroAction[]
}

export function SectionHeading({
  eyebrow,
  title,
  description,
  align = "left",
}: SectionHeadingProps) {
  return (
    <div className={cn("max-w-3xl space-y-3", align === "center" && "mx-auto text-center")}>
      <p className="text-xs font-semibold uppercase tracking-[0.22em] text-primary sm:text-sm">{eyebrow}</p>
      <h2 className="text-2xl font-bold tracking-tight text-foreground font-display sm:text-4xl">
        {title}
      </h2>
      <p className="text-sm leading-7 text-muted-foreground sm:text-lg">{description}</p>
    </div>
  )
}

export function DemoImage({ asset, className, eager = false }: DemoImageProps) {
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

export function PublicAdmissionsPageHero({
  eyebrow,
  title,
  description,
  asset,
  captionTitle,
  captionDescription,
  highlights,
  actions,
}: PublicAdmissionsPageHeroProps) {
  const heroAsset = publicAdmissionsMedia[asset]

  return (
    <section className="relative overflow-hidden border-b border-border/70 bg-gradient-to-br from-info-50 via-background to-warning-50">
      <div className="absolute inset-0 bg-[radial-gradient(circle_at_top_right,_rgba(14,165,233,0.16),_transparent_28%),radial-gradient(circle_at_bottom_left,_rgba(245,158,11,0.12),_transparent_32%)]" />
      <div className={`${pageShellClass} relative py-12 sm:py-20`}>
        <div className="grid items-start gap-8 lg:grid-cols-[1.05fr_0.95fr] lg:gap-10">
          <div className="space-y-6 sm:space-y-8 animate-in fade-in slide-in-from-bottom-4 duration-700">
            <div className="inline-flex rounded-full border border-primary/15 bg-background px-4 py-2 text-xs font-medium text-primary shadow-sm sm:text-sm">
              {eyebrow}
            </div>

            <div className="space-y-4 sm:space-y-5">
              <h1 className="max-w-4xl text-3xl font-bold leading-tight tracking-tight text-foreground font-display sm:text-5xl">
                {title}
              </h1>
              <p className="max-w-2xl text-base leading-7 text-muted-foreground sm:text-xl sm:leading-8">
                {description}
              </p>
            </div>

            <div className="flex flex-wrap gap-2">
              {highlights.map((item) => (
                <span
                  key={item}
                  className="rounded-full border border-border bg-background px-3 py-2 text-xs font-medium text-foreground shadow-xs sm:text-sm"
                >
                  {item}
                </span>
              ))}
            </div>

            <div className="flex flex-col gap-3 sm:flex-row">
              {actions.map((action) => (
                <Button
                  key={action.href}
                  asChild
                  variant={action.variant ?? "default"}
                  size="lg"
                  className="touch-target h-11 w-full justify-between px-5 text-sm sm:w-auto sm:justify-center sm:px-6"
                >
                  <Link href={action.href}>
                    {action.label}
                    <ArrowRight />
                  </Link>
                </Button>
              ))}
            </div>
          </div>

          <article className="overflow-hidden rounded-[24px] border border-border/70 bg-card shadow-lg shadow-info-100/40 sm:rounded-[28px] animate-in fade-in zoom-in-95 duration-700">
            <DemoImage asset={heroAsset} eager className="aspect-[16/10] w-full object-cover" />
            <div className="space-y-2 p-4 sm:p-5">
              <p className="text-xs font-semibold uppercase tracking-[0.2em] text-primary">Thông tin tuyển sinh</p>
              <h2 className="text-xl font-semibold tracking-tight font-display sm:text-2xl">{captionTitle}</h2>
              <p className="text-sm leading-6 text-muted-foreground">{captionDescription}</p>
            </div>
          </article>
        </div>
      </div>
    </section>
  )
}

export function PublicAdmissionsShell({ activePath, children }: PublicAdmissionsShellProps) {
  return (
    <div className="min-h-screen bg-background pb-8 text-foreground">
      <header className="sticky top-0 z-40 border-b border-border/70 bg-background/90 backdrop-blur">
        <div className={`${pageShellClass} flex h-16 items-center justify-between gap-3 sm:gap-6`}>
          <Link
            href="/"
            className="flex min-w-0 items-center gap-3 font-display text-base font-semibold tracking-tight sm:text-lg"
          >
            <span className="flex size-10 items-center justify-center rounded-2xl bg-primary text-primary-foreground shadow-primary">
              Q
            </span>
            <span className="truncate">QLTS Admissions</span>
          </Link>

          <nav className="hidden items-center gap-2 lg:flex">
            {publicAdmissionsPrimaryLinks.map((item) => {
              const isActive = activePath === item.href

              return (
                <Link
                  key={item.href}
                  href={item.href}
                  className={cn(
                    "rounded-full px-4 py-2 text-sm font-medium transition-colors",
                    isActive
                      ? "bg-primary text-primary-foreground shadow-primary"
                      : "text-muted-foreground hover:bg-muted hover:text-foreground"
                  )}
                >
                  {item.label}
                </Link>
              )
            })}
          </nav>

          <div className="flex items-center gap-2">
            <Button asChild variant="outline" size="lg" className="hidden sm:inline-flex touch-target px-4 text-sm">
              <Link href="/login">Cổng cán bộ</Link>
            </Button>
            <Button asChild size="lg" className="touch-target px-4 text-sm sm:px-5">
              <Link href="/tuyen-sinh/nganh-hoc">
                Xem ngành học
                <ArrowRight />
              </Link>
            </Button>
          </div>
        </div>

        <div className="border-t border-border/60 bg-background/95 lg:hidden">
          <div className={`${pageShellClass} scroll-shadow-x overflow-x-auto py-3`}>
            <nav className="flex w-max gap-2" aria-label="Điều hướng chính tuyển sinh">
              {publicAdmissionsPrimaryLinks.map((item) => {
                const isActive = activePath === item.href

                return (
                  <Link
                    key={item.href}
                    href={item.href}
                    className={cn(
                      "touch-target inline-flex items-center rounded-full border px-4 text-sm font-medium shadow-xs transition-colors",
                      isActive
                        ? "border-primary bg-primary text-primary-foreground"
                        : "border-border bg-card text-foreground hover:bg-muted"
                    )}
                  >
                    {item.label}
                  </Link>
                )
              })}
            </nav>
          </div>
        </div>
      </header>

      <main>{children}</main>

      <footer className="border-t border-border/70 bg-card py-8">
        <div className={`${pageShellClass} flex flex-col gap-6 lg:flex-row lg:items-center lg:justify-between`}>
          <div className="max-w-2xl">
            <p className="text-lg font-semibold tracking-tight font-display">QLTS Admissions</p>
            <p className="mt-1 text-sm leading-6 text-muted-foreground">
              Cổng thông tin tuyển sinh — tra cứu chương trình đào tạo, phương thức xét tuyển, học phí và lộ trình nhập học.
            </p>
          </div>

          <div className="flex flex-wrap gap-2">
            {publicAdmissionsPrimaryLinks.map((item) => (
              <Button key={item.href} asChild variant="outline" size="lg" className="touch-target">
                <Link href={item.href}>{item.label}</Link>
              </Button>
            ))}
          </div>
        </div>

        <div className={`${pageShellClass} mt-6 flex flex-wrap gap-2`}>
          {Object.entries(publicAdmissionsMedia).map(([key, asset]) => (
            <a
              key={key}
              href={asset.creditHref}
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center rounded-full border border-border bg-background px-3 py-2 text-xs font-medium text-foreground transition-colors hover:bg-muted"
            >
              {asset.creditLabel}
            </a>
          ))}
        </div>
      </footer>
    </div>
  )
}
