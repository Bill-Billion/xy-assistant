export type NodeStatus = 'pending' | 'running' | 'success' | 'degraded' | 'failed'

export interface TraceNode {
  id: string
  label: string
  status: NodeStatus
  latencyMs?: number
  description: string
  outputSchema?: string
}

export interface TraceEdge {
  source: string
  target: string
}

export interface InferenceStage {
  id: string
  title: string
  summary: string
  artifacts: Array<{
    label: string
    value: string
    kind: 'json' | 'text' | 'badge'
  }>
  guardrails?: string[]
  confidenceDelta?: number
}

export interface TimelineEvent {
  id: string
  label: string
  at: string
  durationMs?: number
  annotation?: string
}

export interface ConversationTurn {
  role: 'user' | 'assistant'
  content: string
}

export interface FunctionAnalysisSnapshot {
  result: string
  target?: string
  event?: string
  status?: string
  confidence: number
  needClarify: boolean
  clarifyMessage?: string
  reasoning?: string
  advice?: string
  safetyNotice?: string
}

export interface TraceSnapshot {
  sessionId: string
  request: {
    endpoint: string
    payload: Record<string, unknown>
  }
  pipeline: {
    nodes: TraceNode[]
    edges: TraceEdge[]
  }
  inference: {
    stages: InferenceStage[]
  }
  timeline: TimelineEvent[]
  conversation: ConversationTurn[]
  functionAnalysis: FunctionAnalysisSnapshot
}
