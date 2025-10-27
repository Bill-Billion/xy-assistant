import type { InferenceStage } from '../types/trace'

type InferenceFlowProps = {
  stages: InferenceStage[]
}

const badgeVariants: Record<InferenceStage['artifacts'][number]['kind'], string> = {
  text: 'bg-slate-800 text-slate-200 border border-slate-700/70',
  json: 'bg-brand-500/10 text-brand-100 border border-brand-500/40',
  badge: 'bg-emerald-500/10 text-emerald-200 border border-emerald-500/40',
}

export function InferenceFlow({ stages }: InferenceFlowProps) {
  return (
    <section className="h-full rounded-2xl border border-slate-800 bg-surface/90 p-6 shadow-pane">
      <header className="mb-4">
        <p className="text-xs uppercase tracking-[0.2em] text-slate-400">Hybrid Reasoning</p>
        <h2 className="mt-1 text-2xl font-semibold text-white">规则 × 大模型 裁决矩阵</h2>
      </header>
      <div className="space-y-6">
        {stages.map((stage, index) => (
          <article
            key={stage.id}
            className="rounded-2xl border border-slate-800/70 bg-slate-900/40 p-5 transition hover:border-brand-300/70 hover:bg-slate-900/70"
          >
            <div className="flex items-start justify-between gap-4">
              <div>
                <p className="text-sm uppercase tracking-[0.3em] text-slate-500">Stage {index + 1}</p>
                <h3 className="mt-1 text-lg font-semibold text-white">{stage.title}</h3>
              </div>
              {stage.confidenceDelta && (
                <span className="rounded-lg border border-emerald-500/40 bg-emerald-500/10 px-3 py-1 text-xs font-medium text-emerald-200">
                  confidence ⇢ {Math.round(stage.confidenceDelta * 100)}%
                </span>
              )}
            </div>
            <p className="mt-3 text-sm text-slate-300">{stage.summary}</p>
            <div className="mt-4 grid gap-3 md:grid-cols-2">
              {stage.artifacts.map((item) => (
                <div
                  key={item.label}
                  className={`rounded-xl border px-3 py-3 text-sm font-mono ${badgeVariants[item.kind]}`}
                >
                  <p className="text-xs uppercase tracking-[0.25em] text-slate-400">{item.label}</p>
                  <pre className="mt-2 whitespace-pre-wrap text-left text-[13px] leading-relaxed">{item.value}</pre>
                </div>
              ))}
            </div>
            {stage.guardrails && (
              <div className="mt-4 flex flex-wrap gap-2">
                {stage.guardrails.map((guardrail) => (
                  <span
                    key={guardrail}
                    className="rounded-full border border-amber-400/50 bg-amber-500/10 px-3 py-1 text-[11px] font-medium text-amber-200"
                  >
                    {guardrail}
                  </span>
                ))}
              </div>
            )}
          </article>
        ))}
      </div>
    </section>
  )
}
