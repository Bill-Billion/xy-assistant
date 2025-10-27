import type { TimelineEvent } from '../types/trace'

type MetricsTimelineProps = {
  events: TimelineEvent[]
}

export function MetricsTimeline({ events }: MetricsTimelineProps) {
  return (
    <section className="rounded-2xl border border-slate-800 bg-surface-100/80 p-6 shadow-pane">
      <header className="mb-4">
        <p className="text-xs uppercase tracking-[0.2em] text-slate-400">Latency Budget</p>
        <h2 className="mt-1 text-xl font-semibold text-white">执行时间线</h2>
      </header>
      <div className="relative">
        <div className="absolute left-2 top-1 bottom-1 w-px bg-slate-800" aria-hidden />
        <ol className="space-y-5">
          {events.map((event) => (
            <li key={event.id} className="relative pl-7">
              <span className="absolute left-[-3px] top-1 h-3 w-3 rounded-full border border-brand-400/70 bg-brand-500/40 shadow-md shadow-brand-500/30" />
              <div className="flex flex-wrap items-center gap-3">
                <span className="rounded-md border border-slate-700 bg-slate-900/60 px-2 py-0.5 text-[11px] font-medium text-slate-300">
                  {event.at}
                </span>
                <h3 className="text-sm font-semibold text-white">{event.label}</h3>
                {event.durationMs != null && (
                  <span className="rounded-md border border-slate-700 bg-slate-900/60 px-2 py-0.5 text-[11px] text-slate-400">
                    {event.durationMs} ms
                  </span>
                )}
              </div>
              {event.annotation && <p className="mt-2 text-sm text-slate-300">{event.annotation}</p>}
            </li>
          ))}
        </ol>
      </div>
    </section>
  )
}
