# AI Agent 量化交易系统 — 需求文档 v0.2

> 基于海外服务器，构建"分析 → 信号 → 执行 → 复盘"全闭环的 AI 驱动美股量化交易系统

---

## 目录

1. [项目背景与目标](#1-项目背景与目标)
2. [核心架构决策](#2-核心架构决策)
3. [整体架构总览](#3-整体架构总览)
4. [模块一：AI Agent 交易大脑](#4-模块一ai-agent-交易大脑)
5. [模块二：交易执行层](#5-模块二交易执行层)
6. [模块三：Agent + 交易结合方案](#6-模块三agent--交易结合方案)
7. [Docker Compose 部署方案](#7-docker-compose-部署方案)
8. [风险控制与合规](#8-风险控制与合规)
9. [路线图与优先级](#9-路线图与优先级)
10. [附录](#10-附录)

---

## 1. 项目背景与目标

### 1.1 背景

- 拥有海外服务器（可稳定访问美股行情与 Alpaca API）
- 希望利用 AI（LLM + 传统量化模型）实现美股交易的自动化
- 目标从"人工看盘"升级为"AI 分析决策 + 自动执行 + 持续进化"

### 1.2 核心目标

| 维度 | 目标 |
|------|------|
| 自动化 | 无人值守的每日交易循环，从数据到执行全链路自动 |
| 智能化 | 利用 LLM 解读市场情绪、财报、宏观新闻，超越纯技术指标 |
| 可进化 | 系统通过每日复盘自我优化，形成正向飞轮 |
| 可部署 | 一套 Docker Compose 搞定所有依赖，服务器上一条命令启动 |
| 可风控 | 严格的仓位管理、止损、黑名单，确保不会因 bug 或幻觉爆仓 |

---

## 2. 核心架构决策

本章记录了从 v0.1 到 v0.2 的关键架构变更及其动机。

### 2.1 决策 1：信号桥接 — Redis Streams 取代共享文件

| 项目 | v0.1 方案 | v0.2 方案 |
|------|-----------|-----------|
| 方式 | `shared_signals/signals.json` 文件共享 | Redis Streams / List |
| 问题 | 两进程读写竞争 → 读到半截 JSON 崩溃；旧信号残留 | 原子读写，消费者组避免重复消费 |
| 优势 | 简单直观 | 无竞争条件、支持 ACK 机制、时序天然有序 |

旧方案中 Agent 写文件、Freqtrade 读文件的做法在生产环境会直接引发 bug。v0.2 明确使用 Redis 作为通信总线。

### 2.2 决策 2：执行层提供双方案

Freqtrade 在加密货币领域很强，但用在美股日频交易上存在结构性不匹配：

| 维度 | Freqtrade 设计假设 | 美股日频实际需求 | 冲突程度 |
|------|---------------------|------------------|----------|
| 时间粒度 | 分钟级轮询 | 每日 1-2 次信号 | ⚠️ 大部分特性闲置 |
| 数据模型 | 永续合约 | Spot + 结算周期 | ⚠️ |
| 流动性假设 | 随时可市价成交 | 开盘/收盘滑点大 | ⚠️ 回测结果过于乐观 |
| Alpaca 支持 | 社区贡献，非一等公民 | 核心依赖 | 🚩 遇到 bug 修得慢 |
| 运维成本 | 额外一个服务 | 希望尽可能精简 | ⚠️ |

v0.2 保持双方案路线：

- **方案 A（推荐）**：轻量执行器，用 Alpaca SDK 直接下单，去掉 Freqtrade
- **方案 B（备选）**：保留 Freqtrade，但桥接改为 HTTP API 而非文件

第一周期选方案 A。如后续需要高频策略，可再引入 Freqtrade。

### 2.3 决策 3：α/β/γ 权重自动优化的约束

v0.1 提出的"每周滑动窗口自动优化 α/β/γ"存在根本性问题：

- **小窗口过拟合**：3 个参数 × 20 天 = 有足够自由度拟合噪声
- **Sharpe 比的统计陷阱**：周级别 Sharpe 比几乎无统计意义
- **正反馈发散**：连续亏损 → 调参 → 市场风格切换 → 继续亏损

v0.2 改为**市场状态分类法**：

```
不优化 α/β/γ 权重，而是:
  1. LLM 或规则引擎判断当前市场状态（趋势/震荡/高波动/低波动）
  2. 每种状态预置一套策略参数集（人为设定或离线回测确定）
  3. 状态切换时参数的变更幅度受硬约束，且需要至少 N 笔交易验证
```

### 2.4 决策 4：明确 LLM 回测的不可行性

> **这是一个必须直说的事实：LLM 参与的决策无法做严格的历史回测。**

原因：
1. **数据问题**：历史新闻需要购买语料库，且覆盖范围始终有限
2. **前视偏差 (Look-ahead Bias)**：Claude 2024 分析 2020 年新闻 = 模型已经知道结果
3. **模型版本漂移**：Claude 3.5 → 4 → 5，行为变化使"历史回测通过"承诺失效

应对策略：
- 技术指标部分 → 使用 vectorbt/backtrader 正常回测
- LLM 部分 → **实盘小资金验证 + 模拟盘并行对照**
- 每次 LLM 升级后，模拟盘运行至少 2 周再切换

### 2.5 决策 5：自我进化回路加阻尼

v0.1 的"亏损→归因→调参"回路需要硬约束防止发散：

```
每次参数变更需要满足:
  ├─ 每日参数调整上限 → 单变量变化 ≤ 10%
  ├─ 预热期 → 调整后至少执行 5 笔交易才能再次调整
  ├─ 熔断 → 当日回撤 > 5% 时冻结所有参数调整
  └─ 人工门禁 → 涉及止损/杠杆/品种的参数变更需用户 Telegram 确认
```

### 2.6 决策 6：数据管道质量保障

v0.1 缺少数据质量层，v0.2 新增:

- **数据 Schema 校验**：每批次数据经过 Pydantic 模型验证，包含范围约束
- **异常值检测**：开盘价=0、涨跌幅>50%、成交量突变为 0 → 标记/告警/降级
- **数据新鲜度监控**：OHLCV 延迟 > 30min、新闻超过 1h 未更新 → 告警
- **降级策略**：主数据源失败 → 切换备用源 / 使用最后有效数据 / 跳过该信号

---

## 3. 整体架构总览

### 3.1 架构框图 (v0.2)

```
┌──────────────────────────────────────────────────────┐
│                   用户 / 监控端                        │
│    Telegram Bot / Web Dashboard / 日志告警            │
└──────────────────────┬───────────────────────────────┘
                       │
┌──────────────────────▼───────────────────────────────┐
│                 AI Agent 交易大脑                      │
│  ┌──────────┐  ┌──────────┐  ┌───────────────────┐  │
│  │ 数据采集  │→ │ 分析决策  │→ │ 复盘优化           │  │
│  │ ·行情数据 │  │ ·技术分析 │  │ ·交易日志分析       │  │
│  │ ·财报数据 │  │ ·LLM 解读 │  │ ·归因分析           │  │
│  │ ·新闻情绪 │  │ ·信号生成 │  │ ·反馈阻尼检查       │  │
│  └──────────┘  └──────────┘  └───────────────────┘  │
│        │              │              │                │
└────────┼──────────────┼──────────────┼────────────────┘
         │              │ 信号         │ 参数更新
         ▼              ▼              ▼
┌──────────────────────────────────────────────────────┐
│                   基础设施层                           │
│  ┌────────────────────────────────────────────────┐  │
│  │            Redis (信号总线)                     │  │
│  │  · Stream: agent:signals (Agent→Executor)      │  │
│  │  · Stream: executor:results (Executor→Agent)   │  │
│  │  · KV: positions, account_state               │  │
│  └────────────────────────────────────────────────┘  │
│  ┌──────────────┐   ┌──────────────────────────────┐ │
│  │  PostgreSQL  │   │  Volume (日志轮转 / 备份)    │ │
│  │  ·交易记录    │   │  ·日志: 7天滚动             │ │
│  │  ·回测数据    │   │  ·备份: 每日 pg_dump        │ │
│  │  ·调优历史    │   │  ·审计: 所有信号/决策永久   │ │
│  └──────────────┘   └──────────────────────────────┘ │
└──────────────────────────────────────────────────────┘
         │
         ▼
┌──────────────────────────────────────────────────────┐
│              交易执行层 (二选一)                       │
│                                                       │
│  方案 A (推荐) ┌──────────────────────────────┐      │
│               │  轻量执行器 (executor.py)      │      │
│               │  · 监听 Redis 信号流           │      │
│               │  · 风控校验 → Alpaca SDK 下单   │      │
│               │  · 盘后报告写入 PostgreSQL      │      │
│               └──────────────────────────────┘      │
│                                                       │
│  方案 B (备选) ┌──────────────────────────────┐      │
│               │  Freqtrade + FastAPI 桥接     │      │
│               │  · Agent 通过 HTTP 推送信号    │      │
│               │  · Freqtrade 策略轮询 API     │      │
│               └──────────────────────────────┘      │
└──────────────────────┬───────────────────────────────┘
                       │ Alpaca API
                       ▼
                 券商 / 交易所
```

### 3.2 数据流 (v0.2)

```
外部数据源               Agent 容器                Redis                 Executor 容器
  │                        │                       │                       │
  ├─ Alpaca OHLCV ────────▶│                       │                       │
  ├─ News/RSS ────────────▶│                       │                       │
  ├─ SEC EDGAR ───────────▶│                       │                       │
  │                        │                       │                       │
  │                    ┌───┴───┐                   │                       │
  │                    │ 数据   │                   │                       │
  │                    │ 校验   │ ← Schema 验证      │                       │
  │                    │ 清洗   │                   │                       │
  │                    └───┬───┘                   │                       │
  │                        │                       │                       │
  │                    ┌───┴───┐                   │                       │
  │                    │ 分析   │                   │                       │
  │                    │ 决策   │                   │                       │
  │                    └───┬───┘                   │                       │
  │                        │ XADD agent:signals     │                       │
  │                        ├──────────────────────▶│                       │
  │                        │                       │  XREAD BLOCK          │
  │                        │                       │◀──────────────────────│
  │                        │                       │    风控校验            │
  │                        │                       ├──────────────────────▶│ Alpaca API
  │                        │                       │◀──────────────────────│ 成交结果
  │                        │                       │                       │
  │                    ┌───┴───┐                   │                       │
  │                    │ 复盘   │   XREAD results   │                       │
  │                    │ 优化   │◀──────────────────│                       │
  │                    └───┬───┘                   │                       │
  │                        │ 参数更新 (带阻尼)       │                       │
  │                        └── self-update ────────│                       │
  │                        │                       │                       │
  │                    Telegram 通知 ───────────────────────────────────▶ 用户
```

---

## 4. 模块一：AI Agent 交易大脑

### 4.1 核心循环

每个交易日，Agent 按以下流水线执行：

```
时间线 (美国东部时间) — 注意服务器 UTC 时区需转换
┌──────────────────────────────────────────────────────┐
│ 05:00 ET │ 数据采集阶段                               │
│ (09:00 UTC)                                          │
│          │ · 拉取前一日 OHLCV 数据                     │
│          │ · 数据质量检查：Schema 校验 + 异常值检测     │
│          │ · 爬取相关股票新闻 / 宏观事件               │
│          │ · 拉取最新财报数据 (如属财报季)             │
│          │ · 读取当前持仓 & 账户权益 (Redis)           │
├──────────────────────────────────────────────────────┤
│ 05:30 ET │ 分析决策阶段                               │
│          │ · 技术指标计算 (SMA/EMA/RSI/MACD/Bollinger)│
│          │ · LLM 解读新闻情绪 → 生成情绪评分           │
│          │ · 判断当前市场状态 (趋势/震荡/高波动)       │
│          │ · 按状态选择策略参数集                       │
│          │ · 多因子综合评分 → 生成交易信号             │
│          │ · 输出：信号 JSON → Redis Stream           │
├──────────────────────────────────────────────────────┤
│ 06:00 ET │ 执行器消费信号 → 校验 → 下单               │
│          │ · 执行器从 Redis 读取信号                    │
│          │ · 校验风控规则 (仓位/止损/黑名单)           │
│          │ · Alpaca API 执行下单                       │
│          │ · 结果写回 Redis + PostgreSQL               │
├──────────────────────────────────────────────────────┤
│ 09:30 ET │ 盘前确认 / 盘中监控                        │
│          │ · 检查开盘状态，调整挂单                    │
│          │ · 市场异常波动告警                          │
│          │ · if VIX > 30 → 降级仓位                   │
├──────────────────────────────────────────────────────┤
│ 16:00 ET │ 收盘后复盘                                  │
│          │ · 对比昨日预测 vs 实际走势                   │
│          │ · LLM 分析盈亏原因                          │
│          │ · 反馈阻尼检查：今日是否触发熔断            │
│          │ · 更新策略参数 (满足约束条件时)             │
│          │ · 生成日报 (Markdown) → Telegram 推送       │
└──────────────────────────────────────────────────────┘
```

### 4.2 数据采集模块

#### 数据源矩阵

| 数据源 | 内容 | 获取方式 | 频次 | 质量要求 |
|--------|------|----------|------|----------|
| Alpaca API | OHLCV、账户信息 | REST API | 每日 | 延迟 ≤ 30min，缺失 > 2h → 降级 |
| Financial Modeling Prep | 财报、关键指标 | REST API | 财报季 | 格式校验，字段缺失 → 降级 |
| News API / RSS | 相关新闻 | RSS + LLM 摘要 | 每日 | 去重、过滤广告/无关内容 |
| SEC EDGAR | 10-K/10-Q 原始财报 | EDGAR API | 季度 | 文本长度截断警告 |
| 宏观经济日历 | 非农、CPI、FOMC | API / 爬虫 | 按事件 | 时效性优先 |

#### 数据质量标准 (新增)

每条数据进入处理管道前经过以下检查：

```python
class OHLCVRecord(BaseModel):
    symbol: str
    timestamp: datetime
    open: float = Field(gt=0)           # 开盘价必须 > 0
    high: float
    low: float
    close: float
    volume: int = Field(ge=0)
    
    @validator('high')
    def high_ge_low(cls, v, values):
        if 'low' in values and v < values['low']:
            raise ValueError('high < low')
        return v
    
    @validator('close')
    def close_in_range(cls, v, values):
        if 'low' in values and 'high' in values:
            if v < values['low'] or v > values['high']:
                raise ValueError('close outside [low, high]')
        return v
```

数据新鲜度监控：

| 指标 | 阈值 | 动作 |
|------|------|------|
| OHLCV 数据延迟 | > 30 分钟 | 告警，继续用最后有效数据 |
| OHLCV 数据延迟 | > 2 小时 | 跳过今日信号生成 |
| 新闻流静默 | > 1 小时 | 告警，继续用旧新闻 |
| API 错误率 | > 10% 连续 5 次 | 切换备选源 |

### 4.3 分析决策模块

#### 4.3.1 技术分析 (传统量化)

```
入参: OHLCV 数据, 持仓信息
处理:
  ├─ 趋势跟踪: SMA20/50 交叉, MACD 柱, ADX
  ├─ 动量指标: RSI(14), Stochastic, Williams %R
  ├─ 波动率: Bollinger Bands 带宽, ATR
  ├─ 成交量: OBV, Volume Profile
  └─ 综合 → 技术面评分 (-100 ~ +100)
出参: 技术面信号 (方向 + 置信度)
```

#### 4.3.2 LLM 基本面 / 情绪分析

```
入参: 新闻摘要, 财报文本, 宏观事件描述
处理:
  ├─ 新闻情感分析 → 情感得分
  ├─ 财报关键指标提取 → 超预期 / 不及预期
  ├─ 宏观事件解读 → 风险/利好判断
  └─ 综合 → 基本面评分 (-100 ~ +100)
出参: LLM 解读报告 + 基本面信号
```

#### 4.3.3 市场状态分类 (v0.2 新增，替代固定权重)

```
市场状态由以下指标共同判定:
  ├─ ADX (平均趋向指数) → >25 = 趋势, <20 = 震荡
  ├─ VIX 水平 → >30 = 高波动, 15-30 = 正常, <15 = 低波动
  ├─ 宽基指数 20日表现 → 确认趋势方向
  └─ 综合 → 当前状态

预定义状态:
  ├─ 趋势上升 (Trend Up)     → 使用动量策略参数集
  ├─ 趋势下降 (Trend Down)   → 使用防御/做空策略参数集
  ├─ 震荡 (Range-bound)      → 使用均值回归策略参数集
  ├─ 高波动 (High Vol)       → 降低仓位、扩大止损
  └─ 低波动 (Low Vol)        → 正常仓位、收紧止损

每个策略参数集包含:
  ├─ 信号合成权重 (α, β, γ)   ← 离线回测确定，不自动优化
  ├─ 仓位比例
  ├─ 止损倍数 (ATR 倍数)
  └─ 目标持仓数量上限
```

#### 4.3.4 信号合成引擎

```
信号 = α_state * 技术面评分 + β_state * 基本面评分 + γ_state * 情绪评分

其中 α_state / β_state / γ_state 取决于当前市场状态分类

规则:
  - 总分 > +60  → 强烈买入
  - 总分 +20~60 → 温和买入
  - 总分 -20~+20 → 观望
  - 总分 -60~-20 → 温和卖出
  - 总分 < -60  → 强烈卖出 (或做空)
```

### 4.4 复盘优化模块

#### 4.4.1 每日复盘内容

```
昨日预测回顾:
  ├─ 预测方向 vs 实际方向: ✅ / ❌
  ├─ 准确度评分
  ├─ 归因分析 (为什么错了/对了)
  └─ 市场状态判断是否正确？

策略参数更新 (受反馈阻尼约束):
  ├─ 状态切换阈值调整 (ADX/VIX 边界)
  ├─ 单个参数变化 ≤ 10%/日
  ├─ 预热期: 调整后 5 笔交易内不再调整
  ├─ 熔断: 当日回撤 > 5% → 冻结所有调参
  └─ 止损/杠杆变更 → 需 Telegram 确认

行为日志:
  ├─ 记录了哪些决策依据
  ├─ 是否遵守风控规则
  ├─ 是否存在"幻觉"或错误推理
```

#### 4.4.2 自我进化机制 (带阻尼版本)

| 机制 | 说明 | 阻尼措施 |
|------|------|----------|
| 策略参数调优 | 根据市场状态切换参数集 | 每日变化 ≤ 10%，需 5 笔交易预热 |
| 策略淘汰 | 某策略连续 X 日亏损 → 自动暂停 | X ≥ 5 日，且需与同状态旧策略对照 |
| Prompt 优化 | LLM prompt 模板迭代 | 每次变更记录 diff，可回滚 |
| 知识库构建 | 复盘产出存入向量数据库 | 仅做参考，不影响自动决策 |
| 市场状态边界调整 | ADX/VIX 分类阈值微调 | 季度级别，而非每日 |

#### 4.4.3 关于 LLM 部分"回测"的说明 (重要)

> ⚠️ **LLM 参与的决策无法做严格历史回测，这是设计决定的，不是未来某个阶段能解决的。**
>
> 我们接受的方案是：
> - **技术指标** → vectorbt/backtrader 正常回测
> - **LLM 信号** → 模拟盘实跑验证，主盘与对照盘并行运行
> - **模型升级** → 每次 Claude 版本升级后，模拟盘运行 ≥ 2 周再切换主盘
> - **衡量标准** → 不看 Sharpe 比这种短期统计量，看 3 个月以上的累计对比

---

## 5. 模块二：交易执行层

### 5.1 方案选型对比

| 维度 | 方案 A: 轻量执行器 🏆 | 方案 B: Freqtrade 保留 |
|------|----------------------|----------------------|
| 架构 | Agent → Redis → Executor → Alpaca | Agent → HTTP → Freqtrade → Alpaca |
| 代码量 | ~300 行 Python | 需要整个 Freqtrade 容器 |
| 运维复杂度 | 2 个服务 (agent + executor) | 3+ 个服务 (agent + freqtrade + postgres) |
| 调试难度 | 单进程，打断点即可 | Freqtrade 内部机制黑盒 |
| 灵活性 | Alpaca 新特性立即可用 | 等待 Freqtrade 社区适配 |
| 高频支持 | 需自行实现 | 内建 |
| 本项目的适合度 | ✅ 日频交易，轻量正合适 | ❌ 大炮打蚊子 |

**结论：Phase 1 选方案 A。如果后续需要分钟级策略，再引入 Freqtrade 作为补充。**

### 5.2 方案 A：轻量执行器 (推荐)

```
执行器组件:
├── RedisConsumer    监听 agent:signals Stream
├── RiskEngine       风控规则引擎
├── OrderManager     Alpaca SDK 下单
├── PositionTracker  持仓跟踪
└── ResultProducer   执行结果写回 Redis Stream + PostgreSQL

执行流程:
  1. XREAD BLOCK 等待新信号
  2. RiskEngine 校验:
     ├─ 该股票是否在黑名单
     ├─ 当前持仓数 < 上限
     ├─ 单笔风险 ≤ 账户权益 × 1%
     ├─ 今日回撤 < 5%
     └─ 距离上次交易 ≥ 最小间隔
  3. OrderManager 发起 Alpaca API 调用
  4. 结果写回 executor:results (供 Agent 复盘消费)
  5. 交易记录写入 PostgreSQL
```

### 5.3 方案 B：Freqtrade + HTTP 桥接 (备选)

如后续确实需要 Freqtrade，v0.1 的文件桥接已废弃，改为：

```
Agent ─── HTTP POST /signal ───→ FastAPI 服务 ───→ Freqtrade custom strategy
                                        │
                                    Redis (备选缓存)

Freqtrade 策略内轮询本地 API 获取最新信号
```

移除文件桥接，保留 Freqtrade 但不在 Phase 1 引入。

### 5.4 支持的 Alpaca 交易能力

| 交易类型 | 方案 A | 方案 B (Freqtrade) |
|----------|--------|---------------------|
| 美股做多 (Long) | ✅ Alpaca SDK 原生 | ✅ 社区支持 |
| 美股做空 (Short) | ✅ | ✅ (需权限) |
| 限价单 (Limit) | ✅ | ✅ |
| 市价单 (Market) | ✅ | ✅ |
| 止损单 (Stop Loss) | ✅ | ✅ |
| 追踪止损 (Trailing Stop) | ✅ | ✅ |
| 碎股 (Fractional Shares) | ✅ 原生支持 | ❌ 不支持 |
| 盘后交易 (After-hours) | ✅ 原生支持 | ⚠️ 不完整 |

---

## 6. 模块三：Agent + 交易结合方案

### 6.1 深度结合场景

#### 方案 A：LLM 生成信号 → 量化执行 (Phase 1 主力)

```
Claude API  ──→  结构化 JSON 信号  ──→  Redis Stream ──→  Executor 执行
                     ↑
             提供: 财报数据、新闻、技术指标上下文

原则: LLM 做"分析师"，不做"交易员"
```

#### 方案 B：LLM 辅助优化策略参数 (Phase 2+)

```
离线回测结果  ──→  Claude 分析报告  ──→  参数调优建议 (人工确认后应用)
                      ↑
              分析: 哪些参数导致亏损、过拟合检测、市场适应性
```

⚠️ 注意：这里的 LLM 分析仅作建议，不会自动执行参数变更。自动调参有 v0.2 的反馈阻尼约束。

#### 方案 C：多 Agent 辩论系统 (Phase 3)

```
技术分析 Agent ──┐
基本面 Agent ────┤──→ 仲裁 Agent → 最终信号
宏观 Agent ─────┤
情绪 Agent ─────┘

注意: 本方案需要多个 API Key 且延迟较高
      Phase 3 再评估实际收益 vs 成本
```

### 6.2 Claude 在交易中的具体应用点

| 应用场景 | 输入 | 输出 | 价值 | 回测可能性 |
|----------|------|------|------|------------|
| 财报解读 | 10-K/10-Q 文本 | 超预期/不及预期关键指标 | 节省小时级人工阅读 | ❌ 无法回测 |
| 新闻情感分析 | 相关文章 RSS | 情感得分 + 关键句子 | 量化非结构化信息 | ❌ 无法回测 |
| 复盘归因 | 交易记录 + 行情 | 错误模式识别 | 加速策略迭代 | ✅ 可用历史记录测试 |
| 参数解释 | 回测统计表 | 参数意义 + 调优建议 | 降低量化门槛 | ✅ 人可判断建议质量 |
| 风险预警 | 持仓 + 市场事件 | 风险等级 + 建议操作 | 实时风控辅助 | ❌ 无法回测 |

### 6.3 风险边界

> ⚠️ **关键原则**: LLM 输出结构化信号 → Redis 桥接 → 量化层校验 → 执行。LLM 从不直接下单。

| 风险 | 缓解措施 |
|------|----------|
| LLM 幻觉 | 结构化输出 (JSON Schema 约束) + 数值范围限制 + 信号强度阈值过滤 |
| 上下文窗口溢出 | 分块处理 + 只传入相关数据子集 + 超长文本截断告警 |
| API 延迟/失败 | 信号生成在盘前完成；若 LLM API 超时 → 降级为纯技术信号 |
| 模型行为变化 | Claude 升级后模拟盘 ≥ 2 周观察再切换主盘 |
| 极端行情误判 | 叠加波动率熔断检测 + 最大仓位限制 + 黑名单 |

---

## 7. Docker Compose 部署方案

### 7.1 服务拓扑 (v0.2)

```
┌──────────────────────────────────────────────────────┐
│                    Docker Compose                     │
│                                                       │
│  ┌────────────┐   ┌────────────┐   ┌────────────┐   │
│  │  agent-core│   │  executor  │   │  postgres  │   │
│  │ (Python)   │──▶│ (轻量下单)  │──▶│ (数据持久)  │   │
│  │            │   │            │   │            │   │
│  │ 分析决策   │   │ 风控校验   │   │ 交易记录   │   │
│  │ 信号生成   │   │ Alpaca SDK │   │ 回测数据   │   │
│  │ 复盘优化   │   │            │   │ 调优历史   │   │
│  └─────┬──────┘   └──────┬─────┘   └────────────┘   │
│        │                 │                            │
│        └────────┬────────┘                            │
│                 ▼                                     │
│  ┌──────────────────────┐   ┌────────────────────┐   │
│  │     Redis (信号总线)  │   │ telegram-notifier  │   │
│  │  · agent:signals     │   │ (通知/告警)        │   │
│  │  · executor:results  │   └────────────────────┘   │
│  │  · positions (缓存)  │                            │
│  └──────────────────────┘                            │
│                                                       │
└──────────────────────────────────────────────────────┘
```

### 7.2 docker-compose.yml

```yaml
version: '3.8'

x-logging: &default-logging
  driver: "json-file"
  options:
    max-size: "10m"
    max-file: "3"

services:
  # ──────────────────────────────────────────────
  # AI Agent 核心
  # ──────────────────────────────────────────────
  agent-core:
    build: ./agent
    env_file: .env
    depends_on:
      redis:
        condition: service_healthy
      postgres:
        condition: service_healthy
    volumes:
      - ./agent:/app
      - agent_data:/data
      - logs:/var/log/stockagent
    environment:
      - TZ=America/New_York   # ★ 时区统一为美东
    restart: unless-stopped
    logging: *default-logging
    stop_grace_period: 30s    # 允许完成当前分析再退出

  # ──────────────────────────────────────────────
  # 交易执行器
  # ──────────────────────────────────────────────
  executor:
    build: ./executor
    env_file: .env
    depends_on:
      redis:
        condition: service_healthy
      postgres:
        condition: service_healthy
    environment:
      - TZ=America/New_York
    restart: unless-stopped
    logging: *default-logging
    stop_grace_period: 30s    # 等待挂单响应

  # ──────────────────────────────────────────────
  # Redis (信号总线 + 缓存)
  # ──────────────────────────────────────────────
  redis:
    image: redis:7-alpine
    volumes:
      - redis_data:/data
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 3s
      retries: 3
    restart: unless-stopped
    logging: *default-logging

  # ──────────────────────────────────────────────
  # PostgreSQL (持久存储)
  # ──────────────────────────────────────────────
  postgres:
    image: postgres:15
    volumes:
      - pgdata:/var/lib/postgresql/data
      - ./db/backup:/backup          # 备份挂载
    environment:
      POSTGRES_DB: trading
      POSTGRES_USER: trader
      POSTGRES_PASSWORD: ${DB_PASSWORD:?required}
      TZ: America/New_York
    restart: unless-stopped
    logging: *default-logging

  # ──────────────────────────────────────────────
  # 数据库自动备份 (每日)
  # ──────────────────────────────────────────────
  db-backup:
    image: postgres:15
    depends_on:
      postgres:
        condition: service_started
    env_file: .env
    environment:
      TZ: America/New_York
    volumes:
      - ./db/backup:/backup
      - ./db/backup.sh:/backup.sh:ro
    entrypoint: |
      sh -c '
      echo "0 20 * * * /backup.sh" > /etc/crontabs/root &&
      crond -f -l 2
      '
    restart: unless-stopped
    logging: *default-logging

  # ──────────────────────────────────────────────
  # Telegram 通知
  # ──────────────────────────────────────────────
  notifier:
    build: ./notifier
    env_file: .env
    depends_on: [redis]
    environment:
      TZ: America/New_York
    restart: unless-stopped
    logging: *default-logging

volumes:
  agent_data:
  redis_data:
  pgdata:
  logs:
```

### 7.3 时区处理 (v0.2 新增)

这是一个容易被忽略但一跑就出问题的细节：

```
问题: 服务器是 UTC，美股交易是 ET
    夏令时 UTC-4，冬令时 UTC-5
    Cron 里的 "05:00 ET" 在 Docker 里意义不明

方案:
  1. 所有服务容器设置 TZ=America/New_York
  2. Python 代码用 pytz / zoneinfo 显式处理时区
  3. 所有日志时间戳带时区标记 (ISO 8601 with offset)
  4. 不使用系统 Cron，而是用 APScheduler 指定 ET 时区
```

```python
# agent-core 内的时区处理示例
from zoneinfo import ZoneInfo
ET = ZoneInfo("America/New_York")
now_et = datetime.now(ET)

apscheduler 配置:
scheduler.add_job(
    daily_cycle,
    trigger=CronTrigger(hour=5, minute=0, timezone=ET),
    id='daily_cycle'
)
```

### 7.4 环境变量 (.env)

```bash
# ── Alpaca ──
ALPACA_API_KEY=pk_xxxx
ALPACA_SECRET_KEY=xxxx
ALPACA_PAPER=true                        # 先用模拟交易！
ALPACA_BASE_URL=https://paper-api.alpaca.markets

# ── LLM ──
LLM_API_KEY=sk-xxx
LLM_MODEL=claude-sonnet-4-20250514

# ── 数据库 ──
DB_HOST=postgres
DB_PORT=5432
DB_NAME=trading
DB_USER=trader
DB_PASSWORD=<生成一个强密码，不要用默认值>

# ── Redis ──
REDIS_HOST=redis
REDIS_PORT=6379

# ── 风控 (硬约束) ──
MAX_POSITIONS=5                           # 最大同时持仓数
MAX_RISK_PER_TRADE=0.01                   # 每笔风险 ≤ 账户 1%
MAX_DAILY_DRAWDOWN=0.05                   # 日最大回撤 5%
MAX_ACCOUNT_RISK=0.20                     # 总账户最大承担风险
STOP_LOSS_ATR_MULTIPLIER=1.5              # 止损 ATR 倍数
MIN_TRADE_INTERVAL_HOURS=4               # 同一标的交易最小间隔
BLACKLIST=GME,AMC,BB,CLOV                 # 黑名单 (MEME 股等)

# ── 通知 ──
TELEGRAM_BOT_TOKEN=xxx
TELEGRAM_CHAT_ID=xxx
TELEGRAM_ALERT_LEVEL=info                 # info/warning/error

# ── 交易品种 ──
TRADING_PAIRS=SPY,QQQ,AAPL,MSFT,GOOGL,AMZN

# ── 日志 ──
LOG_LEVEL=INFO
LOG_DIR=/var/log/stockagent

# ── 备份 ──
BACKUP_DIR=/backup
BACKUP_RETENTION_DAYS=30
```

### 7.5 目录结构 (v0.2)

```
stockagent/
├── agent/                        # AI Agent 核心
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── main.py                   # 每日循环入口 (APScheduler)
│   ├── collector/
│   │   ├── market_data.py        # 行情数据采集
│   │   ├── news.py               # 新闻采集
│   │   └── financials.py         # 财报数据
│   ├── quality/                  # ★ 新增: 数据质量
│   │   ├── schema.py             # Pydantic 数据模型
│   │   ├── validator.py          # 异常值检测
│   │   └── freshness.py          # 数据新鲜度监控
│   ├── analyzer/
│   │   ├── technical.py          # 技术指标
│   │   ├── market_state.py       # ★ 市场状态分类
│   │   ├── llm_analyzer.py       # LLM 分析
│   │   └── signal_gen.py         # 信号合成
│   ├── review/
│   │   ├── daily_review.py       # 每日复盘
│   │   └── optimizer.py          # 参数微调 (带阻尼)
│   └── utils/
│       ├── logger.py             # 日志 (时区感知 + 轮转)
│       ├── timezone.py           # ★ 时区工具
│       └── notifier_client.py    # 通知客户端
│
├── executor/                     # ★ 新增: 轻量执行器 (方案 A)
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── main.py                   # Redis 监听循环
│   ├── risk_engine.py            # 风控规则引擎
│   ├── order_manager.py          # Alpaca SDK 下单
│   └── position_tracker.py       # 持仓跟踪
│
├── notifier/                     # Telegram 通知服务
│   ├── Dockerfile
│   └── main.py
│
├── db/
│   ├── backup.sh                 # 数据库备份脚本
│   └── migrations/               # SQL 迁移脚本
│
├── docker-compose.yml
├── .env.example
├── .gitignore
├── REQUIREMENTS.md
└── README.md
```

### 7.6 部署指令

```bash
# 1. 克隆项目到海外服务器
git clone https://github.com/xxx/stockagent.git
cd stockagent

# 2. 配置环境变量
cp .env.example .env
# ★ 生成强密码，不要用示例值
python -c "import secrets; print(secrets.token_urlsafe(16))"
vi .env   # 填入 Alpaca Key、LLM Key、数据库密码

# 3. 首次启动
docker compose up -d --build

# 4. 查看日志
docker compose logs -f agent-core
docker compose logs -f executor
docker compose logs -f notifier

# 5. 手动触发一次日循环 (调试用)
docker compose exec agent-core python -m app.main --force-run

# 6. 查看数据库备份
docker compose exec db-backup ls -la /backup

# 7. 恢复备份
docker compose exec postgres pg_restore -U trader -d trading /backup/<file>

# 8. 更新
git pull
docker compose up -d --build

# 9. 安全停止 (等待挂单处理)
docker compose down --timeout 60
```

### 7.7 运维关键项 (v0.2 新增)

#### 日志轮转

```yaml
# docker-compose.yml 已配置 json-file driver 自动轮转
# Agent 内部日志也使用 RotatingFileHandler:
logging:
  handlers:
    - RotatingFileHandler(log_dir/app.log, maxBytes=50MB, backupCount=5)
    - TimedRotatingFileHandler(log_dir/error.log, when='midnight', backupCount=30)
```

#### 数据库备份

```bash
# db/backup.sh — 每日自动执行
#!/bin/bash
BACKUP_FILE="/backup/trading_$(date +%Y%m%d_%H%M%S).dump"
pg_dump -h postgres -U trader -d trading -Fc -f "$BACKUP_FILE"
# 删除超过 30 天的备份
find /backup -name "*.dump" -mtime +30 -delete
```

#### 监控告警

| 检查项 | 方式 | 告警通道 |
|--------|------|----------|
| 容器是否运行 | Docker healthcheck | Telegram |
| 今日信号是否生成 | Agent 心跳 (Redis key TTL) | Telegram |
| 交易是否正常执行 | Executor 心跳 | Telegram |
| 磁盘空间 | Docker 卷监控 | Telegram |
| LLM API 可用性 | Agent 内探活 | Telegram |
| Alpaca API 可用性 | Executor 内探活 | Telegram |

#### Graceful Shutdown

```
流程: docker compose down --timeout 60
  1. 向 agent-core 发送 SIGTERM
  2. Agent 收到信号 → 完成当前分析 → 保存中间状态 → 退出
  3. 向 executor 发送 SIGTERM
  4. Executor 收到信号 → 等待当前挂单响应 (最多 30s) → 退出
  5. 60s 后仍未退出 → SIGKILL
```

#### API Key 安全

```
- .env 文件权限设为 600 (仅所有者可读)
- .gitignore 包含 .env
- 生产环境考虑使用 Docker Secrets 而非环境变量
  docker secret create alpaca_api_key ./alpaca_key.txt
- 定期轮换 API Key (建议每 90 天)
```

---

## 8. 风险控制与合规

### 8.1 资金风控

```
多层风控体系 (v0.2):

Layer 1 ─ Agent 层面
  ├─ 单信号置信度不足 → 不生成交易
  ├─ 市场波动过大 (VIX > 30) → 切换低波动率策略参数
  └─ 账户回撤 > 阈值 → 暂停交易，发送人工告警

Layer 2 ─ Executor/RiskEngine 层面 (信号与执行解耦)
  ├─ 最大持仓数 = MAX_POSITIONS
  ├─ 单笔风险 ≤ 账户 × MAX_RISK_PER_TRADE
  ├─ 同一标的最小间隔 = MIN_TRADE_INTERVAL_HOURS
  ├─ 黑名单过滤 (BLACKLIST)
  └─ 全局止损 (账户回撤 > MAX_ACCOUNT_RISK → 平所有仓)

Layer 3 ─ 账户层面 (Alpaca)
  ├─ 日交易量限制
  ├─ 个股集中度限制
  └─ 最大杠杆控制 (Alpaca 设置)
```

### 8.2 运维风控

| 场景 | 应对 |
|------|------|
| 服务器宕机 | Docker restart: always，挂单保留在 Alpaca |
| API Key 失效 | Executor 检测到 401 → Telegram 告警 + 暂停下单 |
| LLM API 超时 | Agent 降级为纯技术信号 |
| Executor 崩溃 | Docker restart 自动拉起，从 Redis 重新消费上次未 ACK 的信号 |
| Agent 崩溃 | Docker restart，次日循环自动恢复 |
| 网络分区 | 不挂新单，保持现有持仓，Redis 信号保留待重连后消费 |
| 磁盘写满 | 日志轮转 + 备份自动清理 + 磁盘监控告警 |
| 数据库损坏 | 每日 pg_dump 备份，支持按需恢复 |

### 8.3 合规要点

| 事项 | 说明 |
|------|------|
| 模拟盘先行 | 前 1-2 个月全程 Paper Trading (ALPACA_PAPER=true) |
| 过渡到实盘 | 小资金 ($1000) 验证 ≥ 4 周后逐步加 |
| 人工监督 | 每次交易发送 Telegram 通知 + 关键操作可人工拦截 |
| 日志审计 | 所有决策、信号、风控检查、执行记录完整留存 |
| PDT 规则 (美国) | 账户净资产 < $25,000 时 5 个交易日内 ≤ 3 次日内交易 |
| 税务记录 | 所有交易记录导出为标准 CSV，供报税使用 |

> ⚠️ **免责声明**: 本系统为辅助工具，不构成投资建议。所有交易决策最终由用户负责。
> US 美股账户请注意 Pattern Day Trader 规则。加密货币交易可能涉及额外税务申报义务。

---

## 9. 路线图与优先级

### Phase 1：基础闭环 (MVP) — 3-4 周

```
优先级  任务
────────────────────────────────────────────────────
P0      Docker Compose 基础设施搭建 (含时区/日志/备份)
P0      Agent 基础结构 (APScheduler 日循环)
P0      数据采集 (Alpaca OHLCV + 新闻 RSS)
P0      技术指标分析 (SMA/RSI/MACD)
P0      轻量执行器 (Redis 消费 + Alpaca SDK 下单)
P0      Redis 信号总线 (Stream 生产者/消费者)
P0      Paper Trading 验证
P1      数据质量检查 (Schema + 异常值)
P1      Telegram 通知
P1      基础风控规则 (仓位/止损/黑名单)
P1      模拟盘连续运行 2 周无事故
```

**退出标准**:
- 全流程 "数据采集→分析→信号→Redis→执行→记录" 无人干预跑通 ≥ 2 周
- 模拟盘表现文档化（胜率、盈亏、最大回撤）

### Phase 2：LLM 赋能 — 2-3 周

```
P0      Claude API 集成 + JSON Schema 结构化输出
P0      新闻情绪分析 (LLM) → 情绪评分
P1      市场状态分类 (LLM + 规则)
P1      信号合成 (技术 + LLM, 按市场状态选参数集)
P1      每日复盘报告生成 + Telegram 推送
P2      财报解读信号 (10-K/10-Q 解析)
P2      反馈阻尼机制 (参数上限/预热/熔断)
```

### Phase 3：稳定与进化 — 持续

```
P1      参数微调 (带阻尼，人工确认门禁)
P1      策略知识库 (向量数据库)
P2      Web Dashboard (交易记录、绩效图表)
P2      并行模拟盘 (A/B 策略对照)
P3      多 Agent 辩论系统
P3      市场状态分类的自动校准
```

### Phase 4：高级特性 — 按需

```
□ 多时间框架分析 (日线 + 周线 + 小时线)
□ 行业轮动策略
□ 期权对冲
□ 全托管自动化 (月级别无需人工干预)
□ 多账户管理
□ Freqtrade 接入 (如确实需要分钟级策略)
```

---

## 10. 附录

### 10.1 关键变更日志 (v0.1 → v0.2)

| 变更 | 旧 (v0.1) | 新 (v0.2) | 动机 |
|------|-----------|-----------|------|
| 信号桥接 | 共享文件 `signals.json` | Redis Streams | 避免竞争条件 |
| 执行层 | 仅 Freqtrade | 方案 A: 轻量执行器 + 方案 B: Freqtrade 备选 | 避免大炮打蚊子 |
| 权重优化 | α/β/γ 滑动窗口自动优化 | 市场状态分类 + 预置参数集 | 防止过拟合 |
| 回测 | 默认可回测 | 明确区分: 技术部分可回测 / LLM 部分不可回测 | 诚实面对限制 |
| 自我进化 | 无约束的反馈回路 | 带阻尼 (上限/预热/熔断/门禁) | 防止发散 |
| 数据质量 | 无检查 | Schema 校验 + 异常值 + 新鲜度 + 降级策略 | 垃圾进 = 垃圾出 |
| 时区 | 未提及 | 统一 ET + 时区感知代码 | 一跑就出的问题 |
| 日志/备份 | 未提及 | 轮转 + 自动备份 + 保留策略 | 运维基础 |
| Graceful shutdown | 未提及 | stop_grace_period + 信号处理 | 防止丢单 |
| API Key 安全 | 仅 .env | .env 权限 + secrets + 轮换建议 | 安全基础 |

### 10.2 技术选型汇总

| 组件 | v0.2 选型 | 理由 |
|------|-----------|------|
| Agent 框架 | Python + APScheduler | 轻量、时区友好的定时调度 |
| LLM | Claude API | 长上下文、财报分析能力强 |
| 信号总线 | Redis Streams | 原子操作、消费者组、无竞争 |
| 执行层 | 轻量 Alpaca SDK | 日频交易足够，运维简单 |
| 数据库 | PostgreSQL | 结构化数据存储 + 备份成熟 |
| 回测 | vectorbt 或 backtrader | 更灵活、更适合美股 |
| 容器 | Docker Compose | 单机多服务部署最简方案 |
| 监控 | Telegram Bot | 实时通知 + 远程操作 |
| 编程语言 | Python | 量化生态最丰富 |

### 10.3 数据流图 (终版)

```
  ╔════════════════════════════════════════════════════════╗
  ║              生产数据流 (简版)                         ║
  ╚════════════════════════════════════════════════════════╝

  外部数据               Agent                    Redis                   Executor
    │                     │                        │                       │
    │  Alpaca OHLCV ──────▶ 数据校验               │                       │
    │  News RSS ──────────▶ │                       │                       │
    │  SEC EDGAR ──────────▶ │                       │                       │
    │                     ┌──┴──┐                   │                       │
    │                     │ 分析 │                   │                       │
    │                     │ 决策 │                   │                       │
    │                     └──┬──┘                   │                       │
    │                        │ XADD agent:signals    │                       │
    │                        ├──────────────────────▶ XREAD BLOCK           │
    │                        │                       │◀──────────────────────│
    │                        │                       │   风险引擎            │
    │                        │                       ├──────────────────────▶ Alpaca API
    │                        │                       │◀──────────────────────│ 成交回报
    │                        │                       │                       │
    │                        │  XADD executor:results │                      │
    │                        │◀──────────────────────│                       │
    │                     ┌──┴──┐                    │                       │
    │                     │ 复盘 │                    │                       │
    │                     │ 调参 │  (带阻尼)          │                       │
    │                     └─────┘                    │                       │
    │                        │                       │                       │
    │                        ▼                       ▼                       ▼
    │                 ┌────────────┐          ┌──────────────┐
    │                 │ PostgreSQL │          │ 写入交易记录  │
    │                 │ (持久存储)  │          └──────────────┘
    │                 └────────────┘
    │                        │
    │                        ▼
    │                 ┌──────────────┐
    │                 │ Telegram     │
    │                 │ 日报/告警    │ ───▶ 用户手机
    │                 └──────────────┘


  ╔════════════════════════════════════════════════════════╗
  ║              控制流 (决策链)                           ║
  ╚════════════════════════════════════════════════════════╝

  原始数据
      │
      ▼
  ┌──────────┐    ┌──────────────┐    ┌──────────────┐
  │ 技术指标  │───▶│  市场状态    │───▶│  信号合成器   │
  │ (可回测)  │    │  分类器      │    │  (按状态选    │
  └──────────┘    │ (LLM+规则)   │    │   参数集)     │
                  └──────────────┘    └──────┬───────┘
  ┌──────────┐                                     │
  │ LLM 分析  │────────────────────────────────────▶│
  │ (不可回测)│                                     │
  └──────────┘                                     │
                                                   ▼
                                            ┌──────────────┐
                                            │  执行器       │
                                            │  (Redis消费)  │
                                            │  → 风控校验   │
                                            │  → Alpaca下单 │
                                            └──────────────┘
```

### 10.4 参考资源

- [Alpaca Trading API](https://alpaca.markets/docs/)
- [Alpaca Python SDK](https://github.com/alpacahq/alpaca-py)
- [Claude API Documentation](https://docs.anthropic.com/)
- [Redis Streams 文档](https://redis.io/docs/data-types/streams/)
- [vectorbt (回测库)](https://github.com/polakowo/vectorbt)
- [Freqtrade 官方文档](https://www.freqtrade.io/) (备选方案参考)
- [Pydantic V2 文档](https://docs.pydantic.dev/) (数据校验)

### 10.5 风险告知 (必读)

> ⚠️ 本需求文档描述的是一个实验性的 AI 辅助交易系统，存在以下固有风险：
>
> 1. **金融风险**：所有交易决策最终由用户负责，系统输出不构成投资建议
> 2. **LLM 局限性**：Claude 的分析存在幻觉、偏见和已知/未知的错误模式
> 3. **回测局限性**：LLM 部分无法回测，历史表现不预示未来结果
> 4. **技术风险**：服务器宕机、API 故障、网络延迟等可能导致交易失败或延迟
> 5. **合规风险**：美股 PDT 规则、各国税务法规可能适用于您的交易行为
>
> **强烈建议**：初始阶段使用 Alpaca Paper Trading，确认系统稳定后再用小额资金过渡到实盘。

---

> **下一步**: 阅读完 v0.2 后，请确认以下事项：
> 1. 选择执行层方案 A（轻量执行器）还是方案 B（Freqtrade）？
> 2. Phase 1 的 3-4 周节奏是否可接受？
> 3. 是否开始 Phase 1 的代码实现？
>