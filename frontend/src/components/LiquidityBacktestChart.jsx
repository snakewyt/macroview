import { useEffect, useRef, useState } from 'react';
import { fetchBullLiquidityStatus, triggerBullLiquidityRefresh } from '../api/macroApi';

export default function LiquidityBacktestChart({ history = [], onReload }) {
  const [hoverIdx, setHoverIdx] = useState(null);
  const [generating, setGenerating] = useState(false);
  const [genError, setGenError] = useState('');
  const autoTriggeredRef = useRef(false);
  const pollRef = useRef(null);

  const startGenerate = async () => {
    setGenerating(true);
    setGenError('');
    try {
      await triggerBullLiquidityRefresh();
      if (pollRef.current) clearInterval(pollRef.current);
      pollRef.current = setInterval(async () => {
        try {
          const st = await fetchBullLiquidityStatus();
          if (!st.running) {
            clearInterval(pollRef.current);
            pollRef.current = null;
            setGenerating(false);
            if (st.last_error) {
              setGenError(st.last_error);
            } else if (onReload) {
              onReload();
            }
          }
        } catch {
          clearInterval(pollRef.current);
          pollRef.current = null;
          setGenerating(false);
        }
      }, 3000);
    } catch {
      setGenerating(false);
      setGenError('无法连接本机后端接口触发回测生成');
    }
  };

  useEffect(() => {
    if ((!history || history.length < 3) && !autoTriggeredRef.current) {
      autoTriggeredRef.current = true;
      startGenerate();
    }
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [history?.length]);

  if (!history || history.length < 3) {
    return (
      <div className="backtest-empty">
        {generating ? (
          <span>⏳ 正在后台自动拉取近 8 年宏观与沪深300数据并生成回测曲线，约需 15–30 秒，完成后将自动展示…</span>
        ) : (
          <div className="backtest-empty-row">
            <span>{genError ? `回测生成失败：${genError}` : '历史回测曲线尚未生成。'}</span>
            <button type="button" className="action-btn" onClick={startGenerate}>
              重新生成回测
            </button>
          </div>
        )}
      </div>
    );
  }

  const width = 760;
  const height = 190;
  const padLeft = 32;
  const padRight = 46;
  const padTop = 18;
  const padBottom = 26;
  const plotW = width - padLeft - padRight;
  const plotH = height - padTop - padBottom;

  const xOf = (idx) => (
    history.length <= 1
      ? padLeft + plotW / 2
      : padLeft + (idx / (history.length - 1)) * plotW
  );
  const yCount = (val) => padTop + ((8 - val) / 8) * plotH;

  const hsValues = history.map((item) => item.hs300).filter((v) => v != null);
  const hasHs = hsValues.length >= 2;
  const hsMin = hasHs ? Math.min(...hsValues) * 0.95 : 0;
  const hsMax = hasHs ? Math.max(...hsValues) * 1.05 : 1;
  const hsRange = Math.max(hsMax - hsMin, 1);
  const yHs = (val) => padTop + ((hsMax - val) / hsRange) * plotH;

  const bullPath = history
    .map((pt, i) => `${i === 0 ? 'M' : 'L'} ${xOf(i).toFixed(1)} ${yCount(pt.bull_met).toFixed(1)}`)
    .join(' ');
  const bearPath = history
    .map((pt, i) => `${i === 0 ? 'M' : 'L'} ${xOf(i).toFixed(1)} ${yCount(pt.bear_met).toFixed(1)}`)
    .join(' ');

  let hsPath = '';
  if (hasHs) {
    let started = false;
    hsPath = history
      .map((pt, i) => {
        if (pt.hs300 == null) return '';
        const cmd = started ? 'L' : 'M';
        started = true;
        return `${cmd} ${xOf(i).toFixed(1)} ${yHs(pt.hs300).toFixed(1)}`;
      })
      .filter(Boolean)
      .join(' ');
  }

  const active = history[hoverIdx != null ? hoverIdx : history.length - 1];
  const tickIndices = [0, Math.floor((history.length - 1) / 2), history.length - 1]
    .filter((v, i, arr) => arr.indexOf(v) === i);

  return (
    <div className="backtest-card">
      <div className="vix-chart-head">
        <div>
          <span className="vix-chart-title">牛熊流动性历史回测（无未来函数）</span>
          <span className="vix-chart-source">绿线=牛市满足数 · 红线=熊市满足数{hasHs ? ' · 金虚线=沪深300' : ''}</span>
        </div>
        <div className="vix-chart-readout">
          <span className="vix-chart-date">{active.date}</span>
          <span style={{ color: 'var(--green)' }}>牛 {active.bull_met}/8</span>
          <span style={{ color: 'var(--red)' }}>熊 {active.bear_met}/8</span>
          {active.hs300 != null && <span style={{ color: 'var(--gold)' }}>HS300 {active.hs300}</span>}
          <button
            type="button"
            className="backtest-refresh-btn"
            onClick={startGenerate}
            disabled={generating}
          >
            {generating ? '更新中…' : '更新回测'}
          </button>
        </div>
      </div>

      <svg
        viewBox={`0 0 ${width} ${height}`}
        className="vix-chart-svg"
        role="img"
        aria-label="牛熊流动性条件历史回测图"
        onMouseLeave={() => setHoverIdx(null)}
      >
        {[0, 4, 8].map((tick) => (
          <g key={tick}>
            <line
              x1={padLeft}
              y1={yCount(tick)}
              x2={width - padRight}
              y2={yCount(tick)}
              stroke="#1f2a38"
              strokeDasharray={tick === 4 ? '3 3' : undefined}
              strokeWidth="1"
            />
            <text x={padLeft - 6} y={yCount(tick) + 3} textAnchor="end" fill="#6b7280" fontSize="10">
              {tick}
            </text>
          </g>
        ))}

        {hasHs && (
          <>
            <text x={width - padRight + 6} y={padTop + 8} textAnchor="start" fill="#f0c27f" fontSize="10">
              {Math.round(hsMax)}
            </text>
            <text x={width - padRight + 6} y={padTop + plotH} textAnchor="start" fill="#f0c27f" fontSize="10">
              {Math.round(hsMin)}
            </text>
          </>
        )}

        {hsPath && (
          <path d={hsPath} fill="none" stroke="#f0c27f" strokeWidth="1.5" strokeDasharray="4 3" opacity="0.85" />
        )}
        <path d={bullPath} fill="none" stroke="#4cd9a0" strokeWidth="2" strokeLinejoin="round" />
        <path d={bearPath} fill="none" stroke="#f9757a" strokeWidth="2" strokeLinejoin="round" />

        {tickIndices.map((idx) => (
          <text
            key={idx}
            x={xOf(idx)}
            y={height - 6}
            textAnchor={idx === 0 ? 'start' : idx === history.length - 1 ? 'end' : 'middle'}
            fill="#6b7280"
            fontSize="10"
          >
            {history[idx].date}
          </text>
        ))}

        {history.map((pt, idx) => (
          <rect
            key={pt.date}
            x={xOf(idx) - plotW / Math.max(history.length * 2, 1)}
            y={padTop}
            width={plotW / Math.max(history.length, 1)}
            height={plotH}
            fill="transparent"
            onMouseEnter={() => setHoverIdx(idx)}
          />
        ))}
      </svg>
    </div>
  );
}
