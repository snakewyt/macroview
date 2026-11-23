import axios from 'axios';

const API_BASE = (import.meta.env.VITE_API_URL || '').replace(/\/$/, '');

const api = axios.create({
  baseURL: API_BASE,
  timeout: 20000,
});

export const fetchDashboard = async ({ refresh = false } = {}) => {
  const resp = await api.get('/api/v1/dashboard', {
    params: refresh ? { refresh: true } : undefined,
  });
  return resp.data;
};

export const fetchBullLiquidity = async () => {
  const resp = await api.get('/api/v1/bull-liquidity');
  return resp.data;
};

export const triggerBullLiquidityRefresh = async () => {
  const resp = await api.post('/api/v1/bull-liquidity/refresh');
  return resp.data;
};

export const fetchBullLiquidityStatus = async () => {
  const resp = await api.get('/api/v1/bull-liquidity/status');
  return resp.data;
};

export const fetchVixHistory = async (days = 30, refresh = false) => {
  const resp = await api.get('/api/v1/vix-history', {
    params: refresh ? { days, refresh: true } : { days },
  });
  return resp.data;
};

export function scissorsView(item) {
  const latest = Number(item?.spread);
  const prior = Number(item?.spread_6m);
  if (!Number.isFinite(latest)) return { signal: null, text: '缺数据', tone: 'missing', driver: null };
  if (!Number.isFinite(prior)) return { signal: 0, text: '已公布', tone: 'neutral', driver: '剪刀差方向不明' };
  const delta = latest - prior;
  if (delta >= 0.5 && latest > -3) return { signal: 2, text: '近半年在收窄', tone: 'good', driver: '剪刀差在收窄' };
  if (delta >= 0.5) return { signal: 1, text: '仍宽，但在收窄', tone: 'good', driver: '剪刀差在收窄' };
  if (delta <= -0.5 && latest <= -8) return { signal: -2, text: '近半年走得很宽', tone: 'bad', driver: '剪刀差在走阔' };
  if (delta <= -0.5) return { signal: -1, text: '近半年在走阔', tone: 'bad', driver: '剪刀差在走阔' };
  return { signal: 0, text: '近半年持平', tone: 'neutral', driver: '剪刀差持平' };
}

export function buildDailyBrief(data, bull) {
  const { meta = {}, overview = {} } = data || {};
  const suggestions = overview.suggestions || {};
  const factors = overview.factor_details || {};
  const dateLabel = meta.data_date || new Date().toISOString().slice(0, 10);
  const biasText = overview.bias === 'RISK_ON' ? '偏进攻 (RISK ON)'
    : overview.bias === 'RISK_OFF' ? '偏防守 (RISK OFF)'
    : '中性 (NEUTRAL)';

  const formatSignal = (sig) => (sig > 0 ? `+${sig}` : `${sig ?? '--'}`);
  const factorRows = Object.values(factors).map((f) => (
    `| ${f.name_cn} | ${formatSignal(f.signal)} | ${f.trend || '--'} | ${f.view || '--'}：${f.narrative || ''} |`
  ));

  const lines = [
    `📋 每日宏观简报 · ${dateLabel}`,
    '',
    `${biasText} · ${overview.label || '--'} · 总分 ${overview.score ?? '--'} / 2.0 · 置信度 ${overview.confidence ?? '--'}% · 权益建议仓位 ${suggestions.equity ?? '--'}%`,
    '',
    `核心观点：${overview.narrative || '暂无'}`,
    '',
    '📌 逻辑拆解',
    '| 因子 | 信号 | 变化 | 简评 |',
    '|---|---|---|---|',
    ...factorRows,
    '',
    `主要驱动：${(overview.primary_driver || []).join('、') || '暂无'}`,
    '',
    '🎯 配置建议',
    `- 权益：${suggestions.equity ?? '--'}%`,
    `- 债券：${suggestions.bond ?? '--'}%`,
    `- 黄金：${suggestions.gold ?? '--'}%`,
    `- 现金：${suggestions.cash ?? '--'}%`,
  ];

  if (bull?.stage) {
    lines.push(
      '',
      `🧭 A股流动性阶段：牛市「${bull.stage}」(${bull.met_count ?? 0}/8) · 熊市「${bull.bear?.stage || '--'}」(${bull.bear?.met_count ?? 0}/8)`,
    );
  }

  lines.push(
    '',
    `*数据日期：${dateLabel} · 来源：公开宏观数据快照 / 东方财富 / CBOE*`,
  );

  return lines.join('\n');
}
