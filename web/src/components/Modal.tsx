// Modal reutilisable : overlay + box centree + header + footer.

import type { ReactNode } from "react";

export function Modal({
  title, onClose, children, footer, width = 480,
}: {
  title: string;
  onClose: () => void;
  children: ReactNode;
  footer?: ReactNode;
  width?: number;
}) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-bg_deep/80"
         onClick={onClose}>
      <div className="bg-surface border border-border_hi rounded-md flex flex-col shadow-2xl max-h-[85vh]"
           style={{ width }}
           onClick={(e) => e.stopPropagation()}>
        <div className="px-4 py-3 border-b border-border bg-surface_hi rounded-t-md flex items-center justify-between">
          <span className="font-display text-section text-amb">{title}</span>
          <button type="button" onClick={onClose}
                  className="text-text_med hover:text-text text-lg leading-none">✕</button>
        </div>
        <div className="flex-1 overflow-auto p-4">{children}</div>
        {footer && (
          <div className="px-4 py-3 border-t border-border bg-surface_hi rounded-b-md flex items-center justify-end gap-2">
            {footer}
          </div>
        )}
      </div>
    </div>
  );
}

export function ModalBtn({
  children, onClick, primary, danger, disabled,
}: {
  children: ReactNode;
  onClick: () => void;
  primary?: boolean;
  danger?: boolean;
  disabled?: boolean;
}) {
  const tone = danger
    ? "bg-err_dim text-err border-err/40 hover:bg-err_deep"
    : primary
    ? "bg-mag_dim2 text-amb border-mag/50 hover:bg-mag"
    : "bg-surface_hi text-text border-border_hi hover:bg-mag_dim2";
  return (
    <button type="button" onClick={onClick} disabled={disabled}
            className={`px-4 py-1.5 rounded-sm border font-ui text-control transition disabled:opacity-30 ${tone}`}>
      {children}
    </button>
  );
}
