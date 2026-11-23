# 宏观仪表盘 (MacroView)

中国视角全球大类资产宏观量化仪表盘，全部基于公开数据源（国家统计局 / 人民银行 / 中国货币网 / 中债 / 东方财富 / CBOE / 纽约联储 / 美国商务部 / 美联储 H.4.1，支持可选 FRED API Key 补齐）。

> 完整产品与信号规格见 [SPEC.md](SPEC.md)。

---

## 一句话定位

**「公开数据采集 → 信号合成与牛熊流动性评估 → 观点映射 → 每日简报」** —— 给投顾 / 个人及机构投资者提供中国视角的全球资产配置决策参考。

---

## 技术架构

```text
前端（React + Vite）
   │  GET /api/v1/dashboard, /api/v1/bull-liquidity, /api/v1/vix-history
   ▼
后端（FastAPI，本地 uvicorn 或 Vercel Python Serverless api/index.py）
   │  TTL 缓存 + 并发补充 + 统一 signal_engine 评分
   ▼
数据层（data/public_snapshot.json & data/bull_liquidity.json）
   └─ scripts/refresh_all.py（或 GitHub Actions 工作日定时刷新）
```

---

## 核心 API 端点

| API 端点 | 说明 |
|---|---|
| `GET /api/v1/dashboard` | 统一全景接口（`?refresh=true` 可跳过缓存强制刷新） |
| `GET /api/v1/overview` | 顶层决策锚点（RISK ON/OFF、置信度、总分、仓位建议） |
| `GET /api/v1/bull-liquidity` | A股牛市 / 熊市流动性 8 条条件及所处阶段 |
| `GET /api/v1/china-core` | 中国内核（PMI、CPI/PPI、社融、M1-M2、LPR、中债、GC001） |
| `GET /api/v1/global-macro` | 全球宏观（美国 ISM PMI、核心 PCE、CPI、联邦基金利率、H.4.1、ON RRP） |
| `GET /api/v1/fx-liquidity` | 美元与流动性（DXY、中美利差、USD/CNH、USD/JPY） |
| `GET /api/v1/assets` | 全球核心资产（标普500、纳斯达克、沪深300、恒指、日经、黄金、原油、美债） |
| `GET /api/v1/risk` | 波动率与风险（VIX、MOVE、高收益债 OAS、TED 替代利差、50ETF 波动率） |
| `GET /api/v1/vix-history` | VIX 历史曲线（有 FRED Key 走 FRED，否则自动走 CBOE 公开 CSV） |
| `GET /api/v1/health` | 健康检查与快照状态 |

---

## 信号合成规则（5 因子）

每因子打分 `-2` 到 `+2`，缺失因子不参与分母稀释总分，按有效权重归一化后映射到权益/债/金/现仓位：

| 因子 | 权重 |
|---|---:|
| 中美利差 | 20% |
| M1-M2 剪刀差 | 25% |
| VIX | 15% |
| 北向资金 | 15% |
| 高收益债利差 | 25% |

---

## 本地开发与运行

### 1. 安装 Python 依赖并刷新数据

```bash
pip install -r requirements.txt
python scripts/refresh_all.py          # 先拉取 public_snapshot.json，再计算 bull_liquidity.json
# python scripts/refresh_all.py --push # 刷新后自动提交推送到 GitHub
```

### 2. 启动后端

```bash
uvicorn backend.main:app --reload --port 8000
```

### 3. 启动前端

```bash
cd frontend
npm install
npm run dev
```

### 4. 运行单元测试

```bash
python -m unittest discover -s backend -p "test_*.py" -v
```

---

## 部署

- **Vercel**：[vercel.json](vercel.json) 已配置前端静态构建（`frontend/package.json`）与后端 Serverless 入口（[api/index.py](api/index.py)）。
- **定时数据更新**：[.github/workflows/update-data.yml](.github/workflows/update-data.yml) 支持工作日自动刷新或手动触发。
