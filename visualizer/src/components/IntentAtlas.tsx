import { motion } from 'framer-motion'
import type { IntentCategory } from '../data/intentAtlas'

type IntentAtlasProps = {
  categories: IntentCategory[]
}

export function IntentAtlas({ categories }: IntentAtlasProps) {
  return (
    <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
      {categories.map((category, index) => {
        const Icon = category.icon
        return (
          <motion.div
            key={category.id}
            initial={{ opacity: 0, y: 16 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: index * 0.04, duration: 0.3, ease: 'easeOut' }}
            className="rounded-[24px] border border-[#dbe1f1] bg-white p-6 shadow-[0_8px_28px_rgba(169,181,214,0.2)]"
          >
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-3">
                <div className="flex h-10 w-10 items-center justify-center rounded-2xl bg-gradient-to-br from-[#4c63b6] to-[#5b7ac8] text-white shadow">
                  <Icon className="h-5 w-5" />
                </div>
                <h3 className="text-lg font-semibold text-[#1f2a44]">{category.title}</h3>
              </div>
              <span className="text-xs uppercase tracking-[0.3em] text-[#6d7c9b]">
                x{category.intents.length}
              </span>
            </div>
            <div className="mt-4 grid grid-cols-2 gap-2 text-sm text-[#43506d] sm:grid-cols-3">
              {category.intents.map((intent) => (
                <span
                  key={intent}
                  className="rounded-2xl border border-[#cbd5f5] bg-[#eef2ff] px-3 py-1 text-xs font-medium text-[#4c63b6]"
                >
                  {intent}
                </span>
              ))}
            </div>
          </motion.div>
        )
      })}
    </div>
  )
}
