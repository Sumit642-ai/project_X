import { useId } from "react";

/** The score, with its arithmetic on hover or keyboard focus. */
export function ScoreHover({ score, explanation }: { score: string; explanation: string }) {
  const tipId = useId();
  return (
    <span className="group relative inline-flex">
      <button
        type="button"
        aria-describedby={tipId}
        className="rounded px-1 font-mono text-sm font-semibold text-slate-900 underline decoration-dotted underline-offset-2"
        data-testid="score"
      >
        {score}
      </button>
      <span
        id={tipId}
        role="tooltip"
        className="pointer-events-none absolute left-0 top-full z-20 mt-1 hidden whitespace-nowrap rounded bg-slate-900 px-2 py-1 font-mono text-xs text-white group-focus-within:block group-hover:block"
        data-testid="score-explain"
      >
        {explanation}
      </span>
    </span>
  );
}
