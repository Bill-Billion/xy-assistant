# XY Assistant Execution Visualizer

独立于 FastAPI 主服务的前端子项目，用于对“用户输入 → 混合式意图推理 → 结构化响应”全链路进行可视化回放。页面现以「PPT 幻灯片」形式呈现，便于专家评审按“总-分”节奏快速理解。核心维度：

- **Request Envelope** — 展示 `CommandRequest` 入参的 schema 治理与 session 租期。
- **Hybrid Reasoning Matrix** — 将规则引擎、豆包 LLM、后置归一化的多阶段 artefact、guardrail、置信度演进可视化。
- **Pipeline Topology** — 梳理 API → Service → Classifier → Client → Conversation 的执行编排，强调 SRP/OCP。
- **Latency Timeline** — 恢复关键阶段的时序指标与重试策略，辅助性能调优。
- **Conversation + FunctionAnalysis** — 回放 TTLCache 会话态与结构化裁决签名，验证业务落地结果。

## 技术栈

- Vite + React 19 + TypeScript，保持轻量快速迭代（KISS）。
- Tailwind CSS 3.x 处理信息密度较高的可视化布局。
- 组件层按职责拆分（SRP），后续可插入 D3/Visx 以增强图形效果而无需重构（OCP）。

## 本地启动

```bash
cd visualizer
npm install
npm run dev
```

访问 `http://localhost:5173/` 查看演示。默认将请求投递到 `http://0.0.0.0:8000`，可通过 `.env` 设置 `VITE_API_BASE` 覆盖。

### 演示提示

- 页面按幻灯片纵向排列，单页比例为 16:9，可通过浏览器全屏模式实现“逐页汇报”。  
- 第一页以图标/动画呈现核心亮点，并列出全部意图清单；第二页提供交互式链式演示。  
- 在第二页输入指令后点击“开始链路演示”，可逐毫秒回放 FastAPI → CommandService → IntentClassifier → DoubaoClient → Conversation → Response 的真实调用顺序。  
- 在「Scene Picker」画廊中即时切换案例，也可对接实时接口替换 `scenarios` 数据。

## 目录速览

```
visualizer/
├─ src/
│  ├─ components/         # SRP 拆分的可视化组件
│  │  ├─ InteractiveChain.tsx  # 链式调用交互演示
│  │  └─ ...               # 其它可视化组件
│  ├─ data/scenarios.ts   # 多场景静态样例
│  ├─ data/intentAtlas.ts # 意图清单数据
│  ├─ types/trace.ts      # 前后端共享的数据契约
│  └─ App.tsx             # 布局编排 & 动画
└─ tailwind.config.js    # 主题扩展，强调品牌色与暗色 UI
```

## 下一步演进建议

1. 打通与 FastAPI 的调试接口，提供实时 trace 数据；可通过 SSE 或 WebSocket 实现渐进式更新。
2. 引入 `react-flow` 或 `@visx/xychart` 渲染拓扑与时序图，进一步强化复杂度展示。
3. 增加过滤器与 session 选择器，支持多会话比对与回放。
