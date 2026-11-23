const REGION_LABEL = {
  CN: '中国',
  US: '美国',
  JP: '日本',
  EU: '欧元区',
};

function countdownText(days) {
  if (days === 0) return '今天';
  if (days === 1) return '明天';
  return `${days} 天后`;
}

export default function MacroCalendar({ events = [] }) {
  return (
    <section id="sec-events" className="calendar-panel">
      <div className="section-title">
        📅 七、宏观事件日历
        <span className="section-note">— 未来 30 天全球央行议息会议（FOMC / ECB / BOJ）与中美核心数据窗口</span>
      </div>
      {!events.length ? (
        <p className="bull-empty">近期暂无宏观事件。</p>
      ) : (
        <div className="calendar-list">
          {events.map((ev, idx) => {
            const isRate = ev.category === 'rate';
            return (
              <div
                key={`${ev.date}-${ev.title}-${idx}`}
                className={`calendar-row${isRate ? ' is-rate' : ''}`}
              >
                <div className="calendar-date-col">
                  <span className="calendar-date">{ev.date}</span>
                  <span className={`calendar-countdown${ev.days_away <= 3 ? ' soon' : ''}`}>
                    {countdownText(ev.days_away)}
                  </span>
                </div>
                <div className="calendar-body">
                  <div className="calendar-title-row">
                    <span className={`region-pill region-${(ev.region || 'CN').toLowerCase()}`}>
                      {REGION_LABEL[ev.region] || ev.region}
                    </span>
                    {isRate && <span className="rate-pill">议息会议</span>}
                    <span className="calendar-title">{ev.title}</span>
                    <span className={`impact-pill impact-${ev.impact === '高' ? 'high' : 'med'}`}>
                      {ev.impact}影响
                    </span>
                  </div>
                  <div className="calendar-note">{ev.note}</div>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </section>
  );
}
