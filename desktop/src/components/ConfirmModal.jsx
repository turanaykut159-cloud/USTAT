/**
 * ÜSTAT v5.2 — Tema uyumlu onay / uyarı modalı.
 * window.confirm / window.alert yerine kullanılır; koyu tema ve uygulama formuna uyumlu.
 */

import React, { useEffect } from 'react';

export default function ConfirmModal({
  open,
  title,
  message,
  confirmLabel = 'Tamam',
  cancelLabel = null,
  variant = 'primary',
  onConfirm,
  onCancel,
}) {
  useEffect(() => {
    if (!open) return;
    const handleKey = (e) => {
      if (e.key === 'Escape') (onCancel || onConfirm)?.();
    };
    window.addEventListener('keydown', handleKey);
    return () => window.removeEventListener('keydown', handleKey);
  }, [open, onCancel, onConfirm]);

  if (!open) return null;

  return (
    <div
      className="confirm-modal-overlay"
      role="dialog"
      aria-modal="true"
      aria-labelledby="confirm-modal-title"
      onClick={(e) => e.target === e.currentTarget && (onCancel || onConfirm)?.()}
    >
      <div className="confirm-modal-card" onClick={(e) => e.stopPropagation()}>
        <h2 id="confirm-modal-title" className="confirm-modal-title">
          {title}
        </h2>
        <p className="confirm-modal-message">{message}</p>
        <div className="confirm-modal-actions">
          {cancelLabel != null && (
            <button
              type="button"
              className="confirm-modal-btn confirm-modal-btn-cancel"
              onClick={onCancel}
            >
              {cancelLabel}
            </button>
          )}
          <button
            type="button"
            className={`confirm-modal-btn confirm-modal-btn-confirm confirm-modal-btn--${variant}`}
            onClick={onConfirm}
            autoFocus
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
