import type { ConversationTurn } from '../types/trace'

type ConversationConsoleProps = {
  conversation: ConversationTurn[]
}

const roleStyle: Record<ConversationTurn['role'], string> = {
  user: 'border-brand-500/30 bg-brand-500/10 text-brand-100',
  assistant: 'border-emerald-500/20 bg-emerald-500/10 text-emerald-100',
}

export function ConversationConsole({ conversation }: ConversationConsoleProps) {
  return (
    <section className="rounded-2xl border border-slate-800 bg-surface-100/80 p-6 shadow-pane">
      <header className="mb-4">
        <p className="text-xs uppercase tracking-[0.2em] text-slate-400">Dialogue Context</p>
        <h2 className="mt-1 text-xl font-semibold text-white">会话态回放</h2>
      </header>
      <div className="space-y-3">
        {conversation.map((turn, index) => (
          <div key={`${turn.role}-${index}`} className="flex items-start gap-3">
            <div className="mt-1 h-2 w-2 rounded-full bg-brand-400/90" />
            <div className={`w-full rounded-xl border px-3 py-2 text-sm leading-relaxed ${roleStyle[turn.role]}`}>
              <p className="text-xs uppercase tracking-[0.3em] text-slate-300">
                {turn.role === 'user' ? '呼入指令' : '小雅裁决'}
              </p>
              <p className="mt-2">{turn.content}</p>
            </div>
          </div>
        ))}
      </div>
    </section>
  )
}
