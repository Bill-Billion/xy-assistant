import type { LucideIcon } from 'lucide-react'
import { motion } from 'framer-motion'
import type { Scenario } from '../data/scenarios'

type ScenarioGalleryProps = {
  scenarios: Scenario[]
  activeId: string
  onSelect: (id: string) => void
}

export function ScenarioGallery({ scenarios, activeId, onSelect }: ScenarioGalleryProps) {
  return (
    <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
      {scenarios.map((scenario, index) => {
        const Icon = scenario.highlights[0]?.icon as LucideIcon | undefined
        const active = scenario.id === activeId
        return (
          <motion.button
            key={scenario.id}
            onClick={() => onSelect(scenario.id)}
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: index * 0.05, duration: 0.3, ease: 'easeOut' }}
            className={`group relative overflow-hidden rounded-[28px] border p-6 text-left shadow transition ${
              active
                ? 'border-[#4c63b6] bg-gradient-to-br from-[#eef2ff] via-[#f5f7ff] to-[#e3e7f3] ring-2 ring-[#4c63b6] shadow-[0_10px_30px_rgba(76,99,182,0.25)]'
                : 'border-[#dbe1f1] bg-white hover:border-[#c3cee9] hover:shadow-[0_10px_30px_rgba(161,174,209,0.25)]'
            }`}
          >
            <span
              className={`pointer-events-none absolute -right-10 -top-10 h-32 w-32 rounded-full opacity-30 blur-3xl ${
                active ? 'bg-[#4c63b6]' : 'bg-[#dbe1f1]'
              }`}
            />
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-3">
                {Icon && (
                  <div className="flex h-12 w-12 items-center justify-center rounded-2xl border border-white bg-gradient-to-br from-[#4c63b6] to-[#5b7ac8] text-white shadow-md">
                    <Icon className="h-6 w-6" />
                  </div>
                )}
                <div>
                  <p className="text-[10px] uppercase tracking-[0.4em] text-[#6d7c9b]">SCENARIO</p>
                  <h3 className="text-lg font-semibold text-[#1f2a44]">{scenario.title}</h3>
                </div>
              </div>
              <span className="text-3xl font-bold text-[#aeb6d6]">0{index + 1}</span>
            </div>
            <p className="mt-4 text-sm text-[#43506d]">{scenario.caption}</p>
            <div className="mt-4 flex flex-wrap gap-2">
              {scenario.highlights.map(({ icon: HighlightIcon, label }) => (
                <span
                  key={label}
                  className="inline-flex items-center gap-1 rounded-full border border-[#cbd5f5] bg-[#eef2ff] px-3 py-1 text-xs text-[#4c63b6]"
                >
                  <HighlightIcon className="h-3.5 w-3.5" />
                  {label}
                </span>
              ))}
            </div>
          </motion.button>
        )
      })}
    </div>
  )
}
