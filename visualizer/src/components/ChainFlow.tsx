import { motion } from 'framer-motion'
import type { LucideIcon } from 'lucide-react'
import {
  Braces,
  CircuitBoard,
  Cpu,
  MessageSquareCode,
  Repeat,
  Sparkle,
  Workflow,
} from 'lucide-react'
import type { TraceNode } from '../types/trace'

const nodeIconMap: Record<string, LucideIcon> = {
  ingress: Workflow,
  'command-service': CircuitBoard,
  'intent-classifier': MessageSquareCode,
  'doubao-client': Cpu,
  'conversation-manager': Repeat,
  'response-composer': Sparkle,
}

type ChainFlowProps = {
  nodes: TraceNode[]
}

export function ChainFlow({ nodes }: ChainFlowProps) {
  return (
    <div className="flex flex-col items-center gap-6">
      <motion.div
        className="flex flex-wrap items-center justify-center gap-4"
        initial="hidden"
        animate="visible"
        variants={{
          hidden: { opacity: 0, y: 12 },
          visible: {
            opacity: 1,
            y: 0,
            transition: { staggerChildren: 0.08, ease: 'easeOut', duration: 0.35 },
          },
        }}
      >
        {nodes.map((node, index) => {
          const Icon = nodeIconMap[node.id] ?? Braces
          return (
            <motion.div
              key={node.id}
              variants={{
                hidden: { opacity: 0, scale: 0.9 },
                visible: { opacity: 1, scale: 1 },
              }}
              className="relative flex items-center gap-4"
            >
              <div className="relative flex h-24 w-24 flex-col items-center justify-center rounded-3xl border border-slate-800/70 bg-slate-900/40 p-4 text-center font-medium text-slate-100">
                <span className="absolute inset-0 rounded-3xl bg-gradient-to-br from-brand-500/15 via-transparent to-transparent" />
                <Icon className="relative z-10 mb-2 h-8 w-8 text-brand-200" />
                <span className="relative z-10 text-xs uppercase tracking-[0.2em] text-slate-500">
                  {index + 1}
                </span>
                <p className="relative z-10 mt-1 text-sm">{node.label}</p>
              </div>
              {index !== nodes.length - 1 && (
                <motion.span
                  className="hidden h-px w-16 bg-gradient-to-r from-brand-400/0 via-brand-400/70 to-brand-400/0 md:block"
                  initial={{ scaleX: 0 }}
                  animate={{ scaleX: 1 }}
                  transition={{ delay: index * 0.1 + 0.2, duration: 0.4, ease: 'easeOut' }}
                />
              )}
            </motion.div>
          )
        })}
      </motion.div>
      <div className="mt-4 flex flex-wrap justify-center gap-3 text-xs text-slate-400">
        {nodes.map((node) => (
          <span key={node.id} className="rounded-full border border-slate-800/70 bg-slate-900/50 px-3 py-1 font-mono text-[11px]">
            {node.id} · {node.latencyMs}ms
          </span>
        ))}
      </div>
    </div>
  )
}
