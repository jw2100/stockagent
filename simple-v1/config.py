"""
Simple Stock Agent v1 — 配置文件
═══════════════════════════════════════════════════
你只需要改这个文件里的参数，agent.py 不需要动

快速上手:
  1. 复制 .env.example 为 .env，填入 Alpaca API Key
  2. 想分析哪些股票 → 改 STOCKS 列表
  3. 想调策略权重 → 改 STRATEGY_WEIGHTS
  4. 想改技术参数 → 改下面各个策略的参数
  5. 运行: python agent.py
"""

import os
from dotenv import load_dotenv

# 从 .env 文件读取 API Key (这样 Key 不会传到 GitHub)
load_dotenv()

# ─── Alpaca API 配置 ────────────────────────────────────────
# 去 https://alpaca.markets 注册 Paper Trading 账户
# Dashboard → API Keys 里找到这两个
API_KEY = os.getenv("ALPACA_API_KEY", "你的API_KEY_ID")
SECRET_KEY = os.getenv("ALPACA_SECRET_KEY", "你的SECRET_KEY")
BASE_URL = "https://paper-api.alpaca.markets"  # 模拟交易，不用改


# ─── 股票池 ────────────────────────────────────────────────
# 要分析哪些股票？想加减就直接改这个列表
# 注意: 只能用美股 (Alpaca 只支持美股)
STOCKS = [
    # ── 科技巨头 ──
    "AAPL", "MSFT", "GOOGL", "AMZN", "META",
    # ── 科技成长 ──
    "NVDA", "AMD", "TSLA",
    # ── 金融 ──
    "JPM", "GS",
    # ── 能源 ──
    "XOM", "CVX",
    # ── 医疗 ──
    "JNJ", "UNH",
    # ── 消费 ──
    "KO", "PEP", "WMT", "COST",
    # ── ETF 基准 ──
    "SPY", "QQQ",
]


# ─── 策略权重 ──────────────────────────────────────────────
# 5 个策略的权重，加起来 = 1.0
# 如果你觉得哪个策略特别准，就把它的权重大一些
# 比如觉得 RSI 最靠谱: "rsi": 0.50，其他的相应调小
STRATEGY_WEIGHTS = {
    "sma_crossover": 0.25,    # 均线交叉策略 (趋势跟踪)
    "rsi": 0.25,              # RSI 超买超卖策略 (动量反转)
    "macd": 0.20,             # MACD 策略 (趋势确认)
    "volume": 0.15,           # 成交量策略 (量价配合)
    "bband": 0.15,            # 布林带策略 (波动率回归)
}


# ─── 技术指标参数 ──────────────────────────────────────────
# SMA 均线 (Simple Moving Average)
SMA_FAST = 20        # 快线: 20 日均线 (短期趋势)
SMA_SLOW = 50        # 慢线: 50 日均线 (中期趋势)
                     # 快线上穿慢线 = 买入信号 (黄金交叉)
                     # 快线下穿慢线 = 卖出信号 (死亡交叉)

# RSI (Relative Strength Index)
RSI_PERIOD = 14      # RSI 计算周期 (14 天是标准值)
RSI_OVERSOLD = 35    # 超卖阈值: 低于此值 = 超卖，可能反弹 (买入)
RSI_OVERBOUGHT = 65  # 超买阈值: 高于此值 = 超买，可能回调 (卖出)
                     # 标准是 30/70，这里放宽到 35/65 让信号更多

# MACD (Moving Average Convergence Divergence)
MACD_FAST = 12       # 快线周期 (12 日 EMA)
MACD_SLOW = 26       # 慢线周期 (26 日 EMA)
MACD_SIGNAL = 9      # 信号线周期 (9 日 EMA)

# 布林带 (Bollinger Bands)
BBAND_PERIOD = 20    # 中轨周期 (20 日均线)
BBAND_STD = 2        # 标准差倍数 (2 倍 = 95% 的置信区间)
                     # 价格触及下轨 = 超卖，触及上轨 = 超买

# 成交量
VOLUME_SPIKE = 1.5   # 成交量突增倍数
                     # > 1.5 倍 = 放量，结合涨跌判断信号


# ─── 选股参数 ─────────────────────────────────────────────
TOP_N = 5            # 从所有股票里选分数最高的 N 只


# ─── 回测参数 ─────────────────────────────────────────────
BACKTEST_DAYS = 60   # 下载多少天的数据来做分析和回测
                     # 60 天 ≈ 3 个日历月，足够看趋势了
