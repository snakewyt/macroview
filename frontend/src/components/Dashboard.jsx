import { useState, useEffect, useRef } from 'react';
import { buildDailyBrief, fetchBullLiquidity, fetchDashboard, scissorsView } from '../api/macroApi';
import BriefModal from './BriefModal';
import BullLiquidity from './BullLiquidity';
import FactorBreakdown from './FactorBreakdown';
import MacroCalendar from './MacroCalendar';
import VIXChart from './VIXChart';
import '../styles/dashboard.css';

const NAV_ITEMS = [
  { id: 'sec-overview', label: '顶层概览' },
  { id: 'sec-liquidity', label: 'A股流动性' },
  { id: 'sec-china', label: '中国内核' },
  { id: 'sec-global', label: '全球宏观' },
  { id: 'sec-fx', label: '美元与流动性' },
  { id: 'sec-assets', label: '全球资产' },
  { id: 'sec-risk', label: '波动与风险' },
  { id: 'sec-events', label: '事件日历' },
];

// 指标解释数据
const FIELD_EXPLANATIONS = {
  // === 中国内核模块 ===
  '官方制造业PMI': '经济体温计。>50=经济在扩张（发热），<50=在收缩（发冷）。每月第一个公布，最领先指标。',
  '财新制造业PMI': '中小企业+出口景气度。与官方PMI背离时需警惕（可能反映结构分化）。',
  'M1-M2剪刀差': '企业花钱意愿。拿最新月和六个月前比，变动不到 0.5 个百分点算持平。收窄=企业敢花钱，走阔=花钱变慢。',
  'CPI同比': '物价涨速。<1%=通缩（东西太便宜），>3%=通胀（东西太贵），1-2%最舒服。',
  'PPI同比': '工厂产品卖得好不好。负值=打折也卖不动（利润承压），正值=能涨价（利润改善）。',
  'LPR (1年)': '企业贷款基准利率。下调=宽松（利好），上调=收紧（利空）。',
  '社融增量': '当月实体经济拿到的资金。单月随季节起伏很大，结论看今年1月到当月的累计，和去年同一段比。累计少=信用偏慢。',
  '北向资金': '外资买卖A股的金额。持续流入=外资看好，持续流出=外资撤退。',

  // === 全球宏观模块 ===
  '美国ISM PMI': '全球经济风向标。>50=美国经济好（利好全球），<50=美国经济差（拖累全球）。',
  '核心PCE': '美联储最关心的通胀指标。>3%=不能降息（利空），<2.5%=可以降息（利好全球）。',
  '美国CPI同比': '公众通胀数据，市场波动最大的通胀指标。超预期→股跌债涨。',
  '联邦基金利率': '美国基准利率（美联储政策利率）。高位=全球流动性收紧。',
  '美联储资产负债表': '全球资金水龙头。扩表=放水（利好），缩表=抽水（利空）。',
  '隔夜逆回购': '市场闲钱多少。规模大=资金充裕，接近0=流动性紧张预警。',

  // === 美元与流动性模块 ===
  'DXY美元指数': '美元强弱。>105=强势美元（压制A股），<100=弱势美元（利好A股）。',
  '中美利差': '外资流向总开关。收窄=资本回流中国（利好），走阔=资本外逃（利空）。',
  '美债10Y-2Y利差': '经典美国衰退预警指标。长期倒挂(<0bp)预示经济降温，由负转正(陡峭化)往往对应降息周期启动。',
  '沪深300股债性价比': 'ERP = 1/PE(TTM) - 10Y中债收益率。越高代表股票相对国债越便宜；>6% 通常对应历史高性价比区间，<3% 偏贵。',
  'USD/CNH': '人民币汇率。>7.30=贬值压力（利空A股），<7.10=升值（利好）。',
  'USD/JPY': '套息交易温度。日元急升=套息平仓（危险信号，可能引发流动性危机）。',

  // === 全球核心资产模块 ===
  '标普500': '美股大盘。涨=全球风险偏好高，跌=全球避险。',
  '沪深300': 'A股大盘。中国最大300家公司，A股成绩单。',
  '恒生指数': '港股晴雨表。对全球流动性特别敏感，美元强时港股通常承压。',
  '日经225': '日本股市。套息交易+出口导向，对全球流动性高度敏感。',
  '黄金': '避险资产。地缘风险+实际利率下行时上涨。',
  'WTI原油': '通胀油门。>90$=通胀压力大（利空），<70$=通胀压力小（利好）。',
  'A股逆回购': '上交所 GC001，一天期国债逆回购利率。升高=场内隔夜资金变紧。',
  '纳斯达克': '美股成长股指数。涨=风险偏好高，跌=成长股承压。',
  '10Y美债收益率': '全球资产定价之锚。收益率上行=利率冲击（利空成长股）。',
  '2Y美债收益率': '对美联储政策利率最敏感的短端国债收益率。',
  '10Y中债收益率': '人民币资产定价锚。与美债利差影响外资流向。',

  // === 波动率与风险模块 ===
  'VIX恐慌指数': '全球心跳。VIX>25=市场恐慌（利空），<15=波动很低（警惕变盘）。',
  'MOVE指数': '美债波动率偏高时，美债价格和收益率在晃，折现率不稳。长久期资产、成长股和信用债更敏感，资金更偏向短债和现金。>=120 债市很慌，>=100 波动偏高，80 到 100 正常，<80 很平静。这条不进 5 因子仓位。',
  '高收益债利差': '美国高收益债相对国债的利差。>600bp=信用危险，<450bp=信用不紧。',
  'TED利差': '原版是3个月LIBOR减国库券，2022年已停更。这里用90天金融商业票据减13周国债。升高=银行间资金变紧。',
  'A股VIX': '50ETF期权波动率。>35=恐慌抛售，<15=过于平静。交易所不再发布 iVIX，这是公开日频里的替代。',
};

function readout(title, value, item) {
  const missing = value == null || value === '--' || value === '';
  const number = missing ? NaN : parseFloat(String(value).replace(/,/g, ''));
  const hasNumber = !Number.isNaN(number);

  if (title === '官方制造业PMI' || title === '财新制造业PMI' || title === '美国ISM PMI') {
    if (!hasNumber) return { text: '缺数据', tone: 'missing' };
    return number >= 50 ? { text: '扩张', tone: 'good' } : { text: '收缩', tone: 'bad' };
  }
  if (title === 'CPI同比') {
    if (!hasNumber) return { text: '缺数据', tone: 'missing' };
    if (number < 1) return { text: '偏低', tone: 'bad' };
    if (number > 3) return { text: '通胀偏高', tone: 'bad' };
    return { text: '物价温和', tone: 'good' };
  }
  if (title === '美国CPI同比' || title === '核心PCE') {
    if (!hasNumber) return { text: '没有这张表', tone: 'missing' };
    if (number > 3) return { text: '通胀仍高', tone: 'bad' };
    if (number < 2) return { text: '通胀偏低', tone: 'neutral' };
    return { text: '接近目标', tone: 'good' };
  }
  if (title === 'PPI同比') {
    if (!hasNumber) return { text: '缺数据', tone: 'missing' };
    return number < 0 ? { text: '工业承压', tone: 'bad' } : { text: '工厂端在涨价', tone: 'good' };
  }
  if (title === 'M1-M2剪刀差') {
    const view = scissorsView(item);
    return { text: view.text, tone: view.tone };
  }
  if (title === 'LPR (1年)') {
    if (!hasNumber) return { text: '缺数据', tone: 'missing' };
    return number <= 3.5 ? { text: '利率仍低', tone: 'good' } : { text: '利率偏高', tone: 'bad' };
  }
  if (title === '社融增量') {
    if (!hasNumber) return { text: '缺数据', tone: 'missing' };
    const ytd = item?.ytd;
    const prior = item?.ytd_last_year;
    if (ytd == null || prior == null) return { text: '已公布', tone: 'neutral' };
    if (ytd < prior) return { text: '今年累计偏少', tone: 'bad' };
    if (ytd > prior) return { text: '今年累计偏多', tone: 'good' };
    return { text: '今年累计相当', tone: 'neutral' };
  }
  if (title === '北向资金') return { text: '已经停更', tone: 'missing' };
  if (title === '联邦基金利率') {
    if (!hasNumber) return { text: '缺数据', tone: 'missing' };
    return number >= 3 ? { text: '政策利率仍高', tone: 'bad' } : { text: '政策利率偏低', tone: 'good' };
  }
  if (title === '美联储资产负债表') {
    if (item?.value == null) return { text: '没有这张表', tone: 'missing' };
    const change = item.weekly_change;
    if (change == null) return { text: '已公布', tone: 'neutral' };
    if (change < 0) return { text: '本周在缩表', tone: 'bad' };
    if (change > 0) return { text: '本周在扩表', tone: 'good' };
    return { text: '本周持平', tone: 'neutral' };
  }
  if (title === '隔夜逆回购') {
    const dollars = item?.value;
    if (dollars == null) return { text: '没有这张表', tone: 'missing' };
    return dollars < 1e11
      ? { text: '余额已经很小', tone: 'bad' }
      : { text: '闲钱还多', tone: 'good' };
  }
  if (title === 'DXY美元指数') {
    if (!hasNumber) return { text: '缺数据', tone: 'missing' };
    if (number >= 105) return { text: '强势美元', tone: 'bad' };
    if (number >= 100) return { text: '美元中性偏强', tone: 'neutral' };
    return { text: '美元偏弱', tone: 'good' };
  }
  if (title === '中美利差') {
    if (!hasNumber) return { text: '缺数据', tone: 'missing' };
    if (number <= -200) return { text: '利差很宽', tone: 'bad' };
    if (number <= -100) return { text: '利差偏宽', tone: 'neutral' };
    return { text: '利差不大', tone: 'good' };
  }
  if (title === '美债10Y-2Y利差') {
    if (!hasNumber) return { text: '缺数据', tone: 'missing' };
    if (number < 0) return { text: '曲线倒挂', tone: 'bad' };
    if (number < 50) return { text: '小幅正斜率', tone: 'neutral' };
    return { text: '曲线正常陡峭', tone: 'good' };
  }
  if (title === '沪深300股债性价比') {
    if (!hasNumber) return { text: '待拉取 PE', tone: 'missing' };
    if (number >= 6) return { text: '权益性价比很高', tone: 'good' };
    if (number >= 4.5) return { text: '权益偏便宜', tone: 'good' };
    if (number >= 3) return { text: '股债均衡', tone: 'neutral' };
    return { text: '权益偏贵', tone: 'bad' };
  }
  if (title === 'USD/CNH') {
    if (!hasNumber) return { text: '缺数据', tone: 'missing' };
    if (number >= 7.3) return { text: '贬值压力大', tone: 'bad' };
    if (number >= 7.1) return { text: '汇率中性', tone: 'neutral' };
    return { text: '人民币偏强', tone: 'good' };
  }
  if (title === 'USD/JPY') {
    if (!hasNumber) return { text: '缺数据', tone: 'missing' };
    return number >= 150 ? { text: '日元偏弱', tone: 'neutral' } : { text: '日元不弱', tone: 'neutral' };
  }
  if (title === '10Y中债收益率') {
    if (!hasNumber) return { text: '缺数据', tone: 'missing' };
    return number < 2 ? { text: '收益率偏低', tone: 'neutral' } : { text: '收益率不低', tone: 'neutral' };
  }
  if (title === '10Y美债收益率' || title === '2Y美债收益率') {
    if (!hasNumber) return { text: '缺数据', tone: 'missing' };
    return number >= 4 ? { text: '收益率偏高', tone: 'bad' } : { text: '收益率不高', tone: 'good' };
  }
  if (title === 'WTI原油') {
    if (!hasNumber) return { text: '缺数据', tone: 'missing' };
    return number >= 90 ? { text: '通胀压力大', tone: 'bad' } : { text: '通胀压力不大', tone: 'good' };
  }
  if (title === 'A股逆回购') {
    if (!hasNumber) return { text: '缺数据', tone: 'missing' };
    if (number >= 5) return { text: '隔夜资金偏紧', tone: 'bad' };
    if (number >= 2) return { text: '资金中性', tone: 'neutral' };
    return { text: '资金不紧', tone: 'good' };
  }
  if (title === 'VIX恐慌指数') {
    if (!hasNumber) return { text: '这次没有取到', tone: 'missing' };
    if (number >= 25) return { text: '市场恐慌', tone: 'bad' };
    if (number < 15) return { text: '波动很低', tone: 'neutral' };
    return { text: '波动正常', tone: 'good' };
  }
  if (title === 'MOVE指数') {
    if (!hasNumber) return { text: '这次没有取到', tone: 'missing' };
    const day = Date.parse(`${item?.date || ''}T00:00:00`);
    if (!item?.date || Number.isNaN(day)) return { text: '无新数', tone: 'missing' };
    if ((Date.now() - day) / 86400000 > 5) return { text: '旧数，不下结论', tone: 'missing' };
    if (number >= 120) return { text: '债市很慌', tone: 'bad' };
    if (number >= 100) return { text: '债市波动偏高', tone: 'bad' };
    if (number >= 80) return { text: '债市波动正常', tone: 'neutral' };
    return { text: '债市很平静', tone: 'good' };
  }
  if (title === '高收益债利差') {
    if (!hasNumber) return { text: '这次没有取到', tone: 'missing' };
    if (number > 600) return { text: '信用危险', tone: 'bad' };
    if (number < 450) return { text: '信用不紧', tone: 'good' };
    return { text: '信用中性', tone: 'neutral' };
  }
  if (title === 'A股VIX') {
    if (!hasNumber) return { text: '没有公开接口', tone: 'missing' };
    if (number >= 35) return { text: '恐慌抛售', tone: 'bad' };
    if (number < 15) return { text: '过于平静', tone: 'neutral' };
    return { text: '波动正常', tone: 'good' };
  }
  if (title === 'TED利差') {
    if (!hasNumber) return { text: '这次没有取到', tone: 'missing' };
    if (number >= 100) return { text: '银行间很紧', tone: 'bad' };
    if (number >= 50) return { text: '资金偏紧', tone: 'neutral' };
    return { text: '资金不紧', tone: 'good' };
  }
  return null;
}

const getSignalInfo = (signal) => {
  if (signal > 0) return { class: 'signal-bull', text: '看多', color: 'var(--green)' };
  if (signal < 0) return { class: 'signal-bear', text: '看空', color: 'var(--red)' };
  return { class: 'signal-neutral', text: '中性', color: 'var(--yellow)' };
};

// 单个指标卡片（支持点击外部/ESC 关闭 tooltip，自动防右侧溢出）
function MetricCard({ title, value, unit = '', note, item, signal, explanation }) {
  const [showTip, setShowTip] = useState(false);
  const [alignRight, setAlignRight] = useState(false);
  const tipWrapRef = useRef(null);

  useEffect(() => {
    if (!showTip) return undefined;
    const handlePointerDown = (e) => {
      if (tipWrapRef.current && !tipWrapRef.current.contains(e.target)) {
        setShowTip(false);
      }
    };
    const handleKeyDown = (e) => {
      if (e.key === 'Escape') setShowTip(false);
    };
    document.addEventListener('mousedown', handlePointerDown);
    document.addEventListener('keydown', handleKeyDown);
    return () => {
      document.removeEventListener('mousedown', handlePointerDown);
      document.removeEventListener('keydown', handleKeyDown);
    };
  }, [showTip]);

  const toggleTip = () => {
    if (!showTip && tipWrapRef.current) {
      const rect = tipWrapRef.current.getBoundingClientRect();
      setAlignRight(rect.left + 270 > window.innerWidth);
    }
    setShowTip((v) => !v);
  };

  const reading = readout(title, value, item);
  const signalInfo = !reading && signal != null ? getSignalInfo(signal) : null;
  const explanationText = FIELD_EXPLANATIONS[title] || explanation || '';
  const origin = reading?.tone === 'missing' && !item?.date
    ? ''
    : [item?.source, item?.date].filter(Boolean).join(' ');
  const tail = origin || note || '';

  return (
    <div className="card">
      <div className="title-row">
        <div className="title">{title}</div>
        {explanationText && (
          <div className="tip-wrap" ref={tipWrapRef}>
            <button
              type="button"
              className={`info-btn${showTip ? ' active' : ''}`}
              onClick={toggleTip}
              aria-label={`查看${title}的解释`}
              aria-expanded={showTip}
            >
              ?
            </button>
            {showTip && (
              <div className={`tooltip open${alignRight ? ' align-right' : ''}`} role="tooltip">
                {explanationText}
              </div>
            )}
          </div>
        )}
      </div>
      <div className="number">
        {value ?? '--'}
        {unit && <span className="unit-inline">{unit}</span>}
      </div>
      {(reading || tail) && (
        <div className="note">
          {reading && <span className={`verdict-${reading.tone}`}>{reading.text}</span>}
          {reading && tail ? ' · ' : ''}
          {tail}
        </div>
      )}
      {signalInfo && (
        <span className={`signal ${signalInfo.class}`} style={{ color: signalInfo.color }}>
          {signalInfo.text}
        </span>
      )}
    </div>
  );
}

export default function Dashboard() {
  const [data, setData] = useState(null);
  const [bull, setBull] = useState(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [briefOpen, setBriefOpen] = useState(false);
  const [error, setError] = useState(false);

  const fetchAll = (forceRefresh = false) => {
    if (forceRefresh) {
      setRefreshing(true);
    } else {
      setLoading(true);
    }
    setError(false);
    fetchBullLiquidity().then(setBull).catch(() => setBull(null));
    fetchDashboard({ refresh: forceRefresh })
      .then((d) => {
        if (!d || !d.meta) {
          setError(true);
          return;
        }
        setData(d);
        setError(false);
      })
      .catch(() => setError(true))
      .finally(() => {
        setLoading(false);
        setRefreshing(false);
      });
  };

  useEffect(() => { fetchAll(false); }, []);

  if (loading) {
    return (
      <div className="loading-screen">
        {[...Array(6)].map((_, i) => <div key={i} className="skeleton-card" />)}
      </div>
    );
  }

  if ((error || !data) && !bull) {
    return (
      <div className="error-screen">
        <p>数据加载失败，请确认后端接口已启动或稍后重试</p>
        <button className="retry-btn" onClick={() => fetchAll(true)}>重新加载</button>
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="dashboard">
        <div className="header">
          <h1>宏观量化仪表盘 · 中国视角</h1>
        </div>
        <BullLiquidity report={bull} />
        <div className="error-screen">
          <p>其余宏观模块这次没有加载出来</p>
          <button className="retry-btn" onClick={() => fetchAll(true)}>重新加载</button>
        </div>
      </div>
    );
  }

  const {
    overview = {},
    china_core = {},
    global_macro = {},
    fx_liquidity = {},
    assets = {},
    risk_monitor = {},
    events = [],
    meta = {},
  } = data;

  const riskClass = overview.bias === 'RISK_ON' ? 'risk-on' : overview.bias === 'RISK_OFF' ? 'risk-off' : 'neutral';
  const riskText = overview.bias === 'RISK_ON' ? '偏进攻' : overview.bias === 'RISK_OFF' ? '偏防守' : '中性';

  const cn10yYield = china_core.cn_10y_yield?.value ?? null;
  const us10yYield = assets.us_10y_yield?.value ?? global_macro.us_10y_yield?.value ?? null;
  const cnUsSpread = fx_liquidity.cn_us_10y_spread?.value != null
    ? Math.round(fx_liquidity.cn_us_10y_spread.value)
    : (cn10yYield != null && us10yYield != null ? Math.round((cn10yYield - us10yYield) * 100) : null);

  const snapshotTime = meta.public_updated_at ? Date.parse(meta.public_updated_at) : NaN;
  const snapshotDaysOld = Number.isNaN(snapshotTime) ? null : Math.floor((Date.now() - snapshotTime) / 86400000);
  const isStale = snapshotDaysOld != null && snapshotDaysOld >= 4;

  return (
    <div className="dashboard">
      {/* 顶部标题栏 */}
      <div className="header">
        <h1>📊 宏观量化仪表盘 · 中国视角</h1>
        <div className="header-actions">
          <span className={`update-time${isStale ? ' stale' : ''}`}>
            📅 {meta.data_date || '--'}
            {isStale ? `（快照已距今 ${snapshotDaysOld} 天）` : ''}
          </span>
          <button type="button" className="action-btn" onClick={() => setBriefOpen(true)}>
            今日简报
          </button>
          <button
            type="button"
            className="action-btn"
            onClick={() => fetchAll(true)}
            disabled={refreshing}
          >
            {refreshing ? '刷新中…' : '刷新数据'}
          </button>
        </div>
      </div>

      {/* 顶部快捷锚点导航 */}
      <nav className="section-nav" aria-label="模块导航">
        {NAV_ITEMS.map((item) => (
          <a key={item.id} href={`#${item.id}`} className="section-nav-pill">
            {item.label}
          </a>
        ))}
      </nav>

      {/* ========== 一、顶层概览 ========== */}
      <div id="sec-overview" className="section-title" style={{ marginTop: 0 }}>
        📋 一、顶层概览
        <span className="section-note">— 仪表盘的「结论区」，告诉你现在该怎么办</span>
      </div>
      <div className="top-level">
        <div className="risk-card">
          <div className="label">🌍 全球风险偏好 <span style={{ fontSize: 11, opacity: 0.7 }}>（信号灯）</span></div>
          <div className={`value ${riskClass}`}>{riskText}</div>
          <div className="sub">
            总分 {overview.score ?? '--'} · 置信度 {overview.confidence ?? '--'}%
          </div>
          <div style={{ marginTop: 8, fontSize: 13, color: 'var(--text-secondary)' }}>
            VIX {risk_monitor.vix?.value?.toFixed(2) || '--'} · MOVE {risk_monitor.move_idx?.date ? risk_monitor.move_idx.value?.toFixed(2) : '无新数'}
          </div>
        </div>

        <div className="driver-card">
          <div className="label">⚡ 主要驱动因素 <span style={{ fontSize: 11, opacity: 0.7 }}>（今天看什么）</span></div>
          <div className="tags">
            {(overview.primary_driver || []).map((d, i) => (
              <span key={i} className="tag">{d}</span>
            ))}
            {(!overview.primary_driver || overview.primary_driver.length === 0) && (
              <span className="tag">等待信号</span>
            )}
          </div>
          {overview.narrative && (
            <div style={{ marginTop: 10, fontSize: 13, color: 'var(--text-secondary)', borderTop: '1px solid #1e2a3a', paddingTop: 10, lineHeight: 1.5 }}>
              📌 {overview.narrative}
            </div>
          )}
        </div>

        <div className="risk-card">
          <div className="label">🎯 仓位建议 <span style={{ fontSize: 11, opacity: 0.7 }}>（怎么配）</span></div>
          <div className="value" style={{ color: riskClass === 'risk-off' ? 'var(--red)' : riskClass === 'risk-on' ? 'var(--green)' : 'var(--yellow)' }}>
            {overview.suggestions?.equity ?? '--'}%
          </div>
          <div className="sub">{overview.label || '--'}</div>
          <div style={{ marginTop: 8, fontSize: 13, color: 'var(--text-secondary)', display: 'flex', gap: 16, flexWrap: 'wrap' }}>
            <span>债券 <span style={{ color: 'var(--yellow)' }}>{overview.suggestions?.bond ?? '--'}%</span></span>
            <span>黄金 <span style={{ color: 'var(--yellow)' }}>{overview.suggestions?.gold ?? '--'}%</span></span>
            <span>现金 <span style={{ color: 'var(--text-muted)' }}>{overview.suggestions?.cash ?? '--'}%</span></span>
          </div>
        </div>
      </div>

      <FactorBreakdown factorDetails={overview.factor_details} />

      <div id="sec-liquidity">
        <BullLiquidity
          report={bull}
          onReload={() => fetchBullLiquidity().then(setBull).catch(() => {})}
        />
      </div>

      {/* ========== 二、中国内核 ========== */}
      <div id="sec-china" className="section-title">
        🇨🇳 二、中国内核
        <span className="section-note">— 中国经济的「体检报告」</span>
      </div>
      <div className="grid-4">
        <MetricCard title="官方制造业PMI" value={china_core.cn_pmi_official?.value} item={china_core.cn_pmi_official} />
        <MetricCard title="M1-M2剪刀差" value={china_core.cn_m1_m2_spread?.spread?.toFixed(1)} unit="%" item={china_core.cn_m1_m2_spread} />
        <MetricCard title="CPI同比" value={china_core.cn_cpi_yy?.value} unit="%" item={china_core.cn_cpi_yy} />
        <MetricCard title="PPI同比" value={china_core.cn_ppi_yy?.value} unit="%" item={china_core.cn_ppi_yy} />
      </div>
      <div className="grid-4">
        <MetricCard title="LPR (1年)" value={china_core.cn_lpr_1y?.value} unit="%" item={china_core.cn_lpr_1y} />
        <MetricCard title="社融增量" value={china_core.cn_social_financing?.value != null ? (china_core.cn_social_financing.value / 1e8).toFixed(0) : '--'} unit="亿" item={china_core.cn_social_financing} />
        <MetricCard title="财新制造业PMI" value={china_core.cn_pmi_caixin?.value} item={china_core.cn_pmi_caixin} />
        <MetricCard title="10Y中债收益率" value={cn10yYield != null ? Number(cn10yYield).toFixed(2) : '--'} unit="%" item={china_core.cn_10y_yield} />
      </div>
      <div className="grid-4">
        <MetricCard title="A股逆回购" value={china_core.cn_repo_gc001?.value} unit="%" item={china_core.cn_repo_gc001} />
        <MetricCard
          title="沪深300股债性价比"
          value={china_core.hs300_erp?.value != null ? Number(china_core.hs300_erp.value).toFixed(2) : '--'}
          unit="%"
          item={china_core.hs300_erp}
          note={china_core.hs300_erp?.pe ? `PE-TTM ${china_core.hs300_erp.pe}` : '刷新快照后自动计算'}
        />
      </div>

      {/* ========== 三、全球宏观 ========== */}
      <div id="sec-global" className="section-title">
        🌐 三、全球宏观
        <span className="section-note">— 「外部世界」的天气预报</span>
      </div>
      <div className="grid-4">
        <MetricCard title="美国ISM PMI" value={global_macro.us_ism_pmi?.value} item={global_macro.us_ism_pmi} />
        <MetricCard title="核心PCE" value={global_macro.us_core_pce_yy?.value} unit="%" item={global_macro.us_core_pce_yy} />
        <MetricCard title="美国CPI同比" value={global_macro.us_cpi_yy?.value} unit="%" item={global_macro.us_cpi_yy} />
        <MetricCard title="联邦基金利率" value={global_macro.fed_funds_rate?.range || global_macro.fed_funds_rate?.value} unit="%" item={global_macro.fed_funds_rate} />
      </div>
      <div className="grid-4">
        <MetricCard
          title="美联储资产负债表"
          value={global_macro.fed_balance_sheet?.value != null ? (global_macro.fed_balance_sheet.value / 1e12).toFixed(2) : '--'}
          unit="万亿"
          item={global_macro.fed_balance_sheet}
        />
        <MetricCard
          title="隔夜逆回购"
          value={global_macro.on_rrp_balance?.value != null ? (global_macro.on_rrp_balance.value / 1e8).toFixed(2) : '--'}
          unit="亿美元"
          item={global_macro.on_rrp_balance}
        />
      </div>
      {global_macro.source_note && <p className="bull-footnote">{global_macro.source_note}</p>}

      {/* ========== 四、美元与流动性 ========== */}
      <div id="sec-fx" className="section-title">
        💵 四、美元与流动性
        <span className="section-note">— 汇率与「水位」</span>
      </div>
      <div className="grid-4">
        <MetricCard title="DXY美元指数" value={fx_liquidity.dxy_idx?.value?.toFixed(2)} item={fx_liquidity.dxy_idx} />
        <MetricCard title="中美利差" value={cnUsSpread} unit="bp" item={fx_liquidity.cn_us_10y_spread} note="10年中债减10年美债" />
        <MetricCard
          title="美债10Y-2Y利差"
          value={fx_liquidity.us_10y_2y_spread?.value != null ? Math.round(fx_liquidity.us_10y_2y_spread.value) : '--'}
          unit="bp"
          item={fx_liquidity.us_10y_2y_spread}
        />
        <MetricCard title="USD/CNH" value={fx_liquidity.usd_cnh?.value?.toFixed(4)} item={fx_liquidity.usd_cnh} />
      </div>
      <div className="grid-4">
        <MetricCard title="USD/JPY" value={fx_liquidity.usd_jpy?.value?.toFixed(2)} item={fx_liquidity.usd_jpy} />
      </div>

      {/* ========== 五、全球核心资产 ========== */}
      <div id="sec-assets" className="section-title">
        📈 五、全球核心资产
        <span className="section-note">— 各类资产的「价格」</span>
      </div>
      <div className="grid-4">
        <MetricCard title="标普500" value={assets.spx?.value?.toLocaleString()} item={assets.spx} />
        <MetricCard title="纳斯达克" value={assets.nasdaq?.value?.toLocaleString()} item={assets.nasdaq} />
        <MetricCard title="沪深300" value={assets.hs300?.value?.toLocaleString()} item={assets.hs300} />
        <MetricCard title="恒生指数" value={assets.hsi?.value?.toLocaleString()} item={assets.hsi} />
      </div>
      <div className="grid-4">
        <MetricCard title="日经225" value={assets.nk225?.value?.toLocaleString()} item={assets.nk225} />
        <MetricCard title="黄金" value={assets.gold_spot?.value?.toLocaleString()} unit="$" item={assets.gold_spot} />
        <MetricCard title="WTI原油" value={assets.wti_oil?.value?.toFixed(2)} unit="$" item={assets.wti_oil} />
        <MetricCard title="10Y美债收益率" value={assets.us_10y_yield?.value} unit="%" item={assets.us_10y_yield} />
      </div>
      <div className="grid-4">
        <MetricCard title="2Y美债收益率" value={global_macro.us_2y_yield?.value} unit="%" item={global_macro.us_2y_yield} />
      </div>

      {/* ========== 六、波动率与风险 ========== */}
      <div id="sec-risk" className="section-title">
        ⚠️ 六、波动率与风险
        <span className="section-note">— 市场的「警报器」</span>
      </div>
      <div className="grid-4">
        <MetricCard title="VIX恐慌指数" value={risk_monitor.vix?.value?.toFixed(2)} item={risk_monitor.vix} />
        <MetricCard title="MOVE指数" value={risk_monitor.move_idx?.value?.toFixed(2)} item={risk_monitor.move_idx} />
        <MetricCard title="高收益债利差" value={risk_monitor.hy_spread_oas?.value?.toFixed(0)} unit="bp" item={risk_monitor.hy_spread_oas} />
        <MetricCard title="A股VIX" value={risk_monitor.cn_vix?.value?.toFixed(2)} item={risk_monitor.cn_vix} />
      </div>
      <div className="grid-4">
        <MetricCard title="TED利差" value={risk_monitor.ted_spread?.value?.toFixed(0)} unit="bp" item={risk_monitor.ted_spread} />
      </div>
      <VIXChart value={risk_monitor.vix?.value} />

      {/* ========== 七、宏观事件日历 ========== */}
      <MacroCalendar events={events} />

      {/* 底部 */}
      <div className="footer">
        <span>📊 数据来源：国家统计局 · 人民银行 · 东方财富 · CBOE · 纽约联储 · 美联储</span>
        <span>更新：{meta.updated_at ? new Date(meta.updated_at).toLocaleString('zh-CN') : '--'}</span>
      </div>

      <BriefModal
        open={briefOpen}
        content={buildDailyBrief(data, bull)}
        dateLabel={meta.data_date}
        onClose={() => setBriefOpen(false)}
      />
    </div>
  );
}
