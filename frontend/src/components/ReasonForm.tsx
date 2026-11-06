import { useEffect, useId, useRef, useState, type FormEvent } from "react";

interface Props {
  title: string;
  submitLabel: string;
  onSubmit: (reason: string, date?: string) => Promise<void> | void;
  onCancel: () => void;
  withDate?: { label: string; min: string; max: string };
  error?: string | null;
}

/** Inline (non-pop-up) form that requires a reason, optionally a date. */
export function ReasonForm({ title, submitLabel, onSubmit, onCancel, withDate, error }: Props) {
  const [reason, setReason] = useState("");
  const [date, setDate] = useState(withDate?.min ?? "");
  const id = useId();
  const firstRef = useRef<HTMLTextAreaElement>(null);
  useEffect(() => firstRef.current?.focus(), []);
  const valid = reason.trim().length >= 5 && (!withDate || Boolean(date));

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (valid) await onSubmit(reason.trim(), withDate ? date : undefined);
  }

  return (
    <form
      role="dialog"
      aria-labelledby={`${id}-title`}
      onSubmit={submit}
      onKeyDown={(e) => e.key === "Escape" && onCancel()}
      className="mt-2 rounded border border-slate-400 bg-slate-50 p-3"
    >
      <h3 id={`${id}-title`} className="text-sm font-semibold">
        {title}
      </h3>
      <label htmlFor={`${id}-reason`} className="mt-1 block text-sm text-slate-800">
        Reason (required, at least 5 characters)
      </label>
      <textarea
        id={`${id}-reason`}
        ref={firstRef}
        value={reason}
        onChange={(e) => setReason(e.target.value)}
        rows={2}
        className="mt-1 w-full rounded border border-slate-500 p-1 text-sm"
      />
      {withDate && (
        <>
          <label htmlFor={`${id}-date`} className="mt-1 block text-sm text-slate-800">
            {withDate.label}
          </label>
          <input
            id={`${id}-date`}
            type="date"
            min={withDate.min}
            max={withDate.max}
            value={date}
            onChange={(e) => setDate(e.target.value)}
            className="mt-1 rounded border border-slate-500 p-1 text-sm"
          />
        </>
      )}
      {error && (
        <p role="status" className="mt-1 text-sm text-red-800">
          {error}
        </p>
      )}
      <div className="mt-2 flex gap-2">
        <button type="submit" disabled={!valid} className="rounded bg-blue-800 px-2 py-1 text-sm text-white disabled:opacity-60">
          {submitLabel}
        </button>
        <button type="button" onClick={onCancel} className="rounded border border-slate-600 px-2 py-1 text-sm">
          Cancel
        </button>
      </div>
    </form>
  );
}
