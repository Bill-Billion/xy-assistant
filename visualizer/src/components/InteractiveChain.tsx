import { AnimatePresence, motion } from 'framer-motion'
import {
  Brackets,
  ChevronsDown,
  Crosshair,
  GitBranch,
  LoaderCircle,
  MessageSquareText,
  Puzzle,
  RotateCcw,
  Sparkles,
  Workflow,
} from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import { forwardRef, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { Scenario } from '../data/scenarios'
import type { FunctionAnalysisSnapshot } from '../types/trace'

const API_BASE = import.meta.env.VITE_API_BASE ?? 'http://0.0.0.0:8000'
const MIN_DISPLAY_DURATION = 900
const NODE_WIDTH = 170
const NODE_HEIGHT = 120
const RULE_NODE_WIDTH = 150
const RULE_NODE_HEIGHT = 96
const RULE_NODE_GAP_Y = 56
const RULE_NODE_OFFSET_X = 220

type ViewState = {
  scale: number
  translateX: number
  translateY: number
}

type StepStatus = 'idle' | 'running' | 'done'

type WorkflowNode = {
  id: string
  label: string
  description: string
  baseDuration: number
  icon: LucideIcon
  layer: number
  lane: number
  connections: string[]
}

type NodeState = WorkflowNode & {
  actualDuration: number
  displayDuration: number
  status: StepStatus
  output: string
}

type ConversationTurn = {
  role: 'user' | 'assistant'
  content: string
}

type PositionMap = Record<string, { x: number; y: number }>

type OutputsMap = Record<string, string>

type FlowBoardProps = {
  nodes: NodeState[]
  positions: PositionMap
  edges: Array<{ source: string; target: string }>
  view: ViewState
  onCanvasPointerDown: (event: React.PointerEvent<HTMLDivElement>) => void
  onCanvasWheel: (event: React.WheelEvent<HTMLDivElement>) => void
  onNodePointerDown: (id: string, event: React.PointerEvent<HTMLDivElement>) => void
  onHoverChange: (hovering: boolean) => void
  onAutoLayout: () => void
  onResetBoard: () => void
  onCenterBoard: () => void
  onCollapseDetails: () => void
  rulesExpanded: boolean
  rulePanels: RulePanelInfo[]
}

type DetailPanelProps = {
  node: NodeState
  scenario: Scenario
  analysis: FunctionAnalysisSnapshot
  conversation: ConversationTurn[]
  backendMsg: string
  commandInput: string
  rulesExpanded: boolean
  rulePanels: RulePanelInfo[]
}

type RulePanelInfo = {
  id: string
  title: string
  payload: unknown
  context: string | null
  llmSupport: string
  matched: boolean
}

export function InteractiveChain({ scenario }: { scenario: Scenario }) {
  const workflowNodes = useMemo(() => buildWorkflowNodes(scenario), [scenario])
  const workflowEdges = useMemo(
    () =>
      workflowNodes.flatMap((node) =>
        node.connections.map((target) => ({ source: node.id, target })),
      ),
    [workflowNodes],
  )
  const [rulePanels, setRulePanels] = useState<RulePanelInfo[]>(() => buildRulePanels(scenario))
  useEffect(() => {
    setRulePanels(buildRulePanels(scenario))
  }, [scenario])

  const [commandInput, setCommandInput] = useState(
    String(scenario.trace.request.payload.query ?? ''),
  )
  const [analysis, setAnalysis] = useState<FunctionAnalysisSnapshot>(
    scenario.trace.functionAnalysis,
  )
  const [conversation, setConversation] = useState<ConversationTurn[]>(
    scenario.trace.conversation,
  )
  const [backendMsg, setBackendMsg] = useState<string>(
    scenario.trace.conversation.at(-1)?.content ?? '',
  )
  const [nodes, setNodes] = useState<NodeState[]>(() => {
    const defaults = buildDefaultOutputs(scenario, commandInput)
    return workflowNodes.map((node) => ({
      ...node,
      actualDuration: node.baseDuration,
      displayDuration: Math.max(node.baseDuration, MIN_DISPLAY_DURATION),
      status: 'idle' as StepStatus,
      output: defaults[node.id] ?? '',
    }))
  })

  const [activeIndex, setActiveIndex] = useState(-1)
  const [running, setRunning] = useState(false)
  const [progress, setProgress] = useState(0)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [rulesExpanded, setRulesExpanded] = useState(false)

  const timersRef = useRef<number[]>([])
  const startTimeRef = useRef<number | null>(null)
  const displayDurationsRef = useRef<number[]>(nodes.map((node) => node.displayDuration))

  const basePositions = useMemo(() => computeInitialPositions(workflowNodes), [workflowNodes])
  const initialPositionsRef = useRef<PositionMap>(basePositions)
  const scenarioKeyRef = useRef<string | null>(null)
  const previousActiveIdRef = useRef<string | null>(null)
  const [positions, setPositions] = useState<PositionMap>(basePositions)
  const ruleNodeAnchors = useMemo(() => {
    if (!rulesExpanded || rulePanels.length === 0) return []
    const origin = positions['rule-engine']
    if (!origin) return []
    const spacing = RULE_NODE_HEIGHT + RULE_NODE_GAP_Y
    const startY = origin.y - ((rulePanels.length - 1) * spacing) / 2
    return rulePanels.map((panel, index) => ({
      panel,
      x: origin.x + NODE_WIDTH + RULE_NODE_OFFSET_X,
      y: startY + index * spacing,
    }))
  }, [positions, rulePanels, rulesExpanded])
  const nodeDragRef = useRef<{
    id: string
    offsetX: number
    offsetY: number
    startScreenX: number
    startScreenY: number
    hasMoved: boolean
  } | null>(null)
  const canvasDragRef = useRef<{
    startX: number
    startY: number
    initialX: number
    initialY: number
  } | null>(null)
  const boardRef = useRef<HTMLDivElement | null>(null)
  const bodyOverflowRef = useRef<string | null>(null)
  const viewAnimationRef = useRef<number | null>(null)
  const [view, setView] = useState<ViewState>({ scale: 1, translateX: 0, translateY: 0 })
  const viewRef = useRef(view)

  useEffect(() => {
    const initialCommand = String(scenario.trace.request.payload.query ?? '')
    setCommandInput(initialCommand)
    setAnalysis(scenario.trace.functionAnalysis)
    setConversation(scenario.trace.conversation)
    setBackendMsg(scenario.trace.conversation.at(-1)?.content ?? '')

    const outputs = buildDefaultOutputs(scenario, initialCommand)
    const baseStates = workflowNodes.map((node) => ({
      ...node,
      actualDuration: node.baseDuration,
      displayDuration: Math.max(node.baseDuration, MIN_DISPLAY_DURATION),
      status: 'idle' as StepStatus,
      output: outputs[node.id] ?? '',
    }))
    displayDurationsRef.current = baseStates.map((state) => state.displayDuration)
    clearTimers()
    setRunning(false)
    setActiveIndex(-1)
    setProgress(0)
    setNodes(baseStates)
    initialPositionsRef.current = basePositions
    setPositions(basePositions)
    setView({ scale: 1, translateX: 0, translateY: 0 })
    setRulesExpanded(false)
  }, [basePositions, scenario, workflowNodes])

  useEffect(() => {
    if (running) return
    setNodes((prev) =>
      prev.map((node) =>
        node.id === 'ingress'
          ? {
              ...node,
              output: formatJSON({
                sessionId: scenario.trace.sessionId,
                query: commandInput,
                meta: scenario.trace.request.payload.meta ?? {},
              }),
            }
          : node,
      ),
    )
  }, [commandInput, running, scenario])

  useEffect(() => {
    if (!running) {
      if (activeIndex === nodes.length - 1 && nodes.length > 0) {
        setProgress(1)
      }
      return
    }
    let frameId: number
    const tick = () => {
      if (startTimeRef.current !== null) {
        const delta = performance.now() - startTimeRef.current
        const total = displayDurationsRef.current.reduce((acc, item) => acc + item, 0) || 1
        const clamped = Math.min(delta, total)
        setProgress(Math.min(clamped / total, 1))
        if (clamped < total) {
          frameId = requestAnimationFrame(tick)
        }
      }
    }
    frameId = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(frameId)
  }, [running, nodes.length])

  useEffect(() => {
    viewRef.current = view
  }, [view])

  const restoreBodyOverflow = useCallback(() => {
    if (typeof document === 'undefined') return
    if (bodyOverflowRef.current !== null) {
      document.body.style.overflow = bodyOverflowRef.current
      bodyOverflowRef.current = null
    }
  }, [])

  const handleHoverChange = useCallback(
    (hovering: boolean) => {
      if (typeof document === 'undefined') return
      if (hovering) {
        if (bodyOverflowRef.current === null) {
          bodyOverflowRef.current = document.body.style.overflow
        }
        document.body.style.overflow = 'hidden'
      } else {
        restoreBodyOverflow()
      }
    },
    [restoreBodyOverflow],
  )

  const animateViewTo = useCallback(
    (target: Partial<ViewState>, options: { duration?: number } = {}) => {
      const duration = options.duration ?? 420
      if (viewAnimationRef.current !== null) {
        cancelAnimationFrame(viewAnimationRef.current)
        viewAnimationRef.current = null
      }
      const from = viewRef.current
      const to: ViewState = {
        scale: target.scale ?? from.scale,
        translateX: target.translateX ?? from.translateX,
        translateY: target.translateY ?? from.translateY,
      }
      if (duration <= 0) {
        setView(to)
        return
      }
      const start = performance.now()
      const step = (now: number) => {
        const rawProgress = (now - start) / duration
        const progress = clamp(rawProgress, 0, 1)
        const eased = easeOutCubic(progress)
        setView({
          scale: from.scale + (to.scale - from.scale) * eased,
          translateX: from.translateX + (to.translateX - from.translateX) * eased,
          translateY: from.translateY + (to.translateY - from.translateY) * eased,
        })
        if (progress < 1) {
          viewAnimationRef.current = requestAnimationFrame(step)
        } else {
          viewAnimationRef.current = null
        }
      }
      viewAnimationRef.current = requestAnimationFrame(step)
    },
    [],
  )

  const centerBoardOnPositions = useCallback(
    (
      positionMap: PositionMap,
      options: { duration?: number; keepScale?: boolean; targetScale?: number } = {},
    ) => {
      const container = boardRef.current
      if (!container) return
      const entries = Object.values(positionMap)
      if (!entries.length || container.clientWidth === 0 || container.clientHeight === 0) return

      let minX = Infinity
      let maxX = -Infinity
      let minY = Infinity
      let maxY = -Infinity
      entries.forEach((pos) => {
        minX = Math.min(minX, pos.x)
        maxX = Math.max(maxX, pos.x)
        minY = Math.min(minY, pos.y)
        maxY = Math.max(maxY, pos.y)
      })

      const spanX = maxX - minX + NODE_WIDTH
      const spanY = maxY - minY + NODE_HEIGHT
      const containerWidth = container.clientWidth
      const containerHeight = container.clientHeight
      const padding = 240

      let targetScale =
        options.targetScale ?? (options.keepScale ? viewRef.current.scale : undefined)

      if (targetScale === undefined) {
        const scaleX = containerWidth / (spanX + padding)
        const scaleY = containerHeight / (spanY + padding)
        targetScale = clamp(Math.min(scaleX, scaleY, 1.8), 0.6, 1.8)
      } else {
        targetScale = clamp(targetScale, 0.6, 1.8)
      }

      const centerX = minX + spanX / 2
      const centerY = minY + spanY / 2
      const translateX = containerWidth / 2 - centerX * targetScale
      const translateY = containerHeight / 2 - centerY * targetScale

      animateViewTo({ scale: targetScale, translateX, translateY }, { duration: options.duration })
    },
    [animateViewTo],
  )

  const focusNode = useCallback(
    (nodeId: string, duration = 440) => {
      const container = boardRef.current
      if (!container || container.clientWidth === 0 || container.clientHeight === 0) return
      const nodePosition = positions[nodeId]
      if (!nodePosition) return
      const scale = viewRef.current.scale
      const centerX = nodePosition.x + NODE_WIDTH / 2
      const centerY = nodePosition.y + NODE_HEIGHT / 2
      const translateX = container.clientWidth / 2 - centerX * scale
      const translateY = container.clientHeight / 2 - centerY * scale
      animateViewTo({ translateX, translateY }, { duration })
    },
    [animateViewTo, positions],
  )

  const handleAutoLayout = useCallback(() => {
    const layout = computeInitialPositions(workflowNodes)
    setPositions(layout)
    centerBoardOnPositions(layout, { duration: 360, keepScale: true })
  }, [centerBoardOnPositions, workflowNodes])

  const handleResetBoard = useCallback(() => {
    const layout = clonePositions(initialPositionsRef.current)
    setPositions(layout)
    centerBoardOnPositions(layout, { duration: 420, targetScale: 1 })
  }, [centerBoardOnPositions])

  const handleCenterBoard = useCallback(() => {
    centerBoardOnPositions(positions, { duration: 320, keepScale: true })
  }, [centerBoardOnPositions, positions])

  const handleCollapseDetails = useCallback(() => {
    setRulesExpanded(false)
  }, [])

  useEffect(() => {
    if (!boardRef.current) return
    const key = scenario.id
    if (scenarioKeyRef.current === key) return
    scenarioKeyRef.current = key
    const frame = requestAnimationFrame(() => {
      centerBoardOnPositions(initialPositionsRef.current, { duration: 0, targetScale: 1 })
    })
    return () => cancelAnimationFrame(frame)
  }, [centerBoardOnPositions, scenario.id])

  useEffect(
    () => () => {
      resetChain()
      restoreBodyOverflow()
      if (viewAnimationRef.current !== null) {
        cancelAnimationFrame(viewAnimationRef.current)
        viewAnimationRef.current = null
      }
    },
    [restoreBodyOverflow],
  )

  const handleNodeClick = useCallback(
    (id: string) => {
      const targetIndex = nodes.findIndex((node) => node.id === id)
      if (!running && targetIndex >= 0) {
        setActiveIndex(targetIndex)
        focusNode(id, 320)
      }
      if (id === 'rule-engine') {
        setRulesExpanded(true)
      } else if (rulesExpanded) {
        setRulesExpanded(false)
      }
    },
    [focusNode, nodes, rulesExpanded, running],
  )

  const ensurePositionInView = useCallback(
    (x: number, y: number, width = NODE_WIDTH, height = NODE_HEIGHT) => {
      const container = boardRef.current
      if (!container) return
      const { scale, translateX, translateY } = viewRef.current
      const margin = 160
      const left = x * scale + translateX
      const right = (x + width) * scale + translateX
      const top = y * scale + translateY
      const bottom = (y + height) * scale + translateY

      let deltaX = 0
      let deltaY = 0

      if (left < margin) deltaX = margin - left
      else if (right > container.clientWidth - margin) {
        deltaX = container.clientWidth - margin - right
      }

      if (top < margin) deltaY = margin - top
      else if (bottom > container.clientHeight - margin) {
        deltaY = container.clientHeight - margin - bottom
      }

      if (deltaX || deltaY) {
        setView((prev) => ({
          ...prev,
          translateX: prev.translateX + deltaX,
          translateY: prev.translateY + deltaY,
        }))
        if (nodeDragRef.current) {
          nodeDragRef.current = {
            ...nodeDragRef.current,
            offsetX: nodeDragRef.current.offsetX - deltaX,
            offsetY: nodeDragRef.current.offsetY - deltaY,
          }
        }
      }
    },
    [setView],
  )

  useEffect(() => {
    const handlePointerMove = (event: PointerEvent) => {
      if (nodeDragRef.current) {
        const { id, offsetX, offsetY, startScreenX, startScreenY, hasMoved } = nodeDragRef.current
        const { scale, translateX, translateY } = viewRef.current
        const newX = (event.clientX - offsetX - translateX) / scale
        const newY = (event.clientY - offsetY - translateY) / scale
        if (!hasMoved) {
          const deltaX = Math.abs(event.clientX - startScreenX)
          const deltaY = Math.abs(event.clientY - startScreenY)
          if (deltaX > 4 || deltaY > 4) {
            nodeDragRef.current = {
              ...nodeDragRef.current,
              hasMoved: true,
            }
          }
        }
        setPositions((prev) => ({
          ...prev,
          [id]: { x: newX, y: newY },
        }))
        ensurePositionInView(newX, newY)
      } else if (canvasDragRef.current) {
        const { startX, startY, initialX, initialY } = canvasDragRef.current
        setView((prev) => ({
          ...prev,
          translateX: initialX + (event.clientX - startX),
          translateY: initialY + (event.clientY - startY),
        }))
      }
    }

    const handlePointerUp = () => {
      if (nodeDragRef.current && !nodeDragRef.current.hasMoved) {
        handleNodeClick(nodeDragRef.current.id)
      }
      nodeDragRef.current = null
      canvasDragRef.current = null
    }

    window.addEventListener('pointermove', handlePointerMove)
    window.addEventListener('pointerup', handlePointerUp)
    return () => {
      window.removeEventListener('pointermove', handlePointerMove)
      window.removeEventListener('pointerup', handlePointerUp)
    }
  }, [handleNodeClick, ensurePositionInView])

  const clearTimers = () => {
    timersRef.current.forEach((id) => clearTimeout(id))
    timersRef.current = []
    startTimeRef.current = null
  }

  const resetChain = () => {
    clearTimers()
    setRunning(false)
    setActiveIndex(-1)
    setProgress(0)
    setNodes((prev) =>
      prev.map((node) => ({
        ...node,
        status: 'idle',
      })),
    )
  }

  const startPlayback = (
    actualDurations: number[],
    displayDurations: number[],
    outputs: OutputsMap,
  ) => {
    clearTimers()
    displayDurationsRef.current = displayDurations
    const updatedStates = workflowNodes.map((node, index) => ({
      ...node,
      actualDuration: actualDurations[index],
      displayDuration: displayDurations[index],
      status: (index === 0 ? 'running' : 'idle') as StepStatus,
      output: outputs[node.id] ?? '',
    }))
    setNodes(updatedStates)
    setActiveIndex(0)
    setRunning(true)
    setProgress(0)
    startTimeRef.current = performance.now()

    let elapsed = 0
    displayDurations.forEach((duration, index) => {
      const timer = window.setTimeout(() => {
        setNodes((prev) =>
          prev.map((node, idx) => {
            if (idx === index) return { ...node, status: 'done' }
            if (idx === index + 1) return { ...node, status: 'running' }
            return node
          }),
        )
        setActiveIndex((prev) => (index === displayDurations.length - 1 ? prev : index + 1))
        if (index === displayDurations.length - 1) {
          setRunning(false)
          setProgress(1)
        }
      }, elapsed + duration)
      timersRef.current.push(timer)
      elapsed += duration
    })
  }

  const handleRun = async () => {
    setError(null)
    setLoading(true)
    try {
      const payload = {
        sessionId: scenario.trace.sessionId,
        query: commandInput,
        meta: scenario.trace.request.payload.meta ?? {},
        user: scenario.trace.request.payload.user ?? '',
      }
      const t0 = performance.now()
      const response = await fetch(`${API_BASE}/api/command`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      })
      if (!response.ok) {
        throw new Error(`接口返回 ${response.status}`)
      }
      const raw = await response.json()
      const t1 = performance.now()
      const measured = Math.max(t1 - t0, 1)

      const baseTotal = workflowNodes.reduce((acc, node) => acc + (node.baseDuration || 1), 0) || 1
      const actualDurations = workflowNodes.map((node) =>
        Math.max((node.baseDuration / baseTotal) * measured, 1),
      )
      const displayDurations = actualDurations.map((value) =>
        Math.max(value, MIN_DISPLAY_DURATION),
      )

      const faRaw = raw.function_analysis ?? raw.functionAnalysis ?? {}
      const updatedAnalysis: FunctionAnalysisSnapshot = {
        result: faRaw.result ?? analysis.result ?? '',
        target: faRaw.target ?? analysis.target ?? '',
        event: faRaw.event ?? analysis.event ?? undefined,
        status: faRaw.status ?? analysis.status ?? undefined,
        confidence: typeof faRaw.confidence === 'number'
          ? faRaw.confidence
          : Number(faRaw.confidence ?? analysis.confidence ?? 0),
        needClarify: Boolean(
          faRaw.need_clarify ?? faRaw.needClarify ?? analysis.needClarify ?? false,
        ),
        clarifyMessage: faRaw.clarify_message ?? faRaw.clarifyMessage ?? analysis.clarifyMessage,
        reasoning: faRaw.reasoning ?? analysis.reasoning,
        advice: faRaw.advice ?? analysis.advice,
        safetyNotice: faRaw.safety_notice ?? faRaw.safetyNotice ?? analysis.safetyNotice,
      }
      setAnalysis(updatedAnalysis)

      const assistantMsg: string =
        raw.msg ?? raw.message ?? updatedAnalysis.clarifyMessage ?? '执行完毕。'
      setBackendMsg(assistantMsg)
      setConversation([
        { role: 'user', content: commandInput },
        { role: 'assistant', content: assistantMsg },
      ])

      const llmOutput =
        raw.raw_llm_output ?? raw.rawLLMOutput ?? raw.raw ?? parseLLMOutputFallback(updatedAnalysis)

      const derivedRulePanels = buildRulePanelsFromResponse(raw, scenario)
      const panelsForOutputs =
        derivedRulePanels.length > 0
          ? derivedRulePanels
          : rulePanels.length > 0
            ? rulePanels
            : buildRulePanels(scenario)
      if (derivedRulePanels.length > 0) {
        setRulePanels(derivedRulePanels)
      }

      const outputs = buildOutputsFromResponse(
        payload,
        updatedAnalysis,
        assistantMsg,
        llmOutput,
        scenario,
        panelsForOutputs,
      )
      if (derivedRulePanels.length > 0) {
        setRulesExpanded(true)
      }
      startPlayback(actualDurations, displayDurations, outputs)
    } catch (err) {
      setError(
        err instanceof Error ? `调用失败：${err.message}` : '调用失败，请确认后端服务可用。',
      )
      resetChain()
    } finally {
      setLoading(false)
    }
  }

  const handleNodePointerDown = (id: string, event: React.PointerEvent<HTMLDivElement>) => {
    event.preventDefault()
    const current = positions[id]
    if (!current) return
    const { scale, translateX, translateY } = viewRef.current
    const screenX = translateX + current.x * scale
    const screenY = translateY + current.y * scale
    nodeDragRef.current = {
      id,
      offsetX: event.clientX - screenX,
      offsetY: event.clientY - screenY,
      startScreenX: event.clientX,
      startScreenY: event.clientY,
      hasMoved: false,
    }
  }

  const handleCanvasPointerDown = (event: React.PointerEvent<HTMLDivElement>) => {
    event.preventDefault()
    canvasDragRef.current = {
      startX: event.clientX,
      startY: event.clientY,
      initialX: viewRef.current.translateX,
      initialY: viewRef.current.translateY,
    }
  }

  const handleCanvasWheel = (event: React.WheelEvent<HTMLDivElement>) => {
    event.preventDefault()
    event.stopPropagation()
    const { scale, translateX, translateY } = viewRef.current
    const rect = event.currentTarget.getBoundingClientRect()
    const cursorX = event.clientX - rect.left
    const cursorY = event.clientY - rect.top
    const delta = -event.deltaY * 0.0015
    const newScale = clamp(scale + delta, 0.6, 1.8)
    const scaleRatio = newScale / scale
    const newTranslateX = cursorX - scaleRatio * (cursorX - translateX)
    const newTranslateY = cursorY - scaleRatio * (cursorY - translateY)
    setView({ scale: newScale, translateX: newTranslateX, translateY: newTranslateY })
  }

  const activeNodeId =
    activeIndex >= 0 ? nodes[activeIndex]?.id : nodes.length > 0 ? nodes[0]?.id : undefined
  const activeNode = nodes[Math.max(activeIndex, 0)] ?? nodes[0]

  useEffect(() => {
    if (!running) return
    if (!activeNodeId) return
    if (previousActiveIdRef.current === activeNodeId) return
    previousActiveIdRef.current = activeNodeId
    focusNode(activeNodeId)
  }, [activeNodeId, focusNode, running])

  useEffect(() => {
    if (!running) {
      previousActiveIdRef.current = null
    }
  }, [running])

  useEffect(() => {
    if (activeNodeId !== 'rule-engine' && rulesExpanded) {
      setRulesExpanded(false)
    }
  }, [activeNodeId, rulesExpanded])

  useEffect(() => {
    if (!rulesExpanded || ruleNodeAnchors.length === 0) return
    const target = ruleNodeAnchors.find((anchor) => anchor.panel.matched) ?? ruleNodeAnchors[0]
    if (target) {
      ensurePositionInView(target.x, target.y, RULE_NODE_WIDTH, RULE_NODE_HEIGHT)
    }
  }, [ensurePositionInView, ruleNodeAnchors, rulesExpanded])

  return (
    <div className="flex h-full flex-col gap-6">
      <div className="rounded-[36px] border border-[#dbe1f1] bg-[#f7f9ff] p-8 shadow-[0_12px_40px_rgba(169,181,214,0.25)]">
        <div className="flex flex-col gap-4 xl:flex-row xl:items-center xl:justify-between">
          <div className="w-full xl:max-w-xl">
            <p className="text-[10px] uppercase tracking-[0.4em] text-[#6d7c9b]">输入指令</p>
            <div className="mt-3 flex items-center gap-3">
              <input
                value={commandInput}
                onChange={(event) => setCommandInput(event.target.value)}
                placeholder="请输入指令，例如：请帮我定一个明早8点的闹钟"
                className="flex-1 rounded-3xl border border-[#cbd5f5] bg-white px-5 py-3 text-sm text-[#1f2a44] shadow-inner outline-none transition focus:border-[#4c63b6] focus:ring-2 focus:ring-[#4c63b6]/40"
              />
              <button
                type="button"
                onClick={handleRun}
                disabled={loading}
                className="group rounded-3xl bg-gradient-to-r from-[#4c63b6] to-[#5b7ac8] px-6 py-3 text-sm font-semibold text-white shadow-lg transition hover:brightness-105 disabled:cursor-not-allowed disabled:opacity-60"
              >
                {loading ? (
                  <span className="flex items-center gap-2">
                    <LoaderCircle className="h-4 w-4 animate-spin" />
                    调用中…
                  </span>
                ) : (
                  '开始链路演示'
                )}
              </button>
            </div>
          </div>
          <div className="rounded-3xl border border-[#dbe1f1] bg-white px-4 py-3 text-xs text-[#1f2a44] shadow-inner">
            <p>链路总时长（实测）</p>
            <p className="mt-2 text-lg font-semibold text-[#4c63b6]">
              {formatMs(displayDurationsRef.current.reduce((acc, item) => acc + item, 0))}
            </p>
            <p className="mt-1 text-[11px] uppercase tracking-[0.3em] text-[#6d7c9b]">
              当前进度 {Math.round(progress * 100)}%
            </p>
          </div>
        </div>
        {error && (
          <p className="mt-3 rounded-2xl border border-[#f2b8b5] bg-[#fdecea] px-4 py-3 text-xs text-[#a23c3c]">
            {error}
          </p>
        )}
      </div>

      <div className="flex-1 flex flex-col gap-6 xl:flex-row xl:items-stretch">
        <div className="relative flex-1 min-h-[calc(100vh-220px)] xl:flex-[0_0_70%] xl:max-w-[70%] xl:h-full">
          <FlowBoard
            ref={boardRef}
            nodes={nodes}
            positions={positions}
            edges={workflowEdges}
            view={view}
            onCanvasPointerDown={handleCanvasPointerDown}
            onCanvasWheel={handleCanvasWheel}
            onNodePointerDown={handleNodePointerDown}
            onHoverChange={handleHoverChange}
            onAutoLayout={handleAutoLayout}
            onResetBoard={handleResetBoard}
            onCenterBoard={handleCenterBoard}
            onCollapseDetails={handleCollapseDetails}
            rulesExpanded={rulesExpanded}
            rulePanels={rulePanels}
          />
        </div>
        <div className="mt-6 flex flex-col overflow-hidden rounded-[32px] border border-[#dbe1f1] bg-white shadow-[0_16px_48px_rgba(169,181,214,0.3)] xl:mt-0 xl:flex-[0_0_30%] xl:max-w-[30%] xl:h-full">
          <header className="border-b border-[#dbe1f1] px-6 py-5">
            <p className="text-[10px] uppercase tracking-[0.4em] text-[#6d7c9b]">步骤详情</p>
            <div className="mt-3 flex flex-wrap items-center gap-3 text-sm">
              <span className="rounded-full bg-[#eef2ff] px-3 py-1 font-medium text-[#4c63b6]">
                {activeNode.label}
              </span>
              <span className="rounded-full bg-[#f3f5fb] px-3 py-1 text-[#1f2a44]">
                耗时 {formatMs(activeNode.actualDuration)}
              </span>
            </div>
          </header>
          <AnimatePresence mode="wait">
            <motion.div
              key={activeNode.id}
              initial={{ opacity: 0, x: 30 }}
              animate={{ opacity: 1, x: 0 }}
              exit={{ opacity: 0, x: -30 }}
              transition={{ duration: 0.35, ease: 'easeInOut' }}
              className="flex-1 overflow-auto px-6 py-5 text-sm text-[#1f2a44]"
            >
              <DetailPanel
                node={activeNode}
                scenario={scenario}
                analysis={analysis}
                conversation={conversation}
                backendMsg={backendMsg}
                commandInput={commandInput}
                rulesExpanded={rulesExpanded}
                rulePanels={rulePanels}
              />
            </motion.div>
          </AnimatePresence>
        </div>
      </div>
    </div>
  )
}

const FlowBoard = forwardRef<HTMLDivElement, FlowBoardProps>(function FlowBoard(
  {
    nodes,
    positions,
    edges,
    view,
    onCanvasPointerDown,
    onCanvasWheel,
    onNodePointerDown,
    onHoverChange,
    onAutoLayout,
    onResetBoard,
    onCenterBoard,
    onCollapseDetails,
    rulesExpanded,
    rulePanels,
  },
  ref,
) {
  const { scale, translateX, translateY } = view

  const statusBadge: Record<StepStatus, { text: string; color: string; bg: string }> = {
    idle: { text: '待命', color: '#6d7c9b', bg: '#f3f5fb' },
    running: { text: '执行中', color: '#4c63b6', bg: '#eef2ff' },
    done: { text: '完成', color: '#2a9d8f', bg: '#e6f4f1' },
  }

  const nodeMap = useMemo(
    () =>
      nodes.reduce<Record<string, NodeState>>((acc, node) => {
        acc[node.id] = node
        return acc
      }, {}),
    [nodes],
  )

  const ruleNodes = useMemo(() => {
    if (!rulesExpanded || !rulePanels.length) return [] as Array<{ id: string; x: number; y: number; matched: boolean; title: string }>
    const origin = positions['rule-engine']
    if (!origin) return []
    const spacing = RULE_NODE_HEIGHT + RULE_NODE_GAP_Y
    const startY = origin.y - ((rulePanels.length - 1) * spacing) / 2
    return rulePanels.map((panel, index) => ({
      id: panel.id,
      title: panel.title,
      matched: panel.matched,
      x: origin.x + NODE_WIDTH + RULE_NODE_OFFSET_X,
      y: startY + index * spacing,
    }))
  }, [positions, rulePanels, rulesExpanded])

  const rulePanelMap = useMemo(() => {
    const map = new Map<string, RulePanelInfo>()
    rulePanels.forEach((panel) => map.set(panel.id, panel))
    return map
  }, [rulePanels])

  const ruleEnginePos = positions['rule-engine']
  const harmonizerPos = positions['harmonizer']

  const containerRef = useRef<HTMLDivElement | null>(null)
  const [containerSize, setContainerSize] = useState({ width: 1200, height: 680 })

  const setCombinedRef = useCallback(
    (node: HTMLDivElement | null) => {
      containerRef.current = node
      if (typeof ref === 'function') {
        ref(node)
      } else if (ref) {
        ;(ref as React.MutableRefObject<HTMLDivElement | null>).current = node
      }
    },
    [ref],
  )

  useEffect(() => {
    const element = containerRef.current
    if (!element) return
    const observer = new ResizeObserver((entries) => {
      for (const entry of entries) {
        const { width, height } = entry.contentRect
        setContainerSize({
          width: Math.max(width, 600),
          height: Math.max(height, 420),
        })
      }
    })
    observer.observe(element)
    return () => observer.disconnect()
  }, [])

  const scaledWidth = 2000
  const scaledHeight = 2000

  return (
    <div
      ref={setCombinedRef}
      className="relative h-full min-h-[calc(100vh-220px)] w-full overflow-hidden rounded-[32px] border border-[#dbe1f1] bg-gradient-to-br from-[#f8f9fc] to-[#eef2ff] shadow-inner"
      onWheel={(event) => {
        onHoverChange(true)
        onCanvasWheel(event)
      }}
      onPointerEnter={() => onHoverChange(true)}
      onPointerLeave={() => onHoverChange(false)}
      onPointerDown={(event) => {
        if (event.target === event.currentTarget) {
          onCanvasPointerDown(event)
        }
      }}
    >
      <div className="absolute bottom-6 left-1/2 z-30 -translate-x-1/2">
        <div className="flex items-center gap-4 rounded-full bg-white/90 px-6 py-3 text-[#2f3b59] shadow-[0_16px_36px_rgba(180,192,224,0.45)] backdrop-blur">
          <ControlButton
            icon={Sparkles}
            label="自动整理"
            onClick={onAutoLayout}
          />
          <ControlButton
            icon={RotateCcw}
            label="回归原样"
            onClick={onResetBoard}
          />
          <ControlButton
            icon={ChevronsDown}
            label="收起细节"
            onClick={onCollapseDetails}
          />
          <ControlButton
            icon={Crosshair}
            label="画布居中"
            onClick={onCenterBoard}
          />
        </div>
      </div>
      <div
        className="absolute left-0 top-0"
        style={{
          width: scaledWidth,
          height: scaledHeight,
          transform: `translate(${translateX}px, ${translateY}px) scale(${scale})`,
          transformOrigin: '0 0',
        }}
        onPointerDown={onCanvasPointerDown}
      >
        <svg
          width={scaledWidth}
          height={scaledHeight}
          viewBox={`0 0 ${scaledWidth} ${scaledHeight}`}
          className="absolute inset-0"
        >
          <defs>
            <marker id="arrow" markerWidth="12" markerHeight="12" refX="10" refY="6" orient="auto">
              <polygon points="0 0, 12 6, 0 12" fill="#4c63b6" />
            </marker>
          </defs>
          {edges.map((edge) => {
            const source = positions[edge.source]
            const target = positions[edge.target]
            if (!source || !target) return null
            if (rulesExpanded && edge.source === 'rule-engine' && edge.target === 'harmonizer') {
              return null
            }

            const startX = source.x + NODE_WIDTH
            const startY = source.y + NODE_HEIGHT / 2
            const endX = target.x
            const endY = target.y + NODE_HEIGHT / 2
            const midX = (startX + endX) / 2

            const sourceStatus = nodeMap[edge.source]?.status ?? 'idle'
            const targetStatus = nodeMap[edge.target]?.status ?? 'idle'
            const isActive = sourceStatus === 'running' || targetStatus === 'running'
            const isDone = sourceStatus === 'done'

            const stroke = isActive ? '#4c63b6' : isDone ? '#2a9d8f' : '#cbd5f5'
            const strokeWidth = isActive ? 4 : 2.5
            const outputPreview = truncate(nodeMap[edge.source]?.output ?? '—', 48)

            return (
              <g key={`${edge.source}-${edge.target}`}>
                <path
                  d={`M ${startX} ${startY} C ${midX} ${startY}, ${midX} ${endY}, ${endX} ${endY}`}
                  fill="none"
                  stroke={stroke}
                  strokeWidth={strokeWidth}
                  markerEnd="url(#arrow)"
                />
                <text
                  x={midX}
                  y={(startY + endY) / 2 - 12}
                  textAnchor="middle"
                  fontSize="11"
                  fill="#6d7c9b"
                >
                  {outputPreview}
                </text>
              </g>
            )
          })}
          {rulesExpanded && ruleEnginePos &&
            ruleNodes.map((node) => {
              const startX = ruleEnginePos.x + NODE_WIDTH
              const startY = ruleEnginePos.y + NODE_HEIGHT / 2
              const endX = node.x
              const endY = node.y + RULE_NODE_HEIGHT / 2
              const midX = (startX + endX) / 2
              const panel = rulePanelMap.get(node.id)
              const isMatched = panel?.matched ?? false
              const stroke = isMatched ? '#ff7b54' : '#aeb6d9'
              const strokeWidth = isMatched ? 4 : 2.5
              const dash = isMatched ? undefined : '6 6'
              return (
                <g key={`rule-edge-${node.id}`}>
                  <path
                    d={`M ${startX} ${startY} C ${midX} ${startY}, ${midX} ${endY}, ${endX} ${endY}`}
                    fill="none"
                    stroke={stroke}
                    strokeWidth={strokeWidth}
                    strokeDasharray={dash}
                    markerEnd="url(#arrow)"
                  />
                  <text
                    x={midX}
                    y={(startY + endY) / 2 - 12}
                    textAnchor="middle"
                    fontSize="11"
                    fill={isMatched ? '#ff7b54' : '#6d7c9b'}
                  >
                    {panel?.title ?? '规则'}
                  </text>
                </g>
              )
            })}
          {rulesExpanded && ruleNodes.length > 0 && harmonizerPos &&
            ruleNodes.map((node) => {
              const startX = node.x + RULE_NODE_WIDTH
              const startY = node.y + RULE_NODE_HEIGHT / 2
              const endX = harmonizerPos.x
              const endY = harmonizerPos.y + NODE_HEIGHT / 2
              const midX = (startX + endX) / 2
              const panel = rulePanelMap.get(node.id)
              const isMatched = panel?.matched ?? false
              const stroke = isMatched ? '#4c63b6' : '#cbd5f5'
              const strokeWidth = isMatched ? 4 : 2
              const dash = isMatched ? undefined : '5 5'
              return (
                <g key={`rule-harmonizer-edge-${node.id}`}>
                  <path
                    d={`M ${startX} ${startY} C ${midX} ${startY}, ${midX} ${endY}, ${endX} ${endY}`}
                    fill="none"
                    stroke={stroke}
                    strokeWidth={strokeWidth}
                    strokeDasharray={dash}
                    markerEnd="url(#arrow)"
                  />
                </g>
              )
            })}
        </svg>

        {nodes.map((node) => {
          const statusStyle = statusBadge[node.status]
          const position = positions[node.id] ?? { x: 0, y: 0 }
          return (
            <div
              key={node.id}
              className={`absolute w-[170px] rounded-[24px] border p-4 text-left transition ${
                node.status === 'running'
                  ? 'border-[#4c63b6] bg-[#eef2ff] shadow-[0_12px_30px_rgba(76,99,182,0.25)]'
                  : node.status === 'done'
                    ? 'border-[#2a9d8f] bg-[#e6f4f1]'
                    : 'border-[#dbe1f1] bg-white'
              }`}
              style={{ left: position.x, top: position.y, cursor: 'grab' }}
              onPointerDown={(event) => {
                event.stopPropagation()
                onNodePointerDown(node.id, event)
              }}
            >
              <div className="flex items-center justify-between">
                <span className="rounded-xl bg-gradient-to-br from-[#4c63b6] to-[#5b7ac8] p-2 text白 shadow">
                  <node.icon className="h-5 w-5" />
                </span>
                <span
                  className="rounded-xl px-2 py-1 text-[11px] font-medium"
                  style={{ color: statusStyle.color, backgroundColor: statusStyle.bg }}
                >
                  {statusStyle.text}
                </span>
              </div>
              <p className="mt-3 text-sm font-semibold text-[#1f2a44]">{node.label}</p>
              <p
                className="mt-3 text-xs text-[#43506d]"
                style={{
                  display: '-webkit-box',
                  WebkitLineClamp: 4,
                  WebkitBoxOrient: 'vertical',
                  overflow: 'hidden',
                }}
              >
                {node.output || '等待执行…'}
              </p>
            </div>
          )
        })}
        {rulesExpanded &&
          ruleNodes.map((ruleNode) => {
            const panel = rulePanelMap.get(ruleNode.id)
            const matched = panel?.matched ?? false
            return (
              <div
                key={`rule-node-${ruleNode.id}`}
                className={`absolute flex flex-col rounded-[20px] border p-4 text-xs transition ${
                  matched ? 'border-[#34a853] bg-[#e7f7ee] shadow-[0_10px_26px_rgba(52,168,83,0.22)]' : 'border-[#dbe1f1] bg-white'
                }`}
                style={{
                  left: ruleNode.x,
                  top: ruleNode.y,
                  width: RULE_NODE_WIDTH,
                  height: RULE_NODE_HEIGHT,
                }}
              >
                <div className="flex items-center justify-between">
                  <span className="rounded-xl bg-gradient-to-br from-[#5b7ac8] to-[#6d8fe0] p-2 text-white shadow">
                    <Puzzle className="h-4 w-4" />
                  </span>
                  <span className={`rounded-full px-2 py-1 text-[10px] font-medium ${matched ? 'bg-[#ccf2d9] text-[#1f5130]' : 'bg-[#f3f5fb] text-[#6d7c9b]'}`}>
                    {matched ? '命中' : '候选'}
                  </span>
                </div>
                <p className="mt-3 text-sm font-semibold text-[#1f2a44]">{ruleNode.title}</p>
              </div>
            )
          })}
      </div>
    </div>
  )
})

type ControlButtonProps = {
  icon: LucideIcon
  label: string
  onClick: () => void
}

function ControlButton({ icon: Icon, label, onClick }: ControlButtonProps) {
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      className="pointer-events-auto flex flex-col items-center gap-1 text-xs font-medium text-[#4c63b6] transition hover:text-[#2f3b59]"
      onClick={(event) => {
        event.stopPropagation()
        onClick()
      }}
    >
      <span className="flex h-11 w-11 items-center justify-center rounded-full bg-gradient-to-br from-[#e7ecff] to-[#ffffff] shadow-[0_6px_18px_rgba(145,163,204,0.35)]">
        <Icon className="h-5 w-5" />
      </span>
      {label}
    </button>
  )
}


function DetailPanel({
  node,
  scenario,
  analysis,
  conversation,
  backendMsg,
  commandInput,
  rulesExpanded,
  rulePanels,
}: DetailPanelProps) {
  switch (node.id) {
    case 'ingress':
      return (
        <div className="space-y-4">
          <p className="text-base font-semibold text-[#2f3b59]">路由绑定 · CommandRequest</p>
          <pre className="rounded-[24px] border border-[#dbe1f1] bg-[#f5f7fb] p-4 font-mono text-[12px] leading-6 text-[#1f2a44] shadow-inner">
            {formatJSON({
              sessionId: scenario.trace.sessionId,
              query: commandInput,
              meta: scenario.trace.request.payload.meta ?? {},
            })}
          </pre>
          <div className="flex flex-wrap gap-2 text-xs text-[#43506d]">
            <Tag>FastAPI 路由</Tag>
            <Tag>Pydantic 校验</Tag>
            <Tag>结构化日志</Tag>
          </div>
        </div>
      )
    case 'command-service':
      return (
        <div className="grid gap-4 lg:grid-cols-2">
          <Card title="会话上下文合并" content="载入 ConversationManager 中的历史轮次与候选用户，确保多轮对话语境一致。" />
          <Card title="Meta 同步" content="将 payload.meta 与 user 字段统一写入 meta_payload 传递给推理层。" />
          <Card title="日志监控" content="logger.info 输出 session_id / query / meta，便于链路追踪与审计留痕。" />
          <Card title="兜底策略" content="异常时构造 need_clarify=True 的 FunctionAnalysis，保证前端体验稳定。" />
        </div>
      )
    case 'rule-engine': {
      const ruleStage = scenario.trace.inference.stages[0]
      const llmStage =
        scenario.trace.inference.stages.find((stage) => stage.id === 'llm-synthesis') ??
        scenario.trace.inference.stages[1]

      const laneSummary = (ruleStage?.summary ?? '').split('→').map((chunk) => chunk.trim()).filter(Boolean)
      const guardrails = ruleStage?.guardrails ?? []

      const matchingFlow = [
        {
          title: '规则初筛',
          description: laneSummary[0] || '枚举正则/关键词模板，快速筛出候选意图。',
        },
        {
          title: 'LLM 佐证',
          description:
            llmStage?.summary || '将命中样本连同上下文拼装提示词，让豆包对候选意图打分。',
        },
        {
          title: 'Guardrail',
          description:
            guardrails.join('，') || '应用兜底安全策略，确保输出符合业务白名单与风控要求。',
        },
      ]

      const matchedRule = rulePanels.find((panel) => panel.matched) ?? null
      const matchedRuleLabel = matchedRule?.title ?? '—'
      const matchedPayloadDisplay =
        matchedRule && typeof matchedRule.payload === 'object'
          ? formatJSON(matchedRule.payload)
          : typeof matchedRule?.payload === 'string'
            ? matchedRule.payload
            : '—'

      return (
        <div className="space-y-5">
          <div>
            <p className="text-base font-semibold text-[#2f3b59]">规则引擎 × 大模型协同</p>
            <p className="mt-2 text-sm text-[#43506d]">
              规则引擎先行筛选候选 → LLM 语义校验 → Harmonizer 融合落地，数据流向：Rule Engine → Harmonizer → Response。
            </p>
            <div className="mt-4 grid gap-3 md:grid-cols-3">
              {matchingFlow.map((item, idx) => (
                <div
                  key={`${item.title}-${idx}`}
                  className="rounded-[24px] border border-[#dbe1f1] bg-white p-4 text-sm text-[#1f2a44] shadow-inner"
                >
                  <p className="text-xs uppercase tracking-[0.3em] text-[#6d7c9b]">{item.title}</p>
                  <p className="mt-2 leading-6 text-[#2f3b59]">{item.description}</p>
                </div>
              ))}
            </div>
          </div>

          {!rulesExpanded ? (
            <div className="space-y-3 rounded-[28px] border border-[#dbe1f1] bg-white p-5 text-sm text-[#1f2a44] shadow-[0_12px_30px_rgba(208,215,238,0.35)]">
              <p className="text-xs uppercase tracking-[0.35em] text-[#6d7c9b]">命中规则</p>
              <p className="text-lg font-semibold text-[#2f3b59]">{matchedRuleLabel}</p>
              <pre className="max-h-40 overflow-auto rounded-[18px] border border-dashed border-[#cbd5f5] bg-[#f7f9ff] p-3 font-mono text-[12px] leading-6 text-[#1f2a44]">
                {matchedPayloadDisplay}
              </pre>
              <p className="text-xs text-[#6d7c9b]">提示：点击左侧「规则引擎」节点可展开全部规则明细。</p>
            </div>
          ) : (
            <div className="grid gap-4 lg:grid-cols-2">
              {rulePanels.map((panel) => (
                <div
                  key={panel.id}
                  className={`space-y-3 rounded-[28px] border bg-white p-5 text-sm text-[#1f2a44] shadow-[0_12px_30px_rgba(208,215,238,0.45)] ${
                    panel.matched ? 'border-[#4c63b6] ring-2 ring-[#4c63b6]/20' : 'border-[#dbe1f1]'
                  }`}
                >
                  <header className="flex items-center justify-between">
                    <span className="rounded-full bg-[#eef2ff] px-3 py-1 text-xs font-semibold text-[#4c63b6]">
                      {panel.title}
                    </span>
                    <span className="text-xs text-[#6d7c9b]">{panel.matched ? '已命中' : '候选'}</span>
                  </header>
                  {panel.context && <p className="text-xs text-[#43506d]">{panel.context}</p>}
                  <section className="rounded-[20px] border border-dashed border-[#cbd5f5] bg-[#f7f9ff] p-3">
                    <p className="text-[11px] uppercase tracking-[0.35em] text-[#6d7c9b]">规则命中元数据</p>
                    <pre className="mt-2 max-h-40 overflow-auto font-mono text-[12px] leading-6 text-[#1f2a44]">
                      {typeof panel.payload === 'string' ? panel.payload : formatJSON(panel.payload)}
                    </pre>
                  </section>
                  <section className="rounded-[20px] border border-[#e3e8fb] bg-[#fdfdff] p-3">
                    <p className="text-[11px] uppercase tracking-[0.35em] text-[#6d7c9b]">LLM 匹配说明</p>
                    <p className="mt-2 text-xs leading-6 text-[#2f3b59]">{panel.llmSupport}</p>
                  </section>
                </div>
              ))}
            </div>
          )}
        </div>
      )

    }
    case 'llm-synthesis':
      return (
        <div className="space-y-4">
          <p className="text-base font-semibold text-[#2f3b59]">豆包 LLM 推理</p>
          <p className="text-xs text-[#43506d]">
            使用{' '}
            <code className="rounded-full border border-[#cbd5f5] bg-[#eef2ff] px-2 py-1 font-mono text-[11px] text-[#4c63b6]">
              {`response_format={"type": "json_object"}`}
            </code>{' '}
            限制输出为可解析 JSON，并在失败时自动退避重试三次。
          </p>
          <pre className="rounded-[24px] border border-[#cbd5f5] bg-[#eef2ff] p-4 font-mono text-[12px] leading-6 text-[#1f2a44] shadow-inner">
            {summarizeStage(scenario, 1) || '—'}
          </pre>
        </div>
      )
    case 'harmonizer':
      return (
        <div className="space-y-4">
          <p className="text-base font-semibold text-[#2f3b59]">结果融合 · Harmonizer</p>
          <pre className="rounded-[24px] border border-[#dbe1f1] bg-[#f5f7fb] p-4 font-mono text-[12px] leading-6 text-[#1f2a44] shadow-inner">
            {summarizeStage(scenario, 2) || '—'}
          </pre>
          <div className="flex flex-wrap gap-2 text-xs text-[#43506d]">
            <Tag>规则/LLM 置信度取 max</Tag>
            <Tag>allowed_results 校验</Tag>
            <Tag>安全提示兜底</Tag>
          </div>
        </div>
      )
    case 'conversation-manager':
      return (
        <div className="space-y-4">
          <p className="text-base font-semibold text-[#2f3b59]">会话态快照</p>
          <div className="rounded-[24px] border border-[#dbe1f1] bg-[#f5f7fb] p-4 text-xs text-[#1f2a44]">
            <ul className="space-y-3">
              {conversation.map((turn, index) => (
                <li
                  key={`${turn.role}-${index}`}
                  className="rounded-[20px] border border-[#dbe1f1] bg-white px-4 py-3 shadow-sm"
                >
                  <p className="text-[10px] uppercase tracking-[0.3em] text-[#4c63b6]">
                    {turn.role === 'user' ? '用户' : '助手'}
                  </p>
                  <p className="mt-2 text-sm text-[#1f2a44]">{turn.content}</p>
                </li>
              ))}
            </ul>
          </div>
          <div className="flex flex-wrap gap-2 text-xs text-[#43506d]">
            <Tag>TTLCache 30 分钟</Tag>
            <Tag>pending_clarification</Tag>
            <Tag>user_candidates</Tag>
          </div>
        </div>
      )
    case 'response-composer':
      return (
        <div className="space-y-4">
          <p className="text-base font-semibold text-[#2f3b59]">结构化裁决</p>
          <div className="grid gap-3 md:grid-cols-3">
            <InfoTile label="result" value={analysis.result || '—'} />
            <InfoTile label="target" value={analysis.target || '—'} />
            <InfoTile
              label="confidence"
              value={`${Math.round((analysis.confidence ?? 0) * 100)}%`}
            />
            <InfoTile label="needClarify" value={analysis.needClarify ? '需要' : '不需要'} />
            <InfoTile label="clarifyMessage" value={analysis.clarifyMessage || '—'} />
            <InfoTile label="advice" value={analysis.advice || '—'} />
          </div>
          {analysis.reasoning && (
            <div className="rounded-[24px] border border-[#dbe1f1] bg-[#eef2ff] p-4 text-sm text-[#1f2a44] shadow-inner">
              推理说明：{analysis.reasoning}
            </div>
          )}
          <div className="rounded-[24px] border border-[#dbe1f1] bg-[#f9f9fd] p-4 text-sm text-[#1f2a44] shadow-inner">
            返回话术：{backendMsg}
          </div>
        </div>
      )
    default:
      return (
        <div className="flex h-full items-center justify-center text-[#6d7c9b]">
          点击「开始链路演示」查看详细执行过程。
        </div>
      )
  }
}

function buildWorkflowNodes(scenario: Scenario): WorkflowNode[] {
  const basePipeline = scenario.trace.pipeline
  const latencyOf = (id: string, fallback: number) =>
    basePipeline.nodes.find((node) => node.id === id)?.latencyMs ?? fallback

  return [
    {
      id: 'ingress',
      label: 'FastAPI 路由',
      description: '接收 HTTP 请求并构造 CommandRequest',
      baseDuration: latencyOf('ingress', 120),
      icon: Workflow,
      layer: 0,
      lane: 0,
      connections: ['command-service'],
    },
    {
      id: 'command-service',
      label: 'CommandService',
      description: '会话上下文整理 + 调用意图识别',
      baseDuration: latencyOf('command-service', 180),
      icon: GitBranch,
      layer: 1,
      lane: 0,
      connections: ['rule-engine', 'llm-synthesis'],
    },
    {
      id: 'rule-engine',
      label: '规则引擎',
      description: '关键词/正则识别 + 置信度估计',
      baseDuration: 140,
      icon: Puzzle,
      layer: 2,
      lane: 0,
      connections: ['harmonizer'],
    },
    {
      id: 'llm-synthesis',
      label: '豆包 LLM',
      description: '上下文增强提示 → JSON 裁决',
      baseDuration: latencyOf('doubao-client', 820),
      icon: MessageSquareText,
      layer: 2,
      lane: 1,
      connections: ['harmonizer'],
    },
    {
      id: 'harmonizer',
      label: '结果融合',
      description: '规则/LLM 合并 + 安全提示补全',
      baseDuration: latencyOf('intent-classifier', 118),
      icon: Brackets,
      layer: 3,
      lane: 0,
      connections: ['conversation-manager'],
    },
    {
      id: 'conversation-manager',
      label: '会话管理',
      description: 'TTLCache 持久化对话及澄清状态',
      baseDuration: latencyOf('conversation-manager', 100),
      icon: Puzzle,
      layer: 4,
      lane: 0,
      connections: ['response-composer'],
    },
    {
      id: 'response-composer',
      label: '响应拼装',
      description: '模板渲染 + FunctionAnalysis 返回',
      baseDuration: latencyOf('response-composer', 80),
      icon: MessageSquareText,
      layer: 5,
      lane: 0,
      connections: [],
    },
  ]
}

function computeInitialPositions(nodes: WorkflowNode[]): PositionMap {
  const LAYER_GAP = 210
  const LANE_GAP = 150
  const START_X = 40
  const START_Y = 80
  return nodes.reduce<PositionMap>((acc, node) => {
    acc[node.id] = {
      x: START_X + node.layer * LAYER_GAP,
      y: START_Y + node.lane * LANE_GAP,
    }
    return acc
  }, {})
}

function clonePositions(map: PositionMap): PositionMap {
  const result: PositionMap = {}
  Object.entries(map).forEach(([key, value]) => {
    result[key] = { ...value }
  })
  return result
}

function formatRuleOutput(raw: unknown, fallback: string): string {
  const ruleName = extractRuleName(raw)
  if (ruleName) {
    return `命中规则: ${ruleName}\n${fallback}`
  }
  return fallback
}

function extractRuleName(raw: unknown): string | null {
  if (!raw) return null
  if (typeof raw === 'string') {
    const parsed = tryParseJSON(raw)
    if (parsed && typeof parsed === 'object') {
      return extractRuleName(parsed)
    }
    const match = raw.match(/"(?:intent|rule|result)"\s*:\s*"([^"}]+)"/i)
    return match ? match[1] : null
  }
  if (typeof raw === 'object') {
    const candidate = (raw as Record<string, unknown>)
    for (const key of ['intent', 'rule', 'result', 'name']) {
      const value = candidate[key]
      if (typeof value === 'string' && value.trim()) {
        return value
      }
    }
  }
  return null
}

function buildRulePanels(scenario: Scenario): RulePanelInfo[] {
  const stages = scenario.trace.inference.stages ?? []
  const ruleStage = findRuleStage(stages)
  if (!ruleStage) return []
  const llmStage = findLlmStage(stages)
  return createRulePanelsFromStages(ruleStage, llmStage)
}

function buildRulePanelsFromResponse(raw: unknown, fallback: Scenario): RulePanelInfo[] {
  const stages = extractStages(raw)
  if (!stages.length) return buildRulePanels(fallback)
  const ruleStage = findRuleStage(stages)
  if (!ruleStage) return buildRulePanels(fallback)
  const llmStage = findLlmStage(stages)
  return createRulePanelsFromStages(ruleStage, llmStage)
}

function extractStages(raw: unknown): any[] {
  if (!raw || typeof raw !== 'object') return []
  const candidate = raw as Record<string, unknown>
  if (Array.isArray(candidate.stages)) return candidate.stages as any[]
  const inference = candidate.inference
  if (inference && typeof inference === 'object' && Array.isArray((inference as Record<string, unknown>).stages)) {
    return ((inference as Record<string, unknown>).stages ?? []) as any[]
  }
  const trace = candidate.trace
  if (trace && typeof trace === 'object' && Array.isArray((trace as Record<string, unknown>).stages)) {
    return ((trace as Record<string, unknown>).stages ?? []) as any[]
  }
  return []
}

function findRuleStage(stages: any[]): any | null {
  return (
    stages.find((stage) => stage?.id === 'rule-engine') ??
    stages.find((stage) => typeof stage?.id === 'string' && stage.id.toLowerCase().includes('rule')) ??
    stages.find((stage) => typeof stage?.title === 'string' && stage.title.toLowerCase().includes('rule')) ??
    null
  )
}

function findLlmStage(stages: any[]): any | null {
  return (
    stages.find((stage) => stage?.id === 'llm-synthesis') ??
    stages.find((stage) => typeof stage?.id === 'string' && stage.id.toLowerCase().includes('llm')) ??
    stages.find((stage) => typeof stage?.title === 'string' && stage.title.toLowerCase().includes('llm')) ??
    null
  )
}

function createRulePanelsFromStages(ruleStage: any, llmStage: any | null): RulePanelInfo[] {
  const artifacts = Array.isArray(ruleStage?.artifacts) ? ruleStage.artifacts : []
  const llmArtifacts = Array.isArray(llmStage?.artifacts) ? llmStage.artifacts : []

  return artifacts.map((artifact: any, index: number) => {
    const parsed = tryParseJSON(artifact?.value ?? artifact)
    const title =
      (parsed && typeof parsed === 'object' && 'intent' in parsed && parsed.intent) ||
      (parsed && typeof parsed === 'object' && 'rule' in parsed && parsed.rule) ||
      artifact?.label ||
      `规则 ${index + 1}`
    const context =
      (parsed && typeof parsed === 'object' && 'explain' in parsed && parsed.explain) ||
      (parsed && typeof parsed === 'object' && 'reason' in parsed && parsed.reason) ||
      null
    const llmSupport =
      (llmArtifacts[index]?.value as string | undefined) ??
      (typeof llmStage?.summary === 'string' ? llmStage.summary : '—')

    return {
      id: `${artifact?.label ?? 'rule'}-${index}`,
      title: String(title),
      payload: parsed ?? artifact?.value ?? artifact,
      context: context ? String(context) : null,
      llmSupport: llmSupport ?? '—',
      matched: index === 0,
    }
  })
}

function buildDefaultOutputs(scenario: Scenario, commandInput: string): OutputsMap {
  const stages = scenario.trace.inference.stages
  const stageSummary = (index: number) =>
    stages[index]?.artifacts
      .map((artifact) => artifact.value)
      .join('\n')
      .slice(0, 200) ?? '—'

  return {
    ingress: formatJSON({
      sessionId: scenario.trace.sessionId,
      query: commandInput,
      meta: scenario.trace.request.payload.meta ?? {},
    }),
    'command-service': `session: ${scenario.trace.sessionId}\nmeta keys: ${
      Object.keys(scenario.trace.request.payload.meta ?? {}).join(', ') || '—'
    }`,
    'rule-engine': formatRuleOutput(stages[0]?.artifacts?.[0]?.value, stageSummary(0)),
    'llm-synthesis': stageSummary(1),
    harmonizer: stageSummary(2),
    'conversation-manager': formatConversation(scenario.trace.conversation),
    'response-composer': scenario.trace.conversation.at(-1)?.content ?? '—',
  }
}

function buildOutputsFromResponse(
  payload: Record<string, unknown>,
  analysis: FunctionAnalysisSnapshot,
  assistantMsg: string,
  llmOutput: string,
  scenario: Scenario,
  rulePanels?: RulePanelInfo[],
): OutputsMap {
  const stage0 = scenario.trace.inference.stages[0]
  return {
    ingress: formatJSON(payload),
    'command-service': `session: ${payload.sessionId ?? '—'}\nmeta keys: ${
      Object.keys((payload.meta as Record<string, unknown>) ?? {}).join(', ') || '—'
    }`,
    'rule-engine':
      rulePanels && rulePanels.length
        ? rulePanels
            .map((panel, index) => `${panel.matched ? '✅' : `候选${index + 1}`}: ${panel.title}`)
            .join('\n')
        : formatRuleOutput(
            stage0?.artifacts[0]?.value,
            stage0?.artifacts.map((artifact) => artifact.value).join('\n') ??
              `候选 result: ${analysis.result}`,
          ),
    'llm-synthesis': llmOutput || '—',
    harmonizer: `result: ${analysis.result}\ntarget: ${analysis.target || '—'}\nconfidence: ${(
      analysis.confidence ?? 0
    ).toFixed(2)}`,
    'conversation-manager': formatConversation([
      { role: 'user', content: String(payload.query ?? '') },
      { role: 'assistant', content: assistantMsg },
    ]),
    'response-composer': assistantMsg,
  }
}

function summarizeStage(scenario: Scenario, index: number) {
  const stage = scenario.trace.inference.stages[index]
  if (!stage) return ''
  return stage.artifacts.map((artifact) => artifact.value).join('\n')
}

function formatConversation(turns: ConversationTurn[]) {
  return turns
    .map((turn) => `${turn.role === 'user' ? '用户' : '助手'}：${turn.content}`)
    .join('\n')
}

function clamp(value: number, min: number, max: number) {
  return Math.min(Math.max(value, min), max)
}

function easeOutCubic(t: number) {
  return 1 - Math.pow(1 - t, 3)
}

function formatJSON(value: unknown) {
  if (typeof value === 'string') {
    const parsed = tryParseJSON(value)
    if (parsed !== null) {
      return JSON.stringify(parsed, null, 2)
    }
    return value
  }
  try {
    return JSON.stringify(value, null, 2)
  } catch {
    return String(value)
  }
}

function formatMs(ms: number) {
  if (!Number.isFinite(ms)) return '—'
  if (ms >= 1000) return `${(ms / 1000).toFixed(2)} s`
  return `${Math.round(ms)} ms`
}

function truncate(text: string, max: number) {
  if (text.length <= max) return text
  return `${text.slice(0, max)}…`
}

function tryParseJSON(raw: unknown) {
  if (typeof raw !== 'string') return null
  try {
    return JSON.parse(raw)
  } catch {
    return null
  }
}

function parseLLMOutputFallback(analysis: FunctionAnalysisSnapshot) {
  return formatJSON({
    result: analysis.result,
    target: analysis.target,
    needClarify: analysis.needClarify,
  })
}

function Card({ title, content }: { title: string; content: string }) {
  return (
    <div className="rounded-[24px] border border-[#dbe1f1] bg-white p-4 text-xs text-[#1f2a44] shadow-[0_10px_30px_rgba(169,181,214,0.2)]">
      <p className="text-sm font-semibold text-[#2f3b59]">{title}</p>
      <p className="mt-2 leading-6 text-[#43506d]">{content}</p>
    </div>
  )
}

function Tag({ children }: { children: string }) {
  return (
    <span className="rounded-full border border-[#cbd5f5] bg-[#eef2ff] px-3 py-1 text-[11px] text-[#4c63b6]">
      {children}
    </span>
  )
}

function InfoTile({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-[24px] border border-[#dbe1f1] bg-white p-4 text-xs text-[#1f2a44] shadow-inner">
      <p className="text-[10px] uppercase tracking-[0.4em] text-[#6d7c9b]">{label}</p>
      <p className="mt-2 text-sm font-semibold text-[#2f3b59]">{value}</p>
    </div>
  )
}
