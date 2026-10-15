import { useEffect, useRef } from "react";
import type { ReactNode } from "react";
import { AlertCircle, LoaderCircle, ArrowRight } from "lucide-react";
import { ApiError } from "../api/client";
export function Loading() {
  return (
    <div className="loading" role="status">
      <LoaderCircle className="spin" size={22} /> Загружаем вашу кухню…
    </div>
  );
}
export function ErrorBox({
  error,
  onRetry,
}: {
  error: unknown;
  onRetry?: () => void;
}) {
  const e = error instanceof ApiError ? error : null;
  return (
    <div className="error-box" role="alert">
      <AlertCircle size={22} />
      <div>
        <strong>
          {error instanceof Error
            ? error.message
            : "Не удалось выполнить действие."}
        </strong>
        {e?.requestId && <small>ID запроса: {e.requestId}</small>}
        {e?.sourceUrl && (
          <a href={e.sourceUrl} target="_blank" rel="noreferrer">
            Открыть источник
          </a>
        )}
        {onRetry && (
          <button className="text-button" onClick={onRetry}>
            Попробовать снова <ArrowRight size={15} />
          </button>
        )}
      </div>
    </div>
  );
}
export function Empty({
  title,
  children,
}: {
  title: string;
  children?: ReactNode;
}) {
  return (
    <section className="empty-state">
      <h2>{title}</h2>
      <div className="muted">{children}</div>
    </section>
  );
}
export function Modal({
  title,
  children,
  onClose,
}: {
  title: string;
  children: ReactNode;
  onClose: () => void;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const el = ref.current;
    el?.showModal();
    return () => el?.close();
  }, []);
  return (
    <dialog
      ref={ref}
      className="modal"
      aria-labelledby="modal-title"
      onCancel={(e) => {
        e.preventDefault();
        onClose();
      }}
    >
      <h2 id="modal-title">{title}</h2>
      {children}
    </dialog>
  );
}
export function PageTitle({
  title,
  children,
}: {
  title: string;
  children?: ReactNode;
}) {
  return (
    <div className="page-title">
      <div>
        <h1>{title}</h1>
        {children && <div className="muted">{children}</div>}
      </div>
    </div>
  );
}
