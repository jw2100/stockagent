"""
Simple Stock Agent v1 — Agent 核心
═══════════════════════════════════════════════════
工作流程 (一目了然):
  Step 1 ── 下载股票数据  (DataFetcher)
  Step 2 ── 每只股票跑 5 个策略算出总分  (Strategies → score_stock)
  Step 3 ── 按总分排序，选 TOP N  (run_screening)
  Step 4 ── 模拟持有 7 天，回测收益  (_run_backtest)
  Step 5 ── 打印结果

新手须知:
  • 这是"选股"工具，不是"自动交易"——它只帮你挑股票
  • 每个策略输出一个分数，加权求和 = 总分
  • 总分越高 → Agent 越看好这只股票
  • 试着改 config.py 的参数，看看结果怎么变
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame
from tabulate import tabulate
from config import *


# ═══════════════════════════════════════════════════════════
#  Step 1: 获取数据
# ═══════════════════════════════════════════════════════════

class DataFetcher:
    """
    从 Alpaca API 下载股票历史数据。

    你不需要理解 Alpaca API 的细节，只需要知道:
    - get_bars() 返回一个字典: {"AAPL": DataFrame, "MSFT": DataFrame, ...}
    - 每个 DataFrame 包含: open, high, low, close, volume (开盘/最高/最低/收盘/成交量)
    """

    def __init__(self):
        """初始化 Alpaca 数据客户端 (用你的 API Key)"""
        self.client = StockHistoricalDataClient(API_KEY, SECRET_KEY)

    def get_bars(self, symbols, days=BACKTEST_DAYS):
        """
        下载多只股票的历史行情数据。

        参数:
            symbols: 股票列表，比如 ["AAPL", "MSFT"]
            days: 下载多少天的数据，默认 60 天

        返回:
            dict: {"AAPL": DataFrame(包含 OHLCV 数据), "MSFT": DataFrame, ...}
        """
        end = datetime.now()
        start = end - timedelta(days=days)

        # 构造 API 请求
        request = StockBarsRequest(
            symbol_or_symbols=symbols,
            timeframe=TimeFrame.Day,   # 日线数据
            start=start,
            end=end,
        )

        # 发送请求到 Alpaca
        bars = self.client.get_stock_bars(request)

        # 把返回的数据转成 DataFrame
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
                # 失败就跳过，不影响其他股票

        # ♻️ 成功获取的股票数量
        print(f"   成功获取 {len(result)}/{len(symbols)} 只股票数据")
        return result


# ═══════════════════════════════════════════════════════════
#  Step 2: 策略实现
# ═══════════════════════════════════════════════════════════

class Strategies:
    """
    5 个选股策略，每个策略回答一个问题。

    每个策略的输出:
      +1 或 +2  → 看好 (越大越看好)
      -1 或 -2  → 看空 (越小越看空)
       0         → 中性 (没明确信号)

    为什么用 +1/+2 而不是百分比?
    因为不同策略的量纲不同，用等级分更容易加权求和。
    """

    # ── 策略 1: 均线交叉 ──────────────────────────────────
    @staticmethod
    def sma_crossover(df):
        """
        均线交叉策略 — 趋势跟踪

        逻辑:
          短期均线 (SMA_FAST=20日) 上穿长期均线 (SMA_SLOW=50日) → 趋势向上 → 买入
          短期均线下穿长期均线 → 趋势向下 → 卖出

        适合: 趋势明显的行情 (单边上涨或下跌)
        不适合: 震荡行情 (频繁交叉，反复打脸)
        """
        if len(df) < SMA_SLOW:
            return 0  # 数据不够，无法计算

        # 分别计算快线和慢线
        sma_fast = df['close'].rolling(SMA_FAST).mean()
        sma_slow = df['close'].rolling(SMA_SLOW).mean()

        # 看今天的差值 和 昨天的差值
        current = sma_fast.iloc[-1] - sma_slow.iloc[-1]
        previous = sma_fast.iloc[-2] - sma_slow.iloc[-2]

        # 上穿: 昨天负 → 今天正 (刚刚形成金叉)
        if previous <= 0 and current > 0:
            return 2
        # 下穿: 昨天正 → 今天负 (刚刚形成死叉)
        if previous >= 0 and current < 0:
            return -2
        # 快线在慢线之上 (多头排列，趋势向上)
        if current > 0:
            return 1
        # 快线在慢线之下 (空头排列，趋势向下)
        if current < 0:
            return -1
        return 0

    # ── 策略 2: RSI ───────────────────────────────────────
    @staticmethod
    def rsi(df):
        """
        RSI 策略 — 均值回归

        逻辑:
          RSI < 35 → 超卖，股票被过度卖出，可能反弹 → 买入
          RSI > 65 → 超买，股票被过度买入，可能回调 → 卖出

        适合: 震荡行情 (价格在区间内来回波动)
        不适合: 强趋势行情 (RSI 会长期处于超买/超卖，过早卖出/买入)
        """
        if len(df) < RSI_PERIOD + 1:
            return 0

        # RSI 计算公式 (不用理解细节，知道是 0-100 的值就行)
        delta = df['close'].diff()
        gain = delta.where(delta > 0, 0).rolling(RSI_PERIOD).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(RSI_PERIOD).mean()

        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))

        current_rsi = rsi.iloc[-1]

        if pd.isna(current_rsi):
            return 0

        # RSI 越低 → 越超卖 → 越该买入
        if current_rsi < RSI_OVERSOLD:
            return 2   # 超卖了，买入信号较强
        elif current_rsi > RSI_OVERBOUGHT:
            return -2  # 超买了，卖出信号较强
        elif current_rsi < 50:
            return 1   # 偏弱，但还没到极端
        else:
            return -1  # 偏强，但还没到极端

    # ── 策略 3: MACD ──────────────────────────────────────
    @staticmethod
    def macd(df):
        """
        MACD 策略 — 趋势确认

        逻辑:
          MACD 线上穿信号线 → 动能转正 → 买入
          MACD 线下穿信号线 → 动能转负 → 卖出

        和均线交叉的区别:
          均线看价格，MACD 看动能 (价格变化的速度)
          均线慢半拍，MACD 更快反应变化
        """
        if len(df) < MACD_SLOW + MACD_SIGNAL:
            return 0

        # 计算 MACD 线和信号线
        ema_fast = df['close'].ewm(span=MACD_FAST).mean()
        ema_slow = df['close'].ewm(span=MACD_SLOW).mean()
        macd_line = ema_fast - ema_slow
        signal_line = macd_line.ewm(span=MACD_SIGNAL).mean()

        # MACD 柱 = MACD 线 - 信号线
        macd_hist = macd_line - signal_line

        current = macd_hist.iloc[-1]
        previous = macd_hist.iloc[-2]

        # 柱由负转正 → 动能从下跌变为上涨
        if previous <= 0 and current > 0:
            return 2
        # 柱由正转负 → 动能从上涨变为下跌
        if previous >= 0 and current < 0:
            return -2
        # 柱为正 → 上涨动能
        if current > 0:
            return 1
        # 柱为负 → 下跌动能
        if current < 0:
            return -1
        return 0

    # ── 策略 4: 成交量 ────────────────────────────────────
    @staticmethod
    def volume(df):
        """
        成交量策略 — 量价配合

        逻辑:
          放量 + 价格上涨 → 买方积极，上涨健康 → 看好
          放量 + 价格下跌 → 卖方主导，可能要跌 → 看空
          缩量 → 市场缺乏兴趣 → 中性偏空

        用成交量来佐证价格变化是否真实。
        """
        if len(df) < 20:
            return 0

        # 计算当前成交量是 20 日均量的多少倍
        avg_volume = df['volume'].rolling(20).mean()
        volume_ratio = df['volume'] / avg_volume

        current_ratio = volume_ratio.iloc[-1]
        price_change = df['close'].pct_change().iloc[-1]

        # 放量了 (> 1.5 倍)
        if current_ratio > VOLUME_SPIKE:
            if price_change > 0.02:      # 放量大涨 ✅
                return 2
            elif price_change < -0.02:    # 放量大跌 ❌
                return -2
            else:
                return 1                  # 放量但价格没怎么动
        # 缩量 (< 0.5 倍)
        elif current_ratio < 0.5:
            return -1  # 极度缩量，缺乏兴趣
        return 0

    # ── 策略 5: 布林带 ────────────────────────────────────
    @staticmethod
    def bband(df):
        """
        布林带策略 — 波动率回归

        逻辑:
          布林带 = 中轨 (20日均线) ± 2倍标准差
          价格跌到下轨 → 超卖，大概率反弹 → 买入
          价格涨到上轨 → 超买，大概率回调 → 卖出

        和 RSI 的区别:
          RSI 看"涨跌速度"，布林带看"偏离均值有多远"
        """
        if len(df) < BBAND_PERIOD:
            return 0

        # 计算中轨 (均线) 和标准差
        sma = df['close'].rolling(BBAND_PERIOD).mean()
        std = df['close'].rolling(BBAND_PERIOD).std()

        # 上轨 = 中轨 + 2 倍标准差
        # 下轨 = 中轨 - 2 倍标准差
        upper = sma + (std * BBAND_STD)
        lower = sma - (std * BBAND_STD)

        current_price = df['close'].iloc[-1]

        # 价格触及或跌破下轨 → 超卖
        if current_price <= lower.iloc[-1]:
            return 2
        # 价格触及或突破上轨 → 超买
        elif current_price >= upper.iloc[-1]:
            return -2
        # 在中轨下方但没破下轨 → 偏弱
        elif current_price <= sma.iloc[-1]:
            return 1
        # 在中轨上方但没破上轨 → 偏强
        else:
            return -1


# ═══════════════════════════════════════════════════════════
#  Step 3: Agent 核心 — 把上面所有东西串起来
# ═══════════════════════════════════════════════════════════

class StockAgent:
    """
    Stock Agent 的大脑。

    这个类做的事情:
    1. 让 DataFetcher 去下载数据
    2. 对每只股票调用 Strategies 里的 5 个策略
    3. 加权求和得到总分
    4. 排序选出 Top N 股票
    5. 做快速回测验证
    """

    def __init__(self):
        """初始化 Agent: 创建数据获取器 和 策略实例"""
        self.data_fetcher = DataFetcher()
        self.strategies = Strategies()

        # 把策略方法注册到一个字典里
        # 这样 score_stock() 可以遍历所有策略，不用写 5 遍 if
        self.strategy_methods = {
            "sma_crossover": self.strategies.sma_crossover,
            "rsi": self.strategies.rsi,
            "macd": self.strategies.macd,
            "volume": self.strategies.volume,
            "bband": self.strategies.bband,
        }

    def score_stock(self, df):
        """
        对一只股票运行所有策略，返回加权总分。

        参数:
            df: 这只股票的 OHLCV 数据 (DataFrame)

        返回:
            dict: {
                "total_score": 加权总分 (比如 +1.35),
                "details": { 每个策略的原始评分 },
                "signal": "strong_buy / buy / neutral / sell / strong_sell"
            }
        """
        details = {}
        total = 0

        # 对每个策略，算分 × 权重
        for name, method in self.strategy_methods.items():
            try:
                score = method(df)  # 策略返回 -2 到 +2
                weight = STRATEGY_WEIGHTS.get(name, 0)  # 对应权重
                details[name] = {"raw_score": score, "weight": weight}
                total += score * weight
            except Exception as e:
                # 某个策略出错不影响其他策略
                details[name] = {"raw_score": 0, "weight": 0, "error": str(e)}

        # 总分 → 信号等级
        # 阈值可以自己调: config.py 里没有是因为新手先别管
        if total >= 1.2:
            signal = "strong_buy"      # 🟢🟢 强烈看好
        elif total >= 0.5:
            signal = "buy"             # 🟢 看好
        elif total <= -1.2:
            signal = "strong_sell"     # 🔴🔴 强烈看空
        elif total <= -0.5:
            signal = "sell"            # 🔴 看空
        else:
            signal = "neutral"         # ⚪ 观望/中性

        return {"total_score": round(total, 2), "details": details, "signal": signal}

    def run_screening(self):
        """
        执行一次完整的选股流程。

        这是主入口方法，做这些事情:
        1. 打印标题和时间
        2. 下载所有股票的数据
        3. 对每只股票打分
        4. 按分数排序并打印排名表
        5. 打印每个策略的分解 (让你看到每个策略说了什么)
        6. 对 Top N 股票做快速回测
        7. 返回 Top N 股票列表

        返回:
            list[dict]: 得分最高的 N 只股票信息
        """
        print(f"\n{'='*60}")
        print(f"📊 Stock Agent v1 — 选股扫描")
        print(f"{'='*60}")
        print(f"📅 时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
        print(f"📂 股票池: {len(STOCKS)} 只")
        print(f"📖 数据区间: 最近 {BACKTEST_DAYS} 天")
        print(f"{'='*60}\n")

        # ── 下载数据 ──
        print("⏳ 下载数据中...")
        all_data = self.data_fetcher.get_bars(STOCKS)
        print()

        # ── 逐只评分 ──
        results = []
        for symbol, df in all_data.items():
            if df.empty or len(df) < 20:
                # 数据太少跳过 (至少要 20 天才能算指标)
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
                "data": df,  # 保留数据留到回测用
            })

        # 按总分从高到低排序
        results.sort(key=lambda x: x["score"], reverse=True)

        # ── 打印结果 ──
        self._print_results(results)
        self._print_strategy_breakdown(results)
        self._run_backtest(results[:TOP_N], all_data)

        return results[:TOP_N]

    # ─────────────────────────────────────────────────────
    #  打印方法 (纯输出，不需要改)
    # ─────────────────────────────────────────────────────

    def _print_results(self, results):
        """打印评分排名表"""
        print(f"\n{'─'*60}")
        print(f"📋 评分排名 (总分越高 = Agent 越看好)")
        print(f"{'─'*60}")

        table = []
        for i, r in enumerate(results, 1):
            signal_icon = {
                "strong_buy": "🟢🟢",
                "buy": "🟢",
                "neutral": "⚪",
                "sell": "🔴",
                "strong_sell": "🔴🔴"
            }.get(r["signal"], "⚪")

            table.append([
                i,
                r["symbol"],
                f"${r['price']:.2f}",
                f"{r['change_1d']:+.2f}%",
                f"{r['score']:+.2f}",
                signal_icon,
                r["signal"]
            ])

        print(tabulate(
            table,
            headers=["#", "股票", "价格", "日涨跌", "总分", "", "信号"],
            tablefmt="simple",
            numalign="right"
        ))

    def _print_strategy_breakdown(self, results):
        """打印策略分解 — 看看每个策略分别说了什么"""
        print(f"\n{'─'*60}")
        print(f"🔍 TOP {min(5, len(results))} 策略分解")
        print(f"  每个策略的原始分: +2=强烈看多  +1=看多  0=中性  -1=看空  -2=强烈看空")
        print(f"{'─'*60}")

        top5 = results[:min(5, len(results))]
        strategy_names = list(STRATEGY_WEIGHTS.keys())

        table = []
        for r in top5:
            row = [r["symbol"], r["signal"], f"{r['score']:+.2f}"]
            for s in strategy_names:
                raw = r["details"].get(s, {}).get("raw_score", 0)
                if raw > 0:
                    row.append(f"+{raw}")
                elif raw < 0:
                    row.append(f"{raw}")
                else:
                    row.append(" 0")
            table.append(row)

        headers = ["股票", "信号", "总分"] + [s.upper() for s in strategy_names]
        print(tabulate(table, headers=headers, tablefmt="simple"))

    def _run_backtest(self, top_stocks, all_data):
        """
        快速回测 — 模拟买入 Top N 股票。

        方法:
          假设 5 天前买入，持有到今天，看收益如何。
          同时对比 SPY (标普 500 ETF) 的同期收益。

        警告 ⚠️:
          这不是严格回测，只是一个快速验证。
          真实回测需要考虑: 滑点、手续费、逐日调仓。
          当前结果仅供参考，不要用来做实盘决策。
        """
        print(f"\n{'─'*60}")
        print(f"📈 快速回测 (模拟持有)")
        print(f"{'─'*60}")
        print(f"方法: 假设 5 天前买入 → 持有到今天卖出")
        print(f"对比: 同期 SPY 收益 (市场基准)")
        print(f"⚠️  仅供参考，不包含滑点和手续费\n")

        results = []
        for r in top_stocks:
            df = r["data"]
            if len(df) < 10:
                continue

            # 取最近 10 天数据
            recent = df.tail(10)
            if len(recent) < 6:
                continue

            # 5 天前"买入"，今天"卖出"
            entry_price = recent['close'].iloc[5]
            exit_price = recent['close'].iloc[-1]
            exit_date = recent.index[-1]

            pnl = (exit_price - entry_price) / entry_price * 100

            # 同期 SPY 收益
            spy_data = all_data.get("SPY")
            if spy_data is not None and len(spy_data) >= 10:
                spy_recent = spy_data.tail(10)
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

        # 按收益排序 (赚钱的排前面)
        results.sort(key=lambda x: x["pnl"], reverse=True)

        table = []
        for r in results:
            pnl_str = f"{r['pnl']:+.2f}%"
            vs_str = f"{r['vs_spy']:+.2f}%" if r['vs_spy'] is not None else "-"
            table.append([
                r["symbol"],
                f"{r['score']:+.2f}",
                f"${r['entry']:.2f}",
                f"${r['exit']:.2f}",
                pnl_str,
                vs_str,
                r["exit_date"]
            ])

        print(tabulate(
            table,
            headers=["股票", "评分", "买入价", "卖出价", "收益", "vs SPY", "卖出日"],
            tablefmt="simple",
            numalign="right"
        ))

        # 汇总统计
        if results:
            avg_pnl = np.mean([r["pnl"] for r in results])
            wins = sum(1 for r in results if r["pnl"] > 0)
            print(f"\n📊 汇总:")
            print(f"   平均收益: {avg_pnl:+.2f}%")
            print(f"   胜率: {wins}/{len(results)} ({wins/len(results)*100:.0f}%)")

            if results[0]["vs_spy"] is not None:
                avg_vs = np.mean(
                    [r["vs_spy"] for r in results if r["vs_spy"] is not None]
                )
                print(f"   超额收益 (vs SPY): {avg_vs:+.2f}%")


# ═══════════════════════════════════════════════════════════
#  启动入口
# ═══════════════════════════════════════════════════════════

def main():
    """创建 Agent → 跑一轮选股 → 打印结果"""
    print("🚀 Simple Stock Agent v1 启动中...")

    agent = StockAgent()
    top_picks = agent.run_screening()

    # 最终推荐
    print(f"\n{'='*60}")
    print(f"🏆 TOP {TOP_N} 推荐")
    print(f"{'='*60}")
    for i, pick in enumerate(top_picks, 1):
        icon = {
            "strong_buy": "🟢🟢", "buy": "🟢",
            "neutral": "⚪",
            "sell": "🔴", "strong_sell": "🔴🔴"
        }.get(pick["signal"], "⚪")
        print(f"  {i}. {icon} {pick['symbol']:6s}  |  评分: {pick['score']:+.2f}  |  {pick['signal']}")

    print(f"\n💡 想换股票? 改 config.py 里的 STOCKS 列表")
    print(f"💡 想调权重? 改 config.py 里的 STRATEGY_WEIGHTS")
    print(f"💡 想加策略? 在 agent.py 的 Strategies 类里加方法")
    print(f"\n📖 详细说明看 simple-v1.md")


if __name__ == "__main__":
    main()
