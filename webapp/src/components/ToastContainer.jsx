import React from 'react';
import { Info, CheckCircle2, AlertCircle, XCircle } from 'lucide-react';

export function ToastContainer({ toasts }) {
  if (!toasts || toasts.length === 0) return null;

  const iconMap = {
    info: <Info size={18} color="#3b82f6" />,
    success: <CheckCircle2 size={18} color="#10b981" />,
    warning: <AlertCircle size={18} color="#f59e0b" />,
    error: <XCircle size={18} color="#ef4444" />
  };

  return (
    <div className="toast-container" role="region" aria-label="Notifications" aria-live="polite">
      {toasts.map(t => (
        <div key={t.id} className="toast">
          {iconMap[t.type] || iconMap.info}
          {t.msg}
        </div>
      ))}
    </div>
  );
}
