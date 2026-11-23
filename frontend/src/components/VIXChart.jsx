import { useEffect, useState } from 'react';
import { fetchVixHistory } from '../api/macroApi';

export default function VIXChart({ value, compact = false }) {
  const [history, setHistory] = useState([]);
  const [source, setSource] = useState('');
  const [loading, setLoading] = useState(true);
  const [hoverIdx, setHoverIdx] = useState(null);
  const height = compact ? 130 : 168;

  useEffect(() => {
    let active = true;
    fetchVixHistory(30)
      .then((res) => {
        if (!active) return;
        const rows = (res?.data || []).filter((item) => item && item.value != null);
        setHistory(rows);
        setSource(res?.source || '');
      })
      .catch(() => {
        if (active) setHistory([]);
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => { active = false; };
  }, []);

  if (loading || !history.length) {
    return (
      <div className="vix-chart-empty" style={{ height }}>
        {loading ? '正在加载近 30 日 VIX 走势…' : '暂无 VIX 历史数据'}
      </div>
    );
  }

  const chartData = [...history];
  if (value != null && chartData.length > 0) {
    const last = chartData[chartData.length - 1];
    if (Math.abs(last.value - value) > 0.01) {
      chartData.push({ date: '最新', value });
    }
  }

  const baseline = 20;
  const values = chartData.map((d) => Number(d.value));
  const minVal = Math.floor(Math.min(...values, baseline) * 0.9);
  const maxVal = Math.ceil(Math.max(...values, baseline) * 1.1);
  const range = Math.max(maxVal - minVal, 1);

  const width = 720;
  const padLeft = 36;
  const padRight = 14;
  const padTop = 14;
  const padBottom = 26;
  const plotW = width - padLeft - padRight;
  const plotH = height - padTop - padBottom;

  const xOf = (idx) => (
    chartData.length <= 1
      ? padLeft + plotW / 2
      : padLeft + (idx / (chartData.length - 1)) * plotW
  );
  const yOf = (val) => padTop + ((maxVal - val) / range) * plotH;

  const points = chartData.map((d, idx) => ({
    x: xOf(idx),
    y: yOf(d.value),
    date: d.date,
    value: d.value,
  }));

  const linePath = points
    .map((pt, idx) => `${idx === 0 ? 'M' : 'L'} ${pt.x.toFixed(1)} ${pt.y.toFixed(1)}`)
    .join(' ');

  const areaPath = `${linePath} L ${points[points.length - 1].x.toFixed(1)} ${(padTop + plotH).toFixed(1)} L ${points[0].x.toFixed(1)} ${(padTop + plotH).toFixed(1)} Z`;
  const baselineY = yOf(baseline);
  const latestPoint = points[points.length - 1];
  const activePoint = hoverIdx != null ? points[hoverIdx] : latestPoint;
  const lineColor = latestPoint.value >= baseline ? '#f9757a' : '#4cd9a0';

  const tickIndices = [0, Math.floor((points.length - 1) / 2), points.length - 1]
    .filter((v, i, arr) => arr.indexOf(v) === i);

  return (
    <div className="vix-chart-card">
      <div className="vix-chart-head">
        <div>
          <span className="vix-chart-title">VIX 近 30 日走势</span>
          {source && <span className="vix-chart-source">{source}</span>}
        </div>
        <div className="vix-chart-readout">
          <span className="vix-chart-date">{activePoint.date}</span>
          <strong style={{ color: activePoint.value >= baseline ? 'var(--red)' : 'var(--green)' }}>
            {Number(activePoint.value).toFixed(2)}
          </strong>
        </div>
      </div>

      <svg
        viewBox={`0 0 ${width} ${height}`}
        className="vix-chart-svg"
        role="img"
        aria-label="VIX 近 30 日走势图"
        onMouseLeave={() => setHoverIdx(null)}
      >
        <defs>
          <linearGradient id="vixAreaGrad" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={lineColor} stopOpacity="0.28" />
            <stop offset="100%" stopColor={lineColor} stopOpacity="0.0" />
          </linearGradient>
        </defs>

        {/* 20 恐慌参考线 */}
        <line
          x1={padLeft}
          y1={baselineY}
          x2={width - padRight}
          y2={baselineY}
          stroke="#4b5563"
          strokeDasharray="4 4"
          strokeWidth="1"
        />
        <text x={width - padRight} y={baselineY - 4} textAnchor="end" fill="#7a879e" fontSize="10">
          恐慌线 20
        </text>

        {/* Y 轴上下边界 */}
        <text x={padLeft - 6} y={padTop + 8} textAnchor="end" fill="#6b7280" fontSize="10">
          {maxVal}
        </text>
        <text x={padLeft - 6} y={padTop + plotH} textAnchor="end" fill="#6b7280" fontSize="10">
          {minVal}
        </text>

        <path d={areaPath} fill="url(#vixAreaGrad)" />
        <path d={linePath} fill="none" stroke={lineColor} strokeWidth="2" strokeLinejoin="round" />

        {/* X 轴关键日期 */}
        {tickIndices.map((idx) => (
          <text
            key={idx}
            x={points[idx].x}
            y={height - 6}
            textAnchor={idx === 0 ? 'start' : idx === points.length - 1 ? 'end' : 'middle'}
            fill="#6b7280"
            fontSize="10"
          >
            {points[idx].date.length > 5 ? points[idx].date.slice(5) : points[idx].date}
          </text>
        ))}

        {/* 当前高亮圆点 */}
        <circle
          cx={activePoint.x}
          cy={activePoint.y}
          r="4"
          fill={activePoint.value >= baseline ? '#f9757a' : '#4cd9a0'}
          stroke="#0b0e14"
          strokeWidth="1.5"
        />

        {/* 交互热区 */}
        {points.map((pt, idx) => (
          <rect
            key={pt.date + idx}
            x={pt.x - plotW / Math.max(points.length * 2, 1)}
            y={padTop}
            width={plotW / Math.max(points.length, 1)}
            height={plotH}
            fill="transparent"
            onMouseEnter={() => setHoverIdx(idx)}
          />
        ))}
      </svg>
    </div>
  );
}
