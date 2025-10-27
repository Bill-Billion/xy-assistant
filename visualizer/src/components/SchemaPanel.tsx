import type { FunctionAnalysisSnapshot } from '../types/trace'

type SchemaPanelProps = {
  functionAnalysis: FunctionAnalysisSnapshot
}

export function SchemaPanel({ functionAnalysis }: SchemaPanelProps) {
  const rows: Array<{ label: string; value: string | number | boolean | undefined }> = [
    { label: 'result', value: functionAnalysis.result },
    { label: 'target', value: functionAnalysis.target },
    { label: 'event', value: functionAnalysis.event },
    { label: 'status', value: functionAnalysis.status },
    { label: 'confidence', value: `${Math.round(functionAnalysis.confidence * 100)}%` },
    { label: 'needClarify', value: functionAnalysis.needClarify },
    { label: 'clarifyMessage', value: functionAnalysis.clarifyMessage },
    { label: 'reasoning', value: functionAnalysis.reasoning },
    { label: 'advice', value: functionAnalysis.advice },
    { label: 'safetyNotice', value: functionAnalysis.safetyNotice },
  ]

  return (
    <section className="rounded-2xl border border-slate-800 bg-surface-100/80 p-6 shadow-pane">
      <header className="mb-4">
        <p className="text-xs uppercase tracking-[0.2em] text-slate-400">Function Analysis</p>
        <h2 className="mt-1 text-xl font-semibold text-white">结构化裁决签名</h2>
      </header>
      <div className="rounded-xl border border-slate-800/70 bg-slate-900/50">
        <table className="w-full table-fixed text-sm">
          <tbody>
            {rows.map((row) => (
              <tr key={row.label} className="border-b border-slate-800 last:border-none">
                <th className="w-32 border-r border-slate-800 px-3 py-2 text-left font-mono text-xs uppercase tracking-[0.2em] text-slate-500">
                  {row.label}
                </th>
                <td className="px-3 py-2 font-mono text-[13px] text-slate-200">
                  {row.value === undefined || row.value === null || row.value === ''
                    ? <span className="text-slate-600">∅</span>
                    : row.value}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {functionAnalysis.reasoning && (
        <p className="mt-4 rounded-lg border border-brand-500/40 bg-brand-500/10 p-3 text-sm text-brand-100">
          reasoning → {functionAnalysis.reasoning}
        </p>
      )}
    </section>
  )
}
