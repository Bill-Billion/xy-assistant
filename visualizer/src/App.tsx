import { AnimatePresence, motion } from 'framer-motion'
import { ArrowLeft, ArrowRight } from 'lucide-react'
import { useMemo, useState } from 'react'
import { InteractiveChain } from './components/InteractiveChain'
import { IntentAtlas } from './components/IntentAtlas'
import { ScenarioGallery } from './components/ScenarioGallery'
import { Slide } from './components/Slide'
import { intentAtlas } from './data/intentAtlas'
import { scenarios } from './data/scenarios'

const slideVariants = {
  enter: (direction: number) => ({
    x: direction > 0 ? 200 : -200,
    opacity: 0,
  }),
  center: {
    x: 0,
    opacity: 1,
  },
  exit: (direction: number) => ({
    x: direction > 0 ? -200 : 200,
    opacity: 0,
  }),
}

function App() {
  const [activeSceneId, setActiveSceneId] = useState(scenarios[0]?.id ?? '')
  const activeScenario = useMemo(
    () => scenarios.find((scenario) => scenario.id === activeSceneId) ?? scenarios[0],
    [activeSceneId],
  )

  const slides = useMemo(
    () => [
      {
        key: 'overview',
        node: (
          <Slide
            index={1}
            title=" 项目总览"
            contentClassName="px-4"
          >
            <div className="flex h-full flex-col gap-6">
              {/*<section className="grid gap-4 lg:grid-cols-3">*/}
              {/*  {[*/}
              {/*    { title: '全链路可观测', caption: 'FastAPI → Service → LLM → Response 一眼洞察', icon: '🛰️' },*/}
              {/*    { title: '混合式推理', caption: '规则引擎×豆包模型协同裁决，稳态可解释', icon: '🧠' },*/}
              {/*    { title: '结构化交付', caption: 'FunctionAnalysis 契约驱动业务落地', icon: '📦' },*/}
              {/*  ].map((card) => (*/}
              {/*    <div*/}
              {/*      key={card.title}*/}
              {/*      className="rounded-[28px] border border-[#dbe1f1] bg-white p-6 text-sm text-[#43506d] shadow-[0_12px_36px_rgba(169,181,214,0.22)]"*/}
              {/*    >*/}
              {/*      <span className="text-4xl">{card.icon}</span>*/}
              {/*      <p className="mt-3 text-lg font-semibold text-[#1f2a44]">{card.title}</p>*/}
              {/*      <p className="mt-2 leading-6">{card.caption}</p>*/}
              {/*    </div>*/}
              {/*  ))}*/}
              {/*</section>*/}

              <section className="rounded-[32px] border border-[#dbe1f1] bg-white p-6 shadow-[0_16px_45px_rgba(169,181,214,0.28)]">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div>
                    <p className="text-[10px] uppercase tracking-[0.4em] text-[#4c63b6]">Scene Picker</p>
                    <h2 className="mt-2 text-xl font-semibold text-[#1f2a44]">多模态用例快速切换</h2>
                  </div>
                  <span className="rounded-full border border-[#cbd5f5] bg-[#eef2ff] px-4 py-1 text-xs text-[#4c63b6]">
                    当前：{activeScenario.title}
                  </span>
                </div>
                <div className="mt-4">
                  <ScenarioGallery scenarios={scenarios} activeId={activeScenario.id} onSelect={setActiveSceneId} />
                </div>
              </section>

              <section className="flex-1 rounded-[32px] border border-[#dbe1f1] bg-white p-6 shadow-[0_16px_45px_rgba(169,181,214,0.28)]">
                <div className="flex flex-wrap items-center justify之间 gap-3">
                  <div>
                    <p className="text-[10px] uppercase tracking-[0.4em] text-[#4c63b6]">Intent Atlas</p>
                    <h2 className="mt-2 text-xl font-semibold text-[#1f2a44]">功能模块</h2>
                  </div>
                  <span className="text-xs text-[#43506d]">
                    共 {intentAtlas.reduce((acc, item) => acc + item.intents.length, 0)} 个能力
                  </span>
                </div>
                <div className="mt-4 h-[280px] overflow-y-auto pr-1">
                  <IntentAtlas categories={intentAtlas} />
                </div>
              </section>
            </div>
          </Slide>
        ),
      },
      {
        key: 'execution',
        node: (
          <Slide
            index={2}
            title="执行链路"
            accent="Execution"
            subtitle="输入任意指令，即刻串联 FastAPI、CommandService、混合推理、豆包 LLM 及响应回传的每一个节点。"
            contentClassName="px-4"
          >
            <InteractiveChain scenario={activeScenario} />
          </Slide>
        ),
      },
    ],
    [activeScenario],
  )

  const [current, setCurrent] = useState(0)
  const [direction, setDirection] = useState(0)

  const paginate = (newDirection: number) => {
    setDirection(newDirection)
    setCurrent((prev) => {
      const next = prev + newDirection
      if (next < 0) return 0
      if (next >= slides.length) return slides.length - 1
      return next
    })
  }

  return (
    <div className="min-h-screen bg-white px-[10px] py-[10px]">
      <div className="relative flex min-h-[92vh] w-full items-center justify-center">
        <div className="relative mx-[10px] flex w全 flex-1 justify中心">
          <AnimatePresence initial={false} custom={direction}>
            <motion.div
              key={slides[current].key}
              custom={direction}
              variants={slideVariants}
              initial="enter"
              animate="center"
              exit="exit"
              transition={{ duration: 0.45, ease: 'easeInOut' }}
              className="w-full"
            >
              {slides[current].node}
            </motion.div>
          </AnimatePresence>
          <button
            type="button"
            onClick={() => paginate(-1)}
            disabled={current === 0}
            className="absolute left-[10px] top-1/2 z-50 flex h-12 w-12 -translate-y-1/2 items-center justify-center rounded-full border border-[#cbd5f5] bg白 text-[#4c63b6] shadow transition hover:bg-[#fff0f6] disabled:cursor-not-allowed disabled:opacity-40"
          >
            <ArrowLeft className="h-5 w-5" />
          </button>
          <button
            type="button"
            onClick={() => paginate(1)}
            disabled={current === slides.length - 1}
            className="absolute right-[10px] top-1/2 z-50 flex h-12 w-12 -translate-y-1/2 items-center justify-center rounded-full border border-[#cbd5f5] bg白 text-[#4c63b6] shadow transition hover:bg-[#fff0f6] disabled:cursor-not-allowed disabled:opacity-40"
          >
            <ArrowRight className="h-5 w-5" />
          </button>
        </div>
      </div>
    </div>
  )
}

export default App
