import axios from 'axios';

const GITHUB_RAW_BASE = 'https://raw.githubusercontent.com/lj22503/macroview/main/data';
const API_BASE = import.meta.env.VITE_API_URL;

const api = axios.create({
  timeout: 15000,
});

export const fetchBullLiquidity = async () => {
  const base = API_BASE || '';
  const resp = await axios.get(`${base}/api/v1/bull-liquidity`);
  return resp.data;
};

// 统一全景接口（首屏使用）
export const fetchDashboard = async () => {
  if (API_BASE) {
    try {
      const resp = await axios.get(`${API_BASE}/api/v1/dashboard`);
      return resp.data;
    } catch (e) {
      console.error('Dashboard API failed:', e);
    }
  }
  try {
    const resp = await axios.get(`${GITHUB_RAW_BASE}/all_indicators.json`);
    return overlayLiveData(normalizeGithubData(resp.data));
  } catch (e) {
    console.error('GitHub fetch failed:', e);
    return overlayLiveData(emptyDashboard());
  }
};

function emptyDashboard() {
  return {
    meta: {
      updated_at: new Date().toISOString(),
      data_date: new Date().toISOString().slice(0, 10),
      status: 'partial',
    },
    overview: {},
    china_core: {},
    global_macro: {},
    fx_liquidity: {},
    assets: {},
    risk_monitor: {},
  };
}

function mergeFilled(base, patch) {
  const next = { ...(base || {}) };
  Object.entries(patch || {}).forEach(([key, item]) => {
    if (item == null) return;
    if (item.value == null && item.spread == null) return;
    next[key] = { ...next[key], ...item };
  });
  return next;
}

async function overlayLiveData(dashboard) {
  const base = API_BASE || '';
  let next = dashboard;
  try {
    const extra = await axios.get(`${base}/api/v1/public-snapshot`);
    const patch = extra.data || {};
    if (patch.status === 'ok') {
      next = {
        ...next,
        china_core: mergeFilled(next.china_core, patch.china_core),
        global_macro: mergeFilled(next.global_macro, patch.global_macro),
        fx_liquidity: mergeFilled(next.fx_liquidity, patch.fx_liquidity),
        assets: mergeFilled(next.assets, patch.assets),
        risk_monitor: mergeFilled(next.risk_monitor, patch.risk_monitor),
        meta: { ...next.meta, public_updated_at: patch.updated_at },
      };
    }
  } catch (e) {
    console.error('Public snapshot overlay failed:', e);
  }
  try {
    const extra = await axios.get(`${base}/api/v1/global-macro`);
    const patch = extra.data || {};
    const global = { ...(next.global_macro || {}) };
    for (const key of ['us_ism_pmi', 'us_cpi_yy', 'fed_funds_rate']) {
      if (patch[key]?.value != null) global[key] = { ...global[key], ...patch[key] };
    }
    global.source_note = patch.source_note;
    next = { ...next, global_macro: global };
  } catch (e) {
    console.error('East Money macro overlay failed:', e);
  }
  return { ...next, overview: buildOverview(next) };
}

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

function buildOverview(data) {
  const cn = data.china_core?.cn_10y_yield?.value;
  const us = data.assets?.us_10y_yield?.value ?? data.global_macro?.us_10y_yield?.value;
  const spread = cn != null && us != null ? (cn - us) * 100 : null;
  const scissorsItem = data.china_core?.cn_m1_m2_spread;
  const scissors = scissorsItem?.spread;
  const scissorsRead = scissorsView(scissorsItem);
  const vix = data.risk_monitor?.vix?.value;
  const credit = data.risk_monitor?.hy_spread_oas?.value;
  const factors = [];

  if (spread != null) {
    const signal = spread > -150 ? 1 : spread < -250 ? -1 : 0;
    factors.push({
      weight: 0.2,
      signal,
      text: signal < 0 ? '中美利差很宽' : signal > 0 ? '中美利差不宽' : '中美利差中性',
    });
  }
  if (scissors != null) {
    factors.push({ weight: 0.25, signal: scissorsRead.signal, text: scissorsRead.driver });
  }
  if (vix != null) {
    const signal = vix < 14 ? 2 : vix < 18 ? 1 : vix <= 22 ? 0 : vix <= 28 ? -1 : -2;
    factors.push({
      weight: 0.15,
      signal,
      text: signal <= -2 ? 'VIX 恐慌' : signal < 0 ? 'VIX 偏高' : signal > 0 ? 'VIX 偏低' : 'VIX 正常',
    });
  }
  if (credit != null) {
    const signal = credit < 350 ? 2 : credit < 450 ? 1 : credit <= 550 ? 0 : credit <= 700 ? -1 : -2;
    factors.push({ weight: 0.25, signal, text: signal > 0 ? '信用不紧' : signal < 0 ? '信用偏紧' : '信用中性' });
  }

  if (!factors.length) {
    return {
      bias: 'NEUTRAL',
      confidence: 0,
      score: 0,
      label: '因子不足',
      primary_driver: ['还没有可计算的因子'],
      suggestions: {},
      narrative: '四个因子都没有数，仓位先不下结论。',
    };
  }

  const weight = factors.reduce((sum, item) => sum + item.weight, 0);
  const score = Math.round((factors.reduce((sum, item) => sum + item.signal * item.weight, 0) / weight) * 100) / 100;
  let label = '系统性风险';
  let suggestions = { equity: 10, bond: 40, gold: 20, cash: 30 };
  if (score >= 1.5) {
    label = '全面扩张';
    suggestions = { equity: 85, bond: 10, gold: 5, cash: 0 };
  } else if (score >= 0.5) {
    label = '温和复苏';
    suggestions = { equity: 65, bond: 25, gold: 10, cash: 0 };
  } else if (score >= -0.5) {
    label = '结构分化';
    suggestions = { equity: 45, bond: 35, gold: 10, cash: 10 };
  } else if (score >= -1.5) {
    label = '收缩压力';
    suggestions = { equity: 25, bond: 40, gold: 15, cash: 20 };
  }
  const missing = [];
  if (credit == null) missing.push('信用利差没有公开数');
  const drivers = factors.filter((item) => item.signal !== 0).map((item) => item.text);
  const parts = [];
  if (vix != null) parts.push(`VIX ${Number(vix).toFixed(2)}`);
  if (spread != null) parts.push(`中美利差 ${Math.round(spread)}bp`);
  if (scissors != null) {
    const prior = scissorsItem?.spread_6m;
    parts.push(prior == null
      ? `M1-M2 ${scissors}，方向不明，这条先记中性`
      : `M1-M2 ${scissors}，六个月前 ${prior}，${scissorsRead.text}`);
  }
  if (credit != null) parts.push(`高收益债利差 ${Math.round(credit)}bp`);
  if (missing.length) parts.push(missing.join('，'));
  parts.push(`有数的因子合成后是${label}`);

  return {
    bias: score > 0.3 ? 'RISK_ON' : score < -0.3 ? 'RISK_OFF' : 'NEUTRAL',
    confidence: Math.min(95, Math.round((factors.length / 4) * 95)),
    score,
    label,
    primary_driver: (drivers.length ? drivers : ['有数的因子都在中性']).slice(0, 3),
    suggestions,
    narrative: `${parts.join('。')}。`,
  };
}

// 将 GitHub JSON 格式转换为前端期望的格式
function normalizeGithubData(raw) {
  const { meta, overview, china, fred, assets } = raw;

  // 计算数据新鲜度
  const dataDate = meta?.data_date || new Date().toISOString().slice(0, 10);
  const today = new Date().toISOString().slice(0, 10);
  const yesterday = new Date(Date.now() - 86400000).toISOString().slice(0, 10);
  let dataFreshness = 'expired';
  if (dataDate === today) dataFreshness = 'fresh';
  else if (dataDate === yesterday) dataFreshness = 'stale';

  // 构建 factor_details（如果不存在）
  const factorDetails = overview?.factor_details || generateFactorDetails(fred, china);

  return {
    meta: {
      ...(meta || {}),
      updated_at: meta?.updated_at || new Date().toISOString(),
      data_date: dataDate,
      data_freshness: dataFreshness,
      status: meta?.status || 'success',
    },
    overview: {
      bias: overview?.bias || 'NEUTRAL',
      confidence: overview?.confidence || 50,
      score: overview?.score || 0,
      label: overview?.label || '数据加载中',
      primary_driver: overview?.primary_driver || [],
      suggestions: overview?.suggestions || { equity: 50, bond: 30, gold: 10, cash: 10 },
      narrative: overview?.narrative || '数据加载中',
      factor_details: factorDetails,
    },
    china_core: normalizeChinaData(china),
    global_macro: normalizeFredGlobal(fred),
    fx_liquidity: normalizeFxLiquidity(fred, assets),
    assets: normalizeAssets(assets, fred),
    risk_monitor: normalizeRiskMonitor(fred),
  };
}

function generateFactorDetails(fred, china) {
  const vix = fred?.vix?.value;
  const spread = calculateSpread(china?.cn_10y_yield?.value, fred?.us_10y_yield?.value);
  const hySpread = fred?.hy_spread_oas?.value;
  const northMoney = china?.north_money_3d?.value;

  return {
    vix: { signal: vix ? (vix < 14 ? 2 : vix < 18 ? 1 : vix < 22 ? 0 : vix < 28 ? -1 : -2) : 0, weight: 0.15, view: '--', narrative: '' },
    cn_us_spread: { signal: spread ? (spread > -150 ? 2 : spread > -200 ? 1 : spread > -250 ? 0 : -1) : 0, weight: 0.20, view: '--', narrative: '' },
    m1_m2_spread: { signal: 0, weight: 0.25, view: '--', narrative: '' },
    north_money: { signal: northMoney ? (northMoney > 100 ? 2 : northMoney > 50 ? 1 : northMoney > -50 ? 0 : northMoney > -100 ? -1 : -2) : 0, weight: 0.15, view: '--', narrative: '' },
    credit_spread: { signal: hySpread ? (hySpread < 350 ? 2 : hySpread < 450 ? 1 : hySpread < 550 ? 0 : hySpread < 700 ? -1 : -2) : 0, weight: 0.25, view: '--', narrative: '' },
  };
}

function calculateSpread(cnYield, usYield) {
  if (cnYield && usYield) return (cnYield - usYield) * 100;
  return null;
}

function normalizeChinaData(china) {
  return {
    cn_pmi_official: { value: china?.cn_pmi_official?.value, source: 'AKShare' },
    cn_pmi_caixin: { value: china?.cn_pmi_caixin?.value, source: 'AKShare' },
    cn_cpi_yy: { value: china?.cn_cpi_yy?.value, source: 'AKShare' },
    cn_ppi_yy: { value: china?.cn_ppi_yy?.value, source: 'AKShare' },
    cn_m1_m2_spread: china?.cn_m1_m2_spread || null,
    cn_lpr_1y: { value: china?.cn_lpr_1y?.value, source: 'AKShare' },
    cn_social_financing: { value: china?.cn_social_financing?.value, source: 'AKShare' },
    cn_10y_yield: china?.cn_10y_yield || null,
    north_money_3d: { value: china?.north_money_3d?.value || china?.north_money?.value, source: 'AKShare' },
    north_money: { value: china?.north_money?.value, source: 'AKShare' },
  };
}

function normalizeFredGlobal(fred) {
  return {
    us_ism_pmi: { value: fred?.us_ism_pmi?.value, source: 'FRED' },
    us_core_pce_yy: { value: fred?.us_core_pce_yy?.value, source: 'FRED' },
    us_cpi_yy: { value: fred?.us_cpi_yy?.value, source: 'FRED' },
    fed_balance_sheet: { value: fred?.fed_balance_sheet?.value, source: 'FRED' },
    on_rrp_balance: { value: fred?.on_rrp_balance?.value, source: 'FRED' },
    fed_funds_rate: { value: fred?.fed_funds_rate?.value, source: 'FRED' },
    us_10y_yield: { value: fred?.us_10y_yield?.value, source: 'FRED' },
    us_2y_yield: { value: fred?.us_2y_yield?.value, source: 'FRED' },
  };
}

function normalizeFxLiquidity(fred, assets) {
  const cn10y = assets?.cn_10y_yield?.value || fred?.cn_10y_yield;
  const us10y = fred?.us_10y_yield?.value;
  const spread = cn10y && us10y ? (cn10y - us10y) * 100 : null;

  return {
    dxy_idx: { value: fred?.dxy_idx?.value, source: 'FRED' },
    cn_us_10y_spread: { value: spread, source: 'calculated' },
    usd_cnh: { value: assets?.usd_cnh?.value, source: 'yfinance' },
    usd_jpy: { value: assets?.usd_jpy?.value, source: 'yfinance' },
  };
}

function normalizeAssets(assets, fred) {
  return {
    spx: { value: fred?.spx?.value || assets?.spx?.value, source: 'FRED/yfinance' },
    hs300: { value: assets?.hs300?.value, source: 'yfinance' },
    hsi: { value: assets?.hsi?.value, source: 'yfinance' },
    nk225: { value: assets?.nk225?.value, source: 'yfinance' },
    gold_spot: { value: assets?.gold_spot?.value || assets?.gold?.value, source: 'yfinance' },
    wti_oil: { value: assets?.wti_oil?.value || assets?.crude?.value, source: 'yfinance' },
    btc_usd: { value: fred?.btc_usd?.value, source: 'FRED' },
    us_10y_yield: { value: fred?.us_10y_yield?.value, unit: '%', source: 'FRED' },
  };
}

function normalizeRiskMonitor(fred) {
  return {
    vix: { value: fred?.vix?.value, source: 'FRED' },
    move_idx: {
      value: fred?.move_idx?.value,
      date: fred?.move_idx?.date || '',
      source: fred?.move_idx?.source === 'YahooChart' ? '雅虎财经' : (fred?.move_idx?.source || ''),
    },
    hy_spread_oas: { value: fred?.hy_spread_oas?.value, source: 'FRED' },
    ted_spread: { value: fred?.ted_spread?.value, source: 'FRED' },
    cn_vix: { value: fred?.cn_vix?.value, source: 'FRED' },
  };
}

// 顶层概览（独立刷新）
export const fetchOverview = () => {
  if (!API_BASE) return Promise.reject(new Error('No API configured'));
  return axios.get(`${API_BASE}/api/v1/overview`).then(r => r.data);
};

// 各模块独立接口
export const fetchChinaCore = () => {
  if (!API_BASE) return Promise.reject(new Error('No API configured'));
  return axios.get(`${API_BASE}/api/v1/china-core`).then(r => r.data);
};

export const fetchGlobalMacro = () => {
  if (!API_BASE) return Promise.reject(new Error('No API configured'));
  return axios.get(`${API_BASE}/api/v1/global-macro`).then(r => r.data);
};

export const fetchFxLiquidity = () => {
  if (!API_BASE) return Promise.reject(new Error('No API configured'));
  return axios.get(`${API_BASE}/api/v1/fx-liquidity`).then(r => r.data);
};

export const fetchAssets = () => {
  if (!API_BASE) return Promise.reject(new Error('No API configured'));
  return axios.get(`${API_BASE}/api/v1/assets`).then(r => r.data);
};

export const fetchRisk = () => {
  if (!API_BASE) return Promise.reject(new Error('No API configured'));
  return axios.get(`${API_BASE}/api/v1/risk`).then(r => r.data);
};

export const fetchVixHistory = (days = 30) => {
  if (!API_BASE) return Promise.reject(new Error('No API configured'));
  return axios.get(`${API_BASE}/api/v1/vix-history`, { params: { days } });
};

// 兼容层：将新 API 结构映射回旧字段名（Dashboard.jsx 使用）
export const fetchAllData = async () => {
  const raw = await fetchDashboard();
  const { meta, overview, china_core, global_macro, fx_liquidity, assets: newAssets, risk_monitor } = raw;
  
  const china = {
    pmi: china_core?.cn_pmi_official,
    cpi: china_core?.cn_cpi_yy,
    ppi: china_core?.cn_ppi_yy,
    m1m2: china_core?.cn_m1_m2_spread,
    social: china_core?.cn_social_financing,
    lpr: china_core?.cn_lpr_1y,
    north_bound: china_core?.north_money_3d,
    a_share_iv: risk_monitor?.cn_vix,
    sentiment: overview?.score != null ? { value: overview.score } : null,
    confidence: overview?.confidence,
  };
  
  const fred = {
    vix: risk_monitor?.vix,
    ism: global_macro?.us_ism_pmi,
    dxy: fx_liquidity?.dxy_idx,
    baml: risk_monitor?.hy_spread_oas,
    move: risk_monitor?.move_idx,
    dgs10: global_macro?.us_10y_yield,
    dgs2: global_macro?.us_2y_yield,
  };
  
  const assets = {
    sp500: newAssets?.spx,
    hs300: newAssets?.hs300,
    gold: newAssets?.gold_spot,
    crude: newAssets?.wti_oil,
    usd_cnh: fx_liquidity?.usd_cnh,
  };
  
  return {
    overview,
    china,
    fred,
    assets,
    updated_at: meta?.updated_at,
  };
};
