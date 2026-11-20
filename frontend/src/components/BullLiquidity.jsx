import { useState } from 'react';

const STATUS_TEXT = {
  met: '满足',
  partial: '部分满足',
  unmet: '未满足',
  missing: '缺数据',
};

export default function BullLiquidity({ report }) {
  const [mode, setMode] = useState('bull');

  if (!report) {
    return (
      <section className="bull-panel">
        <div className="section-title">A股流动性条件</div>
        <p className="bull-empty">流动性条件还没有取到。确认本机接口已启动。</p>
      </section>
    );
  }

  const view = mode === 'bear' ? report.bear : report;
  const ready = view && (view.conditions || []).length > 0;

  return (
    <section className="bull-panel">
      <div className="bull-head">
        <div className="section-title">
          A股流动性条件
          <span className="section-note">8 条条件，单独计算，不改原来的 5 因子仓位</span>
        </div>
        <div className="bull-switch" role="tablist">
          <button type="button" role="tab" aria-selected={mode === 'bull'} className={mode === 'bull' ? 'active' : ''} onClick={() => setMode('bull')}>牛市条件</button>
          <button type="button" role="tab" aria-selected={mode === 'bear'} className={mode === 'bear' ? 'active' : ''} onClick={() => setMode('bear')}>熊市条件</button>
        </div>
      </div>
      {!ready && (
        <p className="bull-empty">熊市条件还没有算出来。重新拉取流动性数据后会出现。</p>
      )}
      {ready && (
        <>
          <div className="bull-stage">
            <div>
              <div className="bull-kicker">当前阶段</div>
              <div className={`bull-stage-name${mode === 'bear' ? ' bear' : ''}`}>{view.stage || '未计算'}</div>
            </div>
            <div className="bull-stage-detail">
              <div>{view.stage_detail}</div>
              <div className="bull-count">已满足 {view.met_count ?? 0} / 8</div>
            </div>
          </div>
          <div className="bull-list">
            {(view.conditions || []).map((item) => (
              <article key={`${mode}-${item.id}`} className="bull-row">
                <div className={`bull-status status-${item.status}`}>{STATUS_TEXT[item.status] || item.status}</div>
                <div>
                  <div className="bull-name">
                    <span>{item.id}. {item.name}</span>
                    <span className="bull-group">{item.group}</span>
                  </div>
                  <p>{item.detail}</p>
                  <p className="bull-rule">{item.rule}</p>
                </div>
              </article>
            ))}
          </div>
        </>
      )}
      {(report.notes?.sources || []).length > 0 && (
        <ul className="bull-footnote">
          {report.notes.sources.map((item) => <li key={item}>{item}</li>)}
        </ul>
      )}
      {report.notes?.earnings_note && <p className="bull-footnote">{report.notes.earnings_note}</p>}
    </section>
  );
}
