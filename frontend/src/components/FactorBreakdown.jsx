const VALUE_FORMATTERS = {
  cn_us_spread: (v) => `${Math.round(v)} bp`,
  m1_m2_spread: (v) => `${Number(v).toFixed(1)}%`,
  vix: (v) => Number(v).toFixed(2),
  north_money: (v) => `${Number(v).toFixed(1)} 亿`,
  credit_spread: (v) => `${Math.round(v)} bp`,
};

function signalTone(signal, hasValue) {
  if (!hasValue) return 'missing';
  if (signal > 0) return 'bull';
  if (signal < 0) return 'bear';
  return 'neutral';
}

export default function FactorBreakdown({ factorDetails }) {
  const entries = Object.entries(factorDetails || {});
  if (!entries.length) return null;

  return (
    <div className="factor-panel">
      <div className="factor-panel-head">
        <span className="factor-panel-title">5 因子打分拆解</span>
        <span className="factor-panel-sub">每项 -2 ~ +2，缺失因子不稀释权重</span>
      </div>
      <div className="factor-grid">
        {entries.map(([key, item]) => {
          const hasValue = item?.value != null;
          const tone = signalTone(item?.signal ?? 0, hasValue);
          const formatter = VALUE_FORMATTERS[key] || ((v) => String(v));
          const displayVal = hasValue ? formatter(item.value) : '--';
          const sig = item?.signal ?? 0;
          const sigLabel = !hasValue ? '缺' : (sig > 0 ? `+${sig}` : `${sig}`);
          // 将 -2..+2 映射到 0..100% 位置（0 为 50%）
          const pct = hasValue ? ((sig + 2) / 4) * 100 : 50;

          return (
            <div key={key} className={`factor-item tone-${tone}`}>
              <div className="factor-top">
                <span className="factor-name">{item.name_cn || key}</span>
                <span className="factor-weight">权重 {Math.round((item.weight || 0) * 100)}%</span>
              </div>
              <div className="factor-mid">
                <span className="factor-val">{displayVal}</span>
                <span className={`factor-sig sig-${tone}`}>{sigLabel}</span>
              </div>
              <div className="factor-meter" aria-hidden="true">
                <div className="factor-meter-zero" />
                {hasValue && (
                  <div
                    className={`factor-meter-fill fill-${tone}`}
                    style={{
                      left: sig >= 0 ? '50%' : `${pct}%`,
                      width: `${Math.abs(pct - 50)}%`,
                    }}
                  />
                )}
              </div>
              <div className="factor-desc">
                <strong>{item.view || '--'}</strong>
                {item.trend && item.trend !== '缺数据' ? ` · ${item.trend}` : ''}
                {item.narrative ? ` — ${item.narrative}` : ''}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
