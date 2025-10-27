import type { ReactNode } from 'react'

type SlideProps = {
  index: number
  title: string
  subtitle?: string
  accent?: string
  children?: ReactNode
  contentClassName?: string
}

export function Slide({ index, title, subtitle, accent, children, contentClassName }: SlideProps) {
  const counter = String(index).padStart(2, '0')
  return (
    <section className="h-full w-full">
      <div className="flex min-h-[calc(100vh-20px)] flex-col rounded-[48px] border border-[#dbe1f1] bg-gradient-to-br from-[#f9faff] via-[#eef2ff] to-[#e6ebf7] p-12 shadow-[0_28px_90px_rgba(169,181,214,0.3)]">
        <header className="flex items-start justify-between border-b border-[#dbe1f1] pb-6">
          <div>
            <p className="text-[10px] uppercase tracking-[0.4em] text-[#6d7c9b]">Slide {counter}</p>
            <h2 className="mt-3 text-3xl font-semibold text-[#1f2a44]">{title}</h2>
            {subtitle && <p className="mt-3 max-w-3xl text-sm text-[#43506d]">{subtitle}</p>}
          </div>
          {accent && (
            <span className="rounded-full border border-white/70 bg-white/70 px-4 py-2 text-xs font-medium uppercase tracking-[0.4em] text-[#4c63b6] shadow">
              {accent}
            </span>
          )}
        </header>
        <div className="mt-6 flex-1 overflow-hidden">
          <div className="h-full overflow-hidden">
            <div className={`h-full overflow-y-auto pr-2 ${contentClassName ?? ''}`}>{children}</div>
          </div>
        </div>
      </div>
    </section>
  )
}
