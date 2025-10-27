# XY Assistant 学术化改进记录

本文档用于记录近期在 XY Assistant 项目中的结构调整、流程资产以及后续科研级改进路径，便于在学术研究或实验阶段快速复现与迭代。

## 1. 已完成的结构化改动

- **提示词流程资产**：在 `flowchart/` 目录下新增多场景流程图（`.md` 与 `.drawio`），覆盖单轮命中、多轮澄清、未知兜底三种主流程，便于后续推导状态转移模型与实验设计。
- **可视化拓展**：为前端管理页面规划信息架构，虽然尚未实现代码，但已整理为面向 Prompt 管理的组件拆分与交互定义。
- **研究资料目录**：创建 `academic/` 文件夹，并克隆 `app/` 核心服务模块至 `academic/app/`，确保实验环境可以独立检索和修改关键代码。

## 2. 实验路线图（研究者视角）

1. **贝叶斯 Prompt 校准与多臂赌博机策略**（本节详述）。
2. 能量函数/图模型融合多源信号，探索近似推断算法。
3. 信息论驱动的主动澄清（基于熵和互信息）实验。
4. 语义流形/最近邻索引减少 LLM 调用频次。

## 3. 贝叶斯 Prompt 校准与多臂赌博机策略

### 3.1 问题建模

- 将一次指令识别视为 **随机变量 $Y$**（意图识别正确与否），其成功率受 Prompt 配置、规则提示等因素影响。
- 规则输出提供“硬先验” $p_0$，LLM 输出提供似然 $p_\text{LLM}$；通过 **贝叶斯更新** 得到后验分布，从而判断是否需要澄清或升级模型。
- 在决策层引入 **多臂赌博机**：三类“臂”分别为纯规则、轻量模型（可选）及豆包大模型，收益函数为识别准确率，成本函数为延迟；使用 UCB 或 Thompson Sampling 平衡探索与利用。

### 3.2 数据准备

1. 收集历史 `logs/` 和 `tests/` 中的真实指令、模型输出及人工标注（若有），构建数据集 $D = \{(x_i, y_i, r_i)\}$。
   - $x_i$：用户指令、上下文。
   - $y_i$：真实意图或类别。
   - $r_i$：规则预测、模型预测、澄清记录等元信息。
2. 对每个意图统计规则命中率，得到 **Beta 先验参数** $(\alpha_0, \beta_0)$：
   - 若无历史数据，可设对称先验 $(1, 1)$。
   - 对于规则命中较高的意图，增大 $\alpha_0$ 以体现信心。
3. 预处理 LLM 输出的置信度或 `function_analysis.confidence`，做离线校准（例如温度缩放）后再参与更新。

### 3.3 在线贝叶斯更新

对于每个意图 $k$，维持 Beta 分布参数 $(\alpha_k, \beta_k)$：

1. **规则先验注入**：如果规则判定意图为 $k$ 且自信，则在进入 LLM 前增加 $(\alpha_k, \beta_k) \leftarrow (\alpha_k + w_r, \beta_k)$，其中 $w_r$ 是规则可信度权重。
2. **LLM 输出处理**：解析 `function_analysis` 后，判断是否正确（可通过真实标签或在线模拟标签）：
   - 成功：$\alpha_k \leftarrow \alpha_k + w_\text{LLM}$。
   - 失败：$\beta_k \leftarrow \beta_k + w_\text{LLM}$。
3. **后验置信度**：计算期望 $\hat{p}_k = \frac{\alpha_k}{\alpha_k + \beta_k}$ 和方差，作为当前轮输出的置信度参考；若 $\hat{p}_k$ 高于阈值则直接确认，否则触发澄清或更强模型。
4. **实现建议**：
   - 在 `academic/app/services/intent_classifier.py` 中新增 `BayesianConfidenceTracker` 类，负责维护参数表并提供 `update(intent_code, result, success: bool)` 接口。
   - 使用 `cachetools` 或 `functools.lru_cache` 存储参数，持久化可写入 `data/bayesian_state.json`。

### 3.4 多臂赌博机策略

1. **定义动作臂**：
   - `arm_rule`：仅运行 `run_rules`，适用于高置信规则。
   - `arm_llm`：直接调用豆包 LLM。
   - （可选）`arm_small_llm`：调用轻量本地模型或缓存结果。
2. **收益设计**：
   - 准确度收益：识别正确得 +1，错误得 0。
   - 延迟成本：可将响应时间 $t$ 转换为负收益 $-\lambda t$，其中 $\lambda$ 为调节系数。
   - 综合奖励：$R = \text{accuracy} - \lambda \cdot t$。
3. **策略选择**：
   - **UCB**：对每个臂维护平均奖励 $\bar{R}_a$ 与选择次数 $N_a$，选择 $a = \arg\max(\bar{R}_a + c \sqrt{\frac{\ln T}{N_a}})$。
   - **Thompson Sampling**：为每个臂维护 Beta 分布，在线采样决定动作，容错性更强。
4. **集成点**：
   - 在 `CommandService.handle_command` 中，调用前先通过 `ArmSelector` 决定执行流程；执行后根据结果更新奖励。
   - 为避免引入副作用，先在 Shadow 模式下运行（记录但不影响实际流程），验证数周后再切换到 Active 模式。

### 3.5 验证与评估

1. **离线回放**：对历史请求进行回放，比较启用贝叶斯+赌博机前后的准确率、澄清率、平均延迟。
2. **在线监控**：新增 Prometheus 指标或日志字段：
   - `intent_bayes_confidence`：输出后验置信度。
   - `arm_selection`：记录本轮选择的臂。
   - `clarify_triggered`：标记是否触发澄清。
3. **统计检验**：使用配对 t 检验或 Wilcoxon 符号检验验证改进的显著性；必要时进行功效分析以确定所需样本量。

## 4. 目录说明

- `academic/app/`：项目核心服务模块的完整拷贝，便于研究时修改，不影响主干代码。
- `academic/research_notes.md`：当前文档，用于持续记录实验设计与结论，建议每次实验后更新。

后续可在 `academic` 目录下新增 Jupyter 笔记本、实验脚本等，以支撑深入的科研探索。

