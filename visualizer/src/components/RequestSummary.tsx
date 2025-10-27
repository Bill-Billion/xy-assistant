import { motion } from 'framer-motion'
import { Inbox, Package } from 'lucide-react'

type RequestSummaryProps = {
  endpoint: string
  payload: Record<string, unknown>
  sessionId: string
}

export function RequestSummary({ endpoint, payload, sessionId }: RequestSummaryProps) {
  return (
    <section className="rounded-3xl border border-slate-800/70 bg-slate-900/40 p-6">
      <header className="mb-4 flex items-center gap-3">
        <span className="flex h-10 w-10 items-center justify-center rounded-2xl border border-brand-400/30 bg-brand-500/10 text-brand-100">
          <Inbox className="h-5 w-5" />
        </span>
        <div>
          <p className="text-xs uppercase tracking-[0.3em] text-slate-400">Request Envelope</p>
          <h2 className="mt-1 text-lg font-semibold text-white">{endpoint}</h2>
        </div>
      </header>
      <div className="space-y-3 text-sm">
        <motion.div
          initial={{ opacity: 0, x: -12 }}
          animate={{ opacity: 1, x: 0 }}
          transition={{ duration: 0.25, ease: 'easeOut' }}
          className="flex items-center justify-between rounded-2xl border border-slate-800/70 bg-slate-900/60 px-4 py-3 font-mono text-[13px] text-slate-200"
        >
          <span>sessionId</span>
          <span className="flex items-center gap-2 text-brand-200">
            <Package className="h-4 w-4" />
            {sessionId}
          </span>
        </motion.div>
        <motion.pre
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.1, duration: 0.3, ease: 'easeOut' }}
          className="rounded-2xl border border-slate-800/70 bg-slate-950/60 p-4 text-left font-mono text-[12px] text-slate-200"
        >
          {JSON.stringify(payload, null, 2)}
        </motion.pre>
      </div>
    </section>
  )
}
