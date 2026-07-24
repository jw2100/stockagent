# Simple Stock Agent v1 — 新手友好版

> **目标**: 写一个最简单的选股 Agent，组合多种策略筛选股票，跑回测验证
>
> **技能要求**: 会 `pip install`、能运行 Python 脚本即可
>
> **不用操心**: Docker / Redis / 数据库 / 部署 / 实盘 — 这些都先不管

---

## 📦 你需要的东西

```
1. 一台能上网的电脑 (Mac/Linux/Windows 都行)
2. Python 3.10+
3. 一个免费的 Alpaca 账号 → https://alpaca.markets 注册 Paper Trading 账户
   注册后获得: API Key ID 和 Secret Key (在 Dashboard → API Keys)
```

---

## 一、项目结构

整个项目只有 **3 个文件**，都在同一个目录下：

```
stockagent-simple/
├── config.py          # 配置 (API Key、策略参数)
├── agent.py           # Agent 核心 (策略 + 选股 + 回测)
└── requirements.txt   # 依赖
```

---

## 二、安装依赖

```bash
# 创建项目目录
mkdir stockagent-simple && cd stockagent-simple

# 创建 requirements.txt
cat > requirements.txt << 'EOF'
alpaca-py>=0.29.0
pandas>=2.0.0
numpy>=1.24.0
tabulate>=0.9.0
python-dotenv>=1.0.0
EOF

# 安装
pip install -r requirements.txt
```

---

## 三、配置 (config.py)

```python
"""
配置文件 — 在这里改参数就行了
"""
import os
from dotenv import load_dotenv

load_dotenv()

# ─── Alpaca API (从 .env 文件读取) ───
API_KEY = os.getenv("ALPACA_API_KEY", "你的KEY_ID")
SECRET_KEY = os.getenv("ALPACA_SECRET_KEY", "你的SECRET_KEY")
BASE_URL = "https://paper-api.alpaca.markets"  # 模拟交易

# ─── 要分析的股票列表 (可以随便加减) ───
STOCKS = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "META",   # 科技巨头
    "NVDA", "AMD", "TSLA",                       # 科技成长
    "JPM", "GS",                                 # 金融
    "XOM", "CVX",                                # 能源
    "JNJ", "UNH",                                # 医疗
    "KO", "PEP", "WMT", "COST",                 # 消费防御
    "SPY", "QQQ",                                 # ETF (市场基准)
]

# ─── 策略权重 (总和=1) ───
# 每个策略输出一个分数，加权求和得到总分
STRATEGY_WEIGHTS = {
    "sma_crossover": 0.25,    # 均线交叉
    "rsi": 0.25,              # RSI 超买超卖
    "macd": 0.20,             # MACD
    "volume": 0.15,           # 成交量异常
    "bband": 0.15,            # 布林带
}

# ─── 策略参数 ───
SMA_FAST = 20       # 快线天数
SMA_SLOW = 50       # 慢线天数
RSI_PERIOD = 14     # RSI 周期
RSI_OVERSOLD = 35   # 超卖阈值 (低于这个算买入信号)
RSI_OVERBOUGHT = 65 # 超买阈值 (高于这个算卖出信号)
MACD_FAST = 12
MACD_SLOW = 26
MACD_SIGNAL = 9
BBAND_PERIOD = 20   # 布林带周期
BBAND_STD = 2       # 标准差倍数
VOLUME_SPIKE = 1.5  # 成交量突增倍数 (高于均值的 1.5 倍)

# ─── 选股参数 ───
TOP_N = 5           # 选出分数最高的 N 只股票

# ─── 回测参数 ───
BACKTEST_DAYS = 60  # 回测天数
```

---

## 四、Agent 核心 (agent.py)

这是完整的 Agent 代码，我把每个部分都加了详细注释：

```python
"""
Simple Stock Agent v1

工作流程:
  1. 下载 N 只股票的历史数据
  2. 对每只股票运行 N 个策略 → 得到分数
  3. 加权汇总 → 选出分数最高的 TOP_N 只
  4. 模拟买入持有 → 回测收益
  5. 打印结果
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame
from tabulate import tabulate
from config import *


# ══════════════════════════════════════════════
#  第一步: 获取数据
# ══════════════════════════════════════════════

class DataFetcher:
    """从 Alpaca 下载历史行情数据"""
    
    def __init__(self):
        self.client = StockHistoricalDataClient(API_KEY, SECRET_KEY)
    
    def get_bars(self, symbols, days=BACKTEST_DAYS):
        """
        下载股票历史 K 线数据
        返回: dict { "AAPL": DataFrame, "MSFT": DataFrame, ... }
        """
        end = datetime.now()
        start = end - timedelta(days=days)
        
        request = StockBarsRequest(
            symbol_or_symbols=symbols,
            timeframe=TimeFrame.Day,
            start=start,
            end=end,
        )
        
        bars = self.client.get_stock_bars(request)
        
        result = {}
        for symbol in symbols:
            try:
                df = bars.dict()[symbol]
                df = pd.DataFrame(df)
                df['timestamp'] = pd.to_datetime(df['timestamp'])
                df.set_index('timestamp', inplace=True)
                df.sort_index(inplace=True)
                result[symbol] = df
            except Exception as e:
                print(f"  ⚠️  {symbol}: 数据获取失败 - {e}")
        
        return result


# ══════════════════════════════════════════════
#  第二步: 策略实现
# ══════════════════════════════════════════════

class Strategies:
    """
    每个策略返回一个分数:
      +1 到 +3  → 买入信号 (越大约看好)
      -1 到 -3  → 卖出信号 (越小越看空)
       0         → 中性/观望
    """
    
    @staticmethod
    def sma_crossover(df):
        """
        均线交叉策略
        快线上穿慢线 → 买入信号
        快线下穿慢线 → 卖出信号
        """
        if len(df) < SMA_SLOW:
            return 0
        
        sma_fast = df['close'].rolling(SMA_FAST).mean()
        sma_slow = df['close'].rolling(SMA_SLOW).mean()
        
        current = sma_fast.iloc[-1] - sma_slow.iloc[-1]
        previous = sma_fast.iloc[-2] - sma_slow.iloc[-2]
        
        # 上穿: 前一天负 → 今天正
        if previous <= 0 and current > 0:
            return 2
        # 下穿: 前一天正 → 今天负
        if previous >= 0 and current < 0:
            return -2
        # 快线在慢线之上 (多头排列)
        if current > 0:
            return 1
        # 快线在慢线之下 (空头排列)
        if current < 0:
            return -1
        return 0
    
    @staticmethod
    def rsi(df):
        """
        RSI 相对强弱指标
        低于超卖阈值 → 超卖，可能反弹 (买入信号)
        高于超买阈值 → 超买，可能回调 (卖出信号)
        """
        if len(df) < RSI_PERIOD + 1:
            return 0
        
        delta = df['close'].diff()
        gain = delta.where(delta > 0, 0).rolling(RSI_PERIOD).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(RSI_PERIOD).mean()
        
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        
        current_rsi = rsi.iloc[-1]
        
        if pd.isna(current_rsi):
            return 0
        
        if current_rsi < RSI_OVERSOLD:
            return 2  # 超卖了，买入
        elif current_rsi > RSI_OVERBOUGHT:
            return -2 # 超买了，卖出
        elif current_rsi < 50:
            return 1  # 偏弱但不在极端
        else:
            return -1 # 偏强但不在极端
    
    @staticmethod
    def macd(df):
        """
        MACD 指标
        MACD 线上穿信号线 → 买入
        MACD 线下穿信号线 → 卖出
        """
        if len(df) < MACD_SLOW + MACD_SIGNAL:
            return 0
        
        ema_fast = df['close'].ewm(span=MACD_FAST).mean()
        ema_slow = df['close'].ewm(span=MACD_SLOW).mean()
        macd_line = ema_fast - ema_slow
        signal_line = macd_line.ewm(span=MACD_SIGNAL).mean()
        
        macd_hist = macd_line - signal_line
        
        current = macd_hist.iloc[-1]
        previous = macd_hist.iloc[-2]
        
        # 由负转正 → 买入信号
        if previous <= 0 and current > 0:
            return 2
        # 由正转负 → 卖出信号
        if previous >= 0 and current < 0:
            return -2
        # 正值 (多头)
        if current > 0:
            return 1
        # 负值 (空头)
        if current < 0:
            return -1
        return 0
    
    @staticmethod
    def volume(df):
        """
        成交量策略
        成交量突增 + 价格上涨 → 放量上涨，看好
        成交量突增 + 价格下跌 → 放量下跌，看空
        """
        if len(df) < 20:
            return 0
        
        avg_volume = df['volume'].rolling(20).mean()
        volume_ratio = df['volume'] / avg_volume
        
        current_ratio = volume_ratio.iloc[-1]
        price_change = df['close'].pct_change().iloc[-1]
        
        if current_ratio > VOLUME_SPIKE:
            if price_change > 0.02:
                return 2    # 放量大涨
            elif price_change < -0.02:
                return -2   # 放量大跌
            else:
                return 1    # 放量但价格变化不大
        elif current_ratio < 0.5:
            # 极度缩量 → 可能缺乏兴趣
            return -1
        return 0
    
    @staticmethod
    def bband(df):
        """
        布林带策略
        价格触及下轨 → 超卖，可能反弹
        价格触及上轨 → 超买，可能回调
        """
        if len(df) < BBAND_PERIOD:
            return 0
        
        sma = df['close'].rolling(BBAND_PERIOD).mean()
        std = df['close'].rolling(BBAND_PERIOD).std()
        
        upper = sma + (std * BBAND_STD)
        lower = sma - (std * BBAND_STD)
        
        current_price = df['close'].iloc[-1]
        
        if current_price <= lower.iloc[-1]:
            return 2     # 触及下轨，超卖
        elif current_price >= upper.iloc[-1]:
            return -2    # 触及上轨，超买
        elif current_price <= sma.iloc[-1]:
            return 1     # 在中轨下方但未触及下轨
        else:
            return -1    # 在中轨上方但未触及上轨


# ══════════════════════════════════════════════
#  第三步: Agent 核心类
# ══════════════════════════════════════════════

class StockAgent:
    """
    Stock Agent 核心
    
    把数据获取、策略评分、选股、回测串起来
    """
    
    def __init__(self):
        self.data_fetcher = DataFetcher()
        self.strategies = Strategies()
        self.strategy_methods = {
            "sma_crossover": self.strategies.sma_crossover,
            "rsi": self.strategies.rsi,
            "macd": self.strategies.macd,
            "volume": self.strategies.volume,
            "bband": self.strategies.bband,
        }
    
    def score_stock(self, df):
        """
        对一只股票运行所有策略 → 返回加权总分
        
        参数:
            df: 该股票的 OHLCV DataFrame
            
        返回:
            {
                "total_score": 加权总分,
                "details": { 每个策略的原始分 },
                "signal": "strong_buy" / "buy" / "neutral" / "sell" / "strong_sell"
            }
        """
        details = {}
        total = 0
        
        for name, method in self.strategy_methods.items():
            try:
                score = method(df)
                weight = STRATEGY_WEIGHTS.get(name, 0)
                details[name] = {"raw_score": score, "weight": weight}
                total += score * weight
            except Exception as e:
                details[name] = {"raw_score": 0, "weight": 0, "error": str(e)}
        
        # 判定信号
        if total >= 1.2:
            signal = "strong_buy"
        elif total >= 0.5:
            signal = "buy"
        elif total <= -1.2:
            signal = "strong_sell"
        elif total <= -0.5:
            signal = "sell"
        else:
            signal = "neutral"
        
        return {"total_score": round(total, 2), "details": details, "signal": signal}
    
    def run_screening(self):
        """
        全市场扫描 → 为每只股票打分 → 排序 → 选 TOP_N
        """
        print(f"\n{'='*60}")
        print(f"📊 Stock Agent v1 — 选股扫描")
        print(f"{'='*60}")
        print(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
        print(f"扫描股票数: {len(STOCKS)}")
        print(f"回测天数: {BACKTEST_DAYS} 天")
        print(f"{'='*60}\n")
        
        # 获取数据
        print("⏳ 下载数据中...")
        all_data = self.data_fetcher.get_bars(STOCKS)
        print(f"   成功获取 {len(all_data)} 只股票数据\n")
        
        # 逐只评分
        results = []
        for symbol, df in all_data.items():
            if df.empty or len(df) < 20:
                continue
                
            score_result = self.score_stock(df)
            latest_price = df['close'].iloc[-1]
            price_change = df['close'].pct_change().iloc[-1] * 100
            
            results.append({
                "symbol": symbol,
                "price": latest_price,
                "change_1d": price_change,
                "score": score_result["total_score"],
                "signal": score_result["signal"],
                "details": score_result["details"],
                "data": df,  # 留到回测用
            })
        
        # 按分数排序
        results.sort(key=lambda x: x["score"], reverse=True)
        
        self._print_results(results)
        self._print_strategy_breakdown(results)
        self._run_backtest(results[:TOP_N], all_data)
        
        return results[:TOP_N]
    
    def _print_results(self, results):
        """打印选股结果"""
        print(f"\n{'─'*60}")
        print(f"📋 评分排名")
        print(f"{'─'*60}")
        
        table = []
        for i, r in enumerate(results, 1):
            signal_icon = {
                "strong_buy": "🟢🟢", "buy": "🟢",
                "neutral": "⚪",
                "sell": "🔴", "strong_sell": "🔴🔴"
            }.get(r["signal"], "⚪")
            
            table.append([
                i, r["symbol"], f"${r['price']:.2f}",
                f"{r['change_1d']:+.2f}%",
                f"{r['score']:+.2f}", signal_icon, r["signal"]
            ])
        
        print(tabulate(
            table,
            headers=["#", "股票", "价格", "日涨跌", "总分", "", "信号"],
            tablefmt="simple",
            numalign="right"
        ))
    
    def _print_strategy_breakdown(self, results):
        """打印策略分解 (看看每个策略分别说了什么)"""
        print(f"\n{'─'*60}")
        print(f"🔍 TOP 5 策略分解 (每个策略的原始分)")
        print(f"{'─'*60}")
        
        top5 = results[:5]
        strategies_names = list(STRATEGY_WEIGHTS.keys())
        
        table = []
        for r in top5:
            row = [r["symbol"], r["signal"], f"{r['score']:+.2f}"]
            for s in strategies_names:
                raw = r["details"].get(s, {}).get("raw_score", 0)
                # 用符号表示
                if raw > 0:
                    row.append(f"+{raw}")
                elif raw < 0:
                    row.append(f"{raw}")
                else:
                    row.append(" 0")
            table.append(row)
        
        headers = ["股票", "信号", "总分"] + [s.upper() for s in strategies_names]
        print(tabulate(table, headers=headers, tablefmt="simple"))
    
    def _run_backtest(self, top_stocks, all_data):
        """
        回测: 模拟在"今天"买入 TOP 股票
        假设 7 天后卖出，看看收益
        
        注意: 这不是严格回测，只是快速验证
              真正的回测应该逐日模拟，但新手先看个大概就好
        """
        print(f"\n{'─'*60}")
        print(f"📈 快速回测 (模拟持有 7 个交易日)")
        print(f"{'─'*60}")
        print(f"假设: 按今日收盘价买入 → 7 天后卖出")
        print(f"⚠️  这只是快速验证，不包含滑点/手续费\n")
        
        results = []
        for r in top_stocks:
            df = r["data"]
            if len(df) < 12:  # 至少需要 5 天数据 + 7 天回测
                continue
            
            # 取最近 12 天的数据 (5 天前到 5 天后)
            recent = df.tail(12)
            if len(recent) < 7:
                continue
                
            entry_price = recent['close'].iloc[5]     # "买入"价格
            exit_price = recent['close'].iloc[-1]      # "卖出"价格
            exit_date = recent.index[-1]
            
            pnl = (exit_price - entry_price) / entry_price * 100
            
            # 也看下同期 SPY 的表现 (基准)
            spy_data = all_data.get("SPY")
            if spy_data is not None and len(spy_data) >= 12:
                spy_recent = spy_data.tail(12)
                spy_entry = spy_recent['close'].iloc[5]
                spy_exit = spy_recent['close'].iloc[-1]
                spy_pnl = (spy_exit - spy_entry) / spy_entry * 100
            else:
                spy_pnl = None
            
            results.append({
                "symbol": r["symbol"],
                "score": r["score"],
                "entry": entry_price,
                "exit": exit_price,
                "pnl": pnl,
                "vs_spy": round(pnl - spy_pnl, 2) if spy_pnl is not None else None,
                "exit_date": exit_date.strftime("%m-%d"),
            })
        
        results.sort(key=lambda x: x["pnl"], reverse=True)
        
        table = []
        for r in results:
            pnl_str = f"{r['pnl']:+.2f}%"
            vs_str = f"{r['vs_spy']:+.2f}%" if r['vs_spy'] is not None else "-"
            table.append([
                r["symbol"], f"{r['score']:+.2f}",
                f"${r['entry']:.2f}", f"${r['exit']:.2f}",
                pnl_str, vs_str, r["exit_date"]
            ])
        
        print(tabulate(
            table,
            headers=["股票", "评分", "买入价", "卖出价", "收益", "vs SPY", "卖出日"],
            tablefmt="simple",
            numalign="right"
        ))
        
        # 汇总
        if results:
            avg_pnl = np.mean([r["pnl"] for r in results])
            wins = sum(1 for r in results if r["pnl"] > 0)
            print(f"\n📊 汇总: 平均收益 {avg_pnl:+.2f}% | 胜率 {wins}/{len(results)}")
            
            if results[0]["vs_spy"] is not None:
                avg_vs = np.mean([r["vs_spy"] for r in results if r["vs_spy"] is not None])
                print(f"📊 vs SPY: 平均超额 {avg_vs:+.2f}%")


# ══════════════════════════════════════════════
#  第四步: 运行入口
# ══════════════════════════════════════════════

def main():
    """启动 Agent"""
    agent = StockAgent()
    top_picks = agent.run_screening()
    
    print(f"\n{'='*60}")
    print(f"🏆 TOP {TOP_N} 推荐")
    print(f"{'='*60}")
    for i, pick in enumerate(top_picks, 1):
        print(f"  {i}. {pick['symbol']:6s} | 评分: {pick['score']:+.2f} | 信号: {pick['signal']}")
    
    print(f"\n💡 提示: 去 config.py 改 STOCKS 列表或策略参数，看看结果怎么变")
    print(f"💡 提示: 多跑几次，观察哪些策略在最近行情中表现更好")


if __name__ == "__main__":
    main()
```

---

## 五、创建 .env 文件

在项目目录创建 `.env` 文件，填入你的 Alpaca API Key：

```bash
# .env
ALPACA_API_KEY=pk_your_actual_key_here
ALPACA_SECRET_KEY=your_actual_secret_here
```

> **没 Alpaca 账号？** 去 https://alpaca.markets 注册，选 Paper Trading (模拟交易)，5 分钟搞定。

---

## 六、运行！

```bash
python agent.py
```

正常输出长这样：

```
============================================================
📊 Stock Agent v1 — 选股扫描
============================================================
时间: 2026-07-20 14:30
扫描股票数: 18
回测天数: 60 天
============================================================

⏳ 下载数据中...
   成功获取 16 只股票数据

────────────────────────────────────────────────────────────
📋 评分排名
────────────────────────────────────────────────────────────
  #  股票     价格        日涨跌       总分        信号
──  ──────  ────────  ─────────  ────────  ───  ──────────
  1  NVDA    $128.45     +2.34%     +1.85      🟢🟢 strong_buy
  2  MSFT    $468.20     +0.87%     +1.20      🟢   buy
  3  AAPL    $235.10     +1.12%     +0.95      🟢   buy
  4  AMZN    $198.70     +0.45%     +0.80      🟢   buy
...

🔍 TOP 5 策略分解
────────────────────────────────────────────────────────────
  股票    信号         总分    SMA_CROSSOVER  RSI   MACD  VOLUME  BBAND
──  ──────  ────────  ─────  ─────────────  ───  ─────  ──────  ─────
NVDA  strong_buy  +1.85   +1          +2    +2    +2     -1
MSFT  buy         +1.20   +2          +1    +1    0      +1
...

📈 快速回测 (模拟持有 7 个交易日)
────────────────────────────────────────────────────────────
假设: 按今日收盘价买入 → 7 天后卖出
⚠️   这只是快速验证，不包含滑点/手续费

  股票     评分    买入价     卖出价      收益      vs SPY   卖出日
──  ──────  ──────  ────────  ────────  ────────  ────────  ──────
NVDA     +1.85   $128.45    $132.30    +3.00%    +1.50%    07-27
MSFT     +1.20   $468.20    $470.10    +0.41%    -1.09%    07-27
...

📊 汇总: 平均收益 +1.27% | 胜率 3/5
📊 vs SPY: 平均超额 +0.35%

============================================================
🏆 TOP 5 推荐
============================================================
  1. NVDA   | 评分: +1.85 | 信号: strong_buy
  2. MSFT   | 评分: +1.20 | 信号: buy
  3. AAPL   | 评分: +0.95 | 信号: buy
  4. AMZN   | 评分: +0.80 | 信号: buy
  5. META   | 评分: +0.65 | 信号: buy
```

---

## 七、各种玩法 — 自己改着玩

### 1️⃣ 换股票池

在 `config.py` 里改 `STOCKS` 列表：

```python
# 只分析 A 股？不行，Alpaca 只支持美股
# 但你可以换成任何美股
STOCKS = ["AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "TSLA", "SPY"]
```

### 2️⃣ 调策略权重

```python
# 如果你觉得 RSI 特别准，就把它的权重调高
STRATEGY_WEIGHTS = {
    "sma_crossover": 0.10,   # 降低
    "rsi": 0.50,             # 提高！我最信 RSI
    "macd": 0.20,
    "volume": 0.10,
    "bband": 0.10,
}
```

### 3️⃣ 加一个自己的策略

在 `agent.py` 的 `Strategies` 类里加一个方法：

```python
@staticmethod
def my_secret_strategy(df):
    """
    我的神奇策略:
    如果股票名字里有 'A'，就买入
    """
    # 这里没有 symbol 信息，这个方法只是演示
    # 你可以从数据里算任何指标
    if df['close'].iloc[-1] > df['close'].iloc[-5]:
        return 1  # 5 天上涨 → 买入
    return -1
```

然后在 `StockAgent.__init__` 里注册：

```python
self.strategy_methods = {
    ...
    "my_secret": self.strategies.my_secret_strategy,
}
```

别忘在 `config.py` 的 `STRATEGY_WEIGHTS` 里加上权重。

### 4️⃣ 只选票，不要下载所有

在 `config.py` 把 `STOCKS` 设为只有几只，跑得飞快：

```python
STOCKS = ["AAPL", "MSFT", "NVDA"]  # 只分析这三只
```

---

## 八、理解你的 Agent 在干什么

```
                         ┌──────────┐
                         │ 股票池    │
                         │ 18 只美股  │
                         └────┬─────┘
                              │
                    ┌─────────▼─────────┐
                    │   下载 60 天数据    │
                    │   (Alpaca API)     │
                    └─────────┬─────────┘
                              │
               ┌──────────────┼──────────────┐
               │              │              │
          ┌────▼────┐   ┌────▼────┐   ┌────▼────┐
          │ AAPL    │   │ MSFT    │   │ NVDA    │  ...
          │ DataFrame│   │ DataFrame│   │ DataFrame│
          └────┬────┘   └────┬────┘   └────┬────┘
               │              │              │
          ┌────▼──────────────▼──────────────▼────┐
          │          对每只股票运行 5 个策略         │
          │                                        │
          │  SMA交叉 + RSI + MACD + 成交量 + 布林带  │
          │            加权求和 → 总分              │
          └────────────────┬───────────────────────┘
                           │
                    ┌──────▼──────┐
                    │ 按总分排序   │
                    │ 选 TOP 5    │
                    └──────┬──────┘
                           │
                    ┌──────▼──────┐
                    │ 模拟持有 7 天 │
                    │ 计算收益     │
                    │ vs SPY 基准  │
                    └─────────────┘
```

---

## 九、常见问题

### Q: 为什么有些股票数据获取失败？

Alpaca 免费账户可能无法获取某些股票的历史数据，或者该股票刚上市没有 60 天数据。直接忽略就好，不影响其他股票。

### Q: 回测结果很好看/很难看，能信吗？

⚠️ **不能全信**。这个回测非常粗糙：
- 用了"未来数据"？没有，但 7 天持有期是随机的
- 没算滑点（你买的时候价格可能不一样）
- 没算手续费
- 7 天太短，样本太少

**当个参考就好**，别看了结果就真金白银冲进去。

### Q: 怎么让结果更可信？

```python
# 在 config.py 里：
BACKTEST_DAYS = 365    # 看 1 年数据
TOP_N = 3              # 只选最看好的 3 只
```

然后自己在代码里改：把"7 天模拟"改成"每天模拟买入，持有 30 天"，但这需要更多代码。下一版会做。

### Q: 能实盘吗？

**千万不要！**
- 这只是个选票工具，没有风控
- 回测不严谨
- 没有止损
- 没有仓位管理

**至少**等 v2 或 v3，加了止损和仓位管理，再用 Paper Trading mock 跑一个月再说。

### Q: Alpaca 的 API Key 安全吗？

`.env` 文件不要传到 GitHub。已经在 `.gitignore` 里加好：

```bash
echo ".env" >> .gitignore
```

---

## 十、完整的代码量

```
stockagent-simple/
├── config.py             ~50 行
├── agent.py              ~300 行
├── requirements.txt      ~5 行
└── .env                  2 行

总共不到 400 行 Python
```

你能在 **30 分钟内** 跑起来，然后花一下午改参数、加策略、看不同股票池的结果。

---

## 十一、下一版预告

如果你想继续：

| 版本 | 新增功能 | 学习价值 |
|------|----------|----------|
| v1.1 | 把结果画成图表 (matplotlib) | 可视化 |
| v1.2 | 严格回测 (逐日模拟, 非 7 天) | 回测方法论 |
| v1.3 | Telegram 每天自动推送结果 | 自动化 |
| v2   | 加止损 + 仓位管理 | 风控 |
| v3   | 通过 Redis/API 接入执行系统 | 对接 REQUIREMENTS.md 的完整架构 |

---

> **下一步**: 复制代码，装依赖，跑起来。先玩 30 分钟熟悉流程，再想下一步。
>
> 有问题随时问 — 这个版本就是让你试错用的，改坏了删掉重来就行。
