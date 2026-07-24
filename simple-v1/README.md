# Simple Stock Agent v1

> 最简版 AI 选股 Agent — 5 个策略组合选股 + 回测验证
> 完整说明见 [simple-v1.md](../simple-v1.md)

## 快速开始 (5 分钟)

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 配置 API Key
cp .env.example .env
# 编辑 .env，填入你的 Alpaca API Key (注册: https://alpaca.markets)

# 3. 运行
python agent.py
```

## 文件说明

| 文件 | 用途 | 你需要动吗? |
|------|------|------------|
| `agent.py` | Agent 核心代码 (5 个策略 + 选股 + 回测) | 熟悉后再改 |
| `config.py` | 所有配置 (股票池、策略权重、技术参数) | **主要改这个** |
| `requirements.txt` | Python 依赖 | 只用装一次 |
| `.env.example` | API Key 模板 | 复制为 `.env` |
| `.env` | 你的 API Key **(不要传到 GitHub)** | 必须创建 |

## 怎么玩

1. **跑一次看看结果** → `python agent.py`
2. **换股票池** → 改 `config.py` 的 `STOCKS` 列表
3. **调权重** → 改 `config.py` 的 `STRATEGY_WEIGHTS`
4. **加策略** → 在 `agent.py` 的 `Strategies` 类加方法
5. **回到完整架构** → 读 [REQUIREMENTS.md](../REQUIREMENTS.md)
