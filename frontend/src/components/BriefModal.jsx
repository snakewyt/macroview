import { useEffect, useState } from 'react';

export default function BriefModal({ open, content, dateLabel, onClose }) {
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (!open) return undefined;
    const onKey = (e) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [open, onClose]);

  if (!open) return null;

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(content);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      window.prompt('复制以下今日宏观简报：', content);
    }
  };

  const handleDownload = () => {
    const blob = new Blob([content], { type: 'text/markdown;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `macro-brief-${dateLabel || 'today'}.md`;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="brief-backdrop" onClick={onClose} role="dialog" aria-modal="true" aria-label="每日宏观简报预览">
      <div className="brief-modal" onClick={(e) => e.stopPropagation()}>
        <div className="brief-modal-head">
          <h3>📋 每日宏观简报预览</h3>
          <button type="button" className="brief-close" onClick={onClose} aria-label="关闭">✕</button>
        </div>
        <pre className="brief-preview">{content}</pre>
        <div className="brief-modal-actions">
          <button type="button" className="action-btn primary" onClick={handleCopy}>
            {copied ? '已复制到剪贴板 ✓' : '一键复制 Markdown'}
          </button>
          <button type="button" className="action-btn" onClick={handleDownload}>
            下载 .md 文件
          </button>
        </div>
      </div>
    </div>
  );
}
