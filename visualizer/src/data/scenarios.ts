import type { LucideIcon } from 'lucide-react'
import {
  AlarmClock,
  BarChart3,
  Bot,
  HeartPulse,
  MonitorPlay,
  PhoneCall,
  Pill,
  Sparkles,
  Video,
} from 'lucide-react'
import type { TraceSnapshot } from '../types/trace'

type Highlight = {
  icon: LucideIcon
  label: string
}

export type Scenario = {
  id: string
  title: string
  caption: string
  accent: string
  tone: string
  highlights: Highlight[]
  trace: TraceSnapshot
}

const basePipelineNodes = [
  {
    id: 'ingress',
    label: 'API Gateway',
    description: 'FastAPI ingress · Pydantic Hydrator',
    outputSchema: 'CommandRequest',
  },
  {
    id: 'command-service',
    label: 'CommandService',
    description: 'Session Context Orchestrator',
    outputSchema: 'FunctionAnalysis',
  },
  {
    id: 'intent-classifier',
    label: 'IntentClassifier',
    description: 'Rule Engine × LLM Arbiter',
    outputSchema: 'ClassificationResult',
  },
  {
    id: 'doubao-client',
    label: 'DoubaoClient',
    description: 'Async LLM ChatCompletions',
    outputSchema: 'LLM JSON Payload',
  },
  {
    id: 'conversation-manager',
    label: 'ConversationManager',
    description: 'TTLCache Session State',
    outputSchema: 'ConversationState',
  },
  {
    id: 'response-composer',
    label: 'ResponseComposer',
    description: 'Template & Advisory Synth',
    outputSchema: 'CommandResponse',
  },
] as const

const baseEdges = [
  { source: 'ingress', target: 'command-service' },
  { source: 'command-service', target: 'intent-classifier' },
  { source: 'intent-classifier', target: 'doubao-client' },
  { source: 'doubao-client', target: 'intent-classifier' },
  { source: 'intent-classifier', target: 'conversation-manager' },
  { source: 'command-service', target: 'conversation-manager' },
  { source: 'command-service', target: 'response-composer' },
]

function composePipeline(latencies: Record<string, number>) {
  return {
    nodes: basePipelineNodes.map((node) => ({
      ...node,
      status: 'success' as const,
      latencyMs: latencies[node.id] ?? 0,
    })),
    edges: baseEdges,
  }
}

const baseTimeline = [
  {
    id: 't0',
    label: 'Ingress Validation',
    at: '00:00',
    annotation: 'Schema alias + meta parsing',
  },
  {
    id: 't1',
    label: 'Rule Scan',
    at: '00:20',
    annotation: 'Heuristics warm start',
  },
  {
    id: 't2',
    label: 'LLM Round Trip',
    at: '00:48',
    annotation: 'HTTPX async call · retry budget',
  },
  {
    id: 't3',
    label: 'Response Ship',
    at: '01:40',
    annotation: 'Template + advisory merge',
  },
]

const SCENARIOS: Scenario[] = [
  {
    id: 'alarm',
    title: '闹钟编排 · 智慧提醒',
    caption: '解析 明早 08:00 提醒 → 结构化周期策略',
    accent: '#1f7fed',
    tone: 'from-brand-500/15 to-brand-500/5',
    highlights: [
      { icon: AlarmClock, label: '时间实体解析' },
      { icon: Bot, label: 'LLM JSON Guardrail' },
      { icon: BarChart3, label: 'Confidence 92%' },
    ],
    trace: {
      sessionId: 'trace-alarm-8am-001',
      request: {
        endpoint: 'POST /api/command',
        payload: {
          sessionId: 'trace-alarm-8am-001',
          query: '请帮我定一个明早8点的闹钟',
          meta: { device: 'smart-speaker' },
        },
      },
      pipeline: composePipeline({
        ingress: 18,
        'command-service': 42,
        'intent-classifier': 118,
        'doubao-client': 820,
        'conversation-manager': 10,
        'response-composer': 6,
      }),
      inference: {
        stages: [
          {
            id: 'rule-engine',
            title: 'Rule Engine',
            summary: 'time expression → ISO8601 target',
            artifacts: [
              {
                label: 'IntentCandidate',
                value: '{ intent: "ALARM_CREATE", target: "2024-09-21T08:00:00+08:00" }',
                kind: 'json',
              },
            ],
            guardrails: ['relative delta fallback'],
            confidenceDelta: 0.72,
          },
          {
            id: 'llm',
            title: 'Doubao LLM',
            summary: 'multi-turn context + reference hints',
            artifacts: [
              {
                label: 'Reply JSON',
                value: '{ result: "新增闹钟", target: "2024-09-21T08:00:00+08:00", confidence: 0.84 }',
                kind: 'json',
              },
            ],
            guardrails: ['response_format::json_object'],
            confidenceDelta: 0.84,
          },
          {
            id: 'post',
            title: 'Harmonizer',
            summary: 'merge rule × LLM → finalize target',
            artifacts: [
              {
                label: 'FunctionAnalysis',
                value: '{ result: "新增闹钟", target: "2024-09-21T08:00:00+08:00", need_clarify: false }',
                kind: 'json',
              },
            ],
            guardrails: ['allowed_results enforcement'],
            confidenceDelta: 0.92,
          },
        ],
      },
      timeline: baseTimeline.map((item, idx) => ({
        ...item,
        durationMs: [18, 26, 820, 14][idx] ?? 0,
      })),
      conversation: [
        { role: 'user', content: '请帮我定一个明早8点的闹钟' },
        { role: 'assistant', content: '已为您设置明天上午 08:00 的闹钟提醒。' },
      ],
      functionAnalysis: {
        result: '新增闹钟',
        target: '2024-09-21T08:00:00+08:00',
        event: undefined,
        status: undefined,
        confidence: 0.92,
        needClarify: false,
        reasoning: 'rule_result 与 LLM 输出一致，取最高置信度。',
      },
    },
  },
  {
    id: 'health',
    title: '血压监测 · 健康档案',
    caption: '识别人名 → 自动匹配监测对象',
    accent: '#0f766e',
    tone: 'from-emerald-500/20 to-emerald-500/5',
    highlights: [
      { icon: HeartPulse, label: 'Health Intent' },
      { icon: Pill, label: 'Safety Notice' },
      { icon: BarChart3, label: 'Confidence 88%' },
    ],
    trace: {
      sessionId: 'trace-health-bp-002',
      request: {
        endpoint: 'POST /api/command',
        payload: {
          sessionId: 'trace-health-bp-002',
          query: '帮我给爸爸开血压监测',
          user: '爸爸,妈妈,我',
        },
      },
      pipeline: composePipeline({
        ingress: 20,
        'command-service': 55,
        'intent-classifier': 135,
        'doubao-client': 910,
        'conversation-manager': 15,
        'response-composer': 8,
      }),
      inference: {
        stages: [
          {
            id: 'rule-engine',
            title: 'Rule Engine',
            summary: 'keyword→ HEALTH_MONITOR_BLOOD_PRESSURE',
            artifacts: [
              {
                label: 'IntentCandidate',
                value: '{ result: "血压监测", target: null }',
                kind: 'json',
              },
            ],
            guardrails: ['health lexical map'],
            confidenceDelta: 0.7,
          },
          {
            id: 'llm',
            title: 'Doubao LLM',
            summary: 'resolve user target + advise check',
            artifacts: [
              {
                label: 'Reply JSON',
                value: '{ target: "爸爸", confidence: 0.82, safety_notice: "...参考" }',
                kind: 'json',
              },
            ],
            guardrails: ['candidate list JSON prompt'],
            confidenceDelta: 0.82,
          },
          {
            id: 'post',
            title: 'Harmonizer',
            summary: 'fuzzy match + confidence uplift',
            artifacts: [
              {
                label: 'FunctionAnalysis',
                value: '{ result: "血压监测", target: "爸爸", need_clarify: false }',
                kind: 'json',
              },
            ],
            guardrails: ['safety notice fallback'],
            confidenceDelta: 0.88,
          },
        ],
      },
      timeline: baseTimeline.map((item, idx) => ({
        ...item,
        durationMs: [20, 34, 910, 19][idx] ?? 0,
      })),
      conversation: [
        { role: 'user', content: '帮我给爸爸开血压监测' },
        { role: 'assistant', content: '已为爸爸开启血压监测，并提醒定期测量。' },
      ],
      functionAnalysis: {
        result: '血压监测',
        target: '爸爸',
        event: undefined,
        status: undefined,
        confidence: 0.88,
        needClarify: false,
        safetyNotice: '监测建议仅供参考，异常请及时就医。',
      },
    },
  },
  {
    id: 'doctor',
    title: '远程问诊 · 家庭医生',
    caption: '自然语言联络需求 → 视频通话入口',
    accent: '#f97316',
    tone: 'from-amber-500/20 to-amber-500/5',
    highlights: [
      { icon: Video, label: 'Video Call' },
      { icon: PhoneCall, label: 'Contact Ready' },
      { icon: BarChart3, label: 'Confidence 93%' },
    ],
    trace: {
      sessionId: 'trace-doctor-003',
      request: {
        endpoint: 'POST /api/command',
        payload: {
          sessionId: 'trace-doctor-003',
          query: '我要和家庭医生视频聊一聊',
          meta: { device: 'smart-display' },
        },
      },
      pipeline: composePipeline({
        ingress: 16,
        'command-service': 40,
        'intent-classifier': 110,
        'doubao-client': 760,
        'conversation-manager': 12,
        'response-composer': 6,
      }),
      inference: {
        stages: [
          {
            id: 'rule-engine',
            title: 'Rule Engine',
            summary: 'doctor keywords → FAMILY_DOCTOR_CALL_VIDEO',
            artifacts: [
              { label: 'IntentCandidate', value: '{ result: "家庭医生视频通话" }', kind: 'json' },
            ],
            guardrails: ['doctor lexical set'],
            confidenceDelta: 0.76,
          },
          {
            id: 'llm',
            title: 'Doubao LLM',
            summary: 'multi-turn check + clarify gating',
            artifacts: [
              {
                label: 'Reply JSON',
                value: '{ result: "家庭医生视频通话", confidence: 0.9 }',
                kind: 'json',
              },
            ],
            guardrails: ['clarify message fallback'],
            confidenceDelta: 0.9,
          },
          {
            id: 'post',
            title: 'Harmonizer',
            summary: 'auto bypass clarify (confidence > threshold)',
            artifacts: [
              {
                label: 'FunctionAnalysis',
                value: '{ requiresSelection: false }',
                kind: 'json',
              },
            ],
            guardrails: ['confidence floor 0.7'],
            confidenceDelta: 0.93,
          },
        ],
      },
      timeline: baseTimeline.map((item, idx) => ({
        ...item,
        durationMs: [16, 28, 760, 11][idx] ?? 0,
      })),
      conversation: [
        { role: 'user', content: '我要和家庭医生视频聊一聊' },
        { role: 'assistant', content: '正在为您连接家庭医生的视频通话。' },
      ],
      functionAnalysis: {
        result: '家庭医生视频通话',
        confidence: 0.93,
        needClarify: false,
      },
    },
  },
  {
    id: 'entertainment',
    title: '娱乐点播 · 戏曲播放',
    caption: '从自然请求直达内容编排与通话抑制',
    accent: '#a855f7',
    tone: 'from-violet-500/20 to-violet-500/5',
    highlights: [
      { icon: MonitorPlay, label: 'Opera Stream' },
      { icon: Sparkles, label: 'Personalization' },
      { icon: BarChart3, label: 'Confidence 86%' },
    ],
    trace: {
      sessionId: 'trace-ent-opera-004',
      request: {
        endpoint: 'POST /api/command',
        payload: {
          sessionId: 'trace-ent-opera-004',
          query: '放一段评剧给我听',
          meta: { mood: 'relax' },
        },
      },
      pipeline: composePipeline({
        ingress: 22,
        'command-service': 47,
        'intent-classifier': 140,
        'doubao-client': 940,
        'conversation-manager': 14,
        'response-composer': 9,
      }),
      inference: {
        stages: [
          {
            id: 'rule-engine',
            title: 'Rule Engine',
            summary: 'opera keywords → ENTERTAINMENT_OPERA_SPECIFIC',
            artifacts: [
              {
                label: 'IntentCandidate',
                value: '{ result: "小雅曲艺", event: "评剧" }',
                kind: 'json',
              },
            ],
            guardrails: ['entertainment lexicon'],
            confidenceDelta: 0.68,
          },
          {
            id: 'llm',
            title: 'Doubao LLM',
            summary: 'content tag + device state check',
            artifacts: [
              {
                label: 'Reply JSON',
                value: '{ result: "小雅曲艺", status: "single_play", advice: "欢迎跟唱" }',
                kind: 'json',
              },
            ],
            guardrails: ['safe content policy'],
            confidenceDelta: 0.82,
          },
          {
            id: 'post',
            title: 'Harmonizer',
            summary: 'inject personalization hints',
            artifacts: [
              {
                label: 'FunctionAnalysis',
                value: '{ result: "小雅曲艺", status: "single_play" }',
                kind: 'json',
              },
            ],
            guardrails: ['allowed_results list'],
            confidenceDelta: 0.86,
          },
        ],
      },
      timeline: baseTimeline.map((item, idx) => ({
        ...item,
        durationMs: [22, 39, 940, 16][idx] ?? 0,
      })),
      conversation: [
        { role: 'user', content: '放一段评剧给我听' },
        { role: 'assistant', content: '已为您播放评剧精选曲目。' },
      ],
      functionAnalysis: {
        result: '小雅曲艺',
        event: '评剧',
        status: 'single_play',
        confidence: 0.86,
        needClarify: false,
        advice: '推荐收藏喜爱的剧目，方便下次快速播放。',
      },
    },
  },
  {
    id: 'dynamic',
    title: '指令推演 · 自由输入',
    caption: '实时指令 → 动态规则匹配与链路回放',
    accent: '#4c63b6',
    tone: 'from-brand-500/15 to-brand-500/5',
    highlights: [
      { icon: Sparkles, label: '实时推理' },
      { icon: Bot, label: 'LLM 辅助' },
      { icon: BarChart3, label: 'Rule Coverage' },
    ],
    trace: {
      sessionId: 'trace-dynamic-004',
      request: {
        endpoint: 'POST /api/command',
        payload: {
          sessionId: 'trace-dynamic-004',
          query: '输入任意指令，例如：帮我为团队准备明早的 standup 提醒',
          meta: { channel: 'web' },
        },
      },
      pipeline: composePipeline({
        ingress: 12,
        'command-service': 35,
        'intent-classifier': 150,
        'doubao-client': 940,
        'conversation-manager': 18,
        'response-composer': 9,
      }),
      inference: {
        stages: [
          {
            id: 'rule-engine',
            title: 'Rule Engine',
            summary: '分析触发词，生成多条候选规则并评分。',
            artifacts: [
              {
                label: 'ScheduleRule',
                value: '{ id: "RULE_SCHEDULE_CREATE", score: 0.82, reason: "含时间短语" }',
                kind: 'json',
              },
              {
                label: 'ReminderRule',
                value: '{ id: "RULE_REMINDER_UPDATE", score: 0.54, reason: "检测到提醒词" }',
                kind: 'json',
              },
              {
                label: 'FallbackRule',
                value: '{ id: "RULE_OPEN_CHAT", score: 0.33, reason: "泛化兜底" }',
                kind: 'json',
              },
            ],
            guardrails: ['regex calendar detection', 'pydantic payload validation'],
            confidenceDelta: 0.68,
          },
          {
            id: 'llm-synthesis',
            title: 'Doubao LLM',
            summary: '携带候选规则上下文，要求输出结构化裁决与解释。',
            artifacts: [
              {
                label: 'LLM Reply',
                value: '{ result: "SCHEDULE_CREATE", target: "2024-09-21T09:00:00", confidence: 0.88, reasoning: "匹配到 standup & 时间" }',
                kind: 'json',
              },
            ],
            guardrails: ['response_format::json_object', 'confidence lower bound 0.6'],
            confidenceDelta: 0.88,
          },
          {
            id: 'harmonizer',
            title: 'Harmonizer',
            summary: '合并规则评分与 LLM 结果，生成最终 FunctionAnalysis。',
            artifacts: [
              {
                label: 'FunctionAnalysis',
                value: '{ result: "SCHEDULE_CREATE", target: "团队 standup", need_clarify: false, confidence: 0.9 }',
                kind: 'json',
              },
            ],
            guardrails: ['allowed_results enforcement', 'safety advisory'],
            confidenceDelta: 0.9,
          },
        ],
      },
      timeline: baseTimeline.map((item, idx) => ({
        ...item,
        durationMs: [12, 42, 940, 18][idx] ?? 0,
      })),
      conversation: [
        { role: 'user', content: '帮我为团队准备明早的 standup 提醒。' },
        { role: 'assistant', content: '已为团队创建明早的 standup 日程，并同步提醒。' },
      ],
      functionAnalysis: {
        result: 'SCHEDULE_CREATE',
        target: '团队 standup',
        event: undefined,
        status: undefined,
        confidence: 0.9,
        needClarify: false,
        reasoning: '规则最高得分与 LLM 裁决一致，置信度 0.9。',
        advice: '已同步团队提醒，可在日历中查看。',
        safetyNotice: '',
      },
    },
  },
]

export const scenarios = SCENARIOS
