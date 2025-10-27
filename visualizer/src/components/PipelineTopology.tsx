import { motion } from 'framer-motion'
import type { LucideIcon } from 'lucide-react'
import { Bolt, Cpu, GitBranch, Layers, MessageSquareCode, Sparkles } from 'lucide-react'
import type { TraceEdge, TraceNode } from '../types/trace'

const statusStyles: Record<
  TraceNode['status'],
  { badge: string; border: string; Icon: LucideIcon; label: string }
> = {
  pending: {
    badge: 'bg-slate-800/80 text-slate-300 border border-slate-700',
    border: 'border-slate-700',
    Icon: GitBranch,
    label: '待命',
  },
  running: {
    badge: 'bg-brand-400/10 text-brand-100 border border-brand-400/40',
    border: 'border-brand-300/60',
    Icon: Bolt,
    label: '执行',
  },
  success: {
    badge: 'bg-emerald-400/10 text-emerald-200 border border-emerald-400/40',
    border: 'border-emerald-400/40',
    Icon: Sparkles,
    label: '完成',
  },
  degraded: {
    badge: 'bg-amber-400/15 text-amber-200 border border-amber-500/40',
    border: 'border-amber-500/40',
    Icon: Layers,
    label: '降级',
  },
  failed: {
    badge: 'bg-rose-500/20 text-rose-200 border border-rose-500/40',
    border: 'border-rose-500/40',
    Icon: Bolt,
    label: '失败',
  },
}

const nodeIconMap: Record<string, LucideIcon> = {
  ingress: Layers,
  'command-service': GitBranch,
  'intent-classifier': MessageSquareCode,
  'doubao-client': Cpu,
  'conversation-manager': Layers,
  'response-composer': Sparkles,
}

type PipelineTopologyProps = {
  nodes: TraceNode[]
  edges: TraceEdge[]
}

export function PipelineTopology({ nodes, edges }: PipelineTopologyProps) {
  const outward = edges.reduce<Record<string, string[]>>((map, edge) => {
    if (!map[edge.source]) map[edge.source] = []
    map[edge.source].push(edge.target)
    return map
  }, {})

  return (
    <section className="rounded-3xl border border-slate-800/70 bg-surface-100/80 p-6 shadow-pane">
      <header className="mb-4 flex items-center justify-between">
        <div>
          <p className="text-xs uppercase tracking-[0.3em] text-slate-500">Execution Graph</p>
          <h2 className="mt-2 text-lg font-semibold text-white">链路节点概览</h2>
        </div>
        <span className="rounded-full border border-brand-400/40 bg-brand-500/10 px-4 py-1 text-xs font-medium text-brand-100">
          FastAPI → Rules → LLM → Response
        </span>
      </header>
      <ol className="space-y-3">
        {nodes.map((node, index) => {
          const status = statusStyles[node.status] ?? statusStyles.success
          const Icon = nodeIconMap[node.id] ?? Layers
          const DownIcons = status.Icon
          const downstream = outward[node.id] ?? []
          return (
            <motion.li
              key={node.id}
              initial={{ opacity: 0, x: -12 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ delay: index * 0.05, duration: 0.3, ease: 'easeOut' }}
              className="relative"
            >
              <div className={`rounded-2xl border ${status.border} bg-slate-900/40 px-4 py-3 backdrop-blur-sm`}>
                <div className="flex items-center justify-between gap-3">
                  <div className="flex items-center gap-3">
                    <span className="flex h-10 w-10 items-center justify-center rounded-2xl border border-white/10 bg-white/5 text-brand-100">
                      <Icon className="h-5 w-5" />
                    </span>
                    <div>
                      <p className="text-sm font-semibold text-white">{node.label}</p>
                      <p className="text-[11px] uppercase tracking-[0.3em] text-slate-500">#{node.id}</p>
                    </div>
                  </div>
                  <div className="flex items-center gap-2">
                    {node.latencyMs != null && (
                      <span className="rounded-md border border-slate-700/60 bg-slate-800/50 px-2 py-0.5 text-xs font-medium text-slate-300">
                        {node.latencyMs} ms
                      </span>
                    )}
                    <span className={`inline-flex items-center gap-1 rounded-md px-2 py-0.5 text-xs font-medium ${status.badge}`}>
                      <DownIcons className="h-3.5 w-3.5" />
                      {status.label}
                    </span>
                  </div>
                </div>
                <div className="mt-3 flex flex-wrap items-center gap-2 text-xs text-slate-400">
                  <span className="rounded-lg border border-slate-800/70 bg-slate-900/70 px-2 py-1 font-mono text-[11px] text-brand-200">
                    emits {node.outputSchema}
                  </span>
                  <span className="rounded-lg border border-slate-800/60 bg-slate-900/60 px-2 py-1">
                    {node.description}
                  </span>
                </div>
                {downstream.length > 0 && (
                  <div className="mt-3 flex flex-wrap items-center gap-1 text-[11px] text-slate-400">
                    <span className="rounded-full border border-slate-700 bg-slate-900/60 px-2 py-0.5">flow →</span>
                    {downstream.map((target) => (
                      <span
                        key={target}
                        className="rounded-full border border-slate-700/50 bg-slate-800/70 px-2 py-0.5 font-mono"
                      >
                        {target}
                      </span>
                    ))}
                  </div>
                )}
              </div>
            </motion.li>
          )
        })}
      </ol>
    </section>
  )
}
