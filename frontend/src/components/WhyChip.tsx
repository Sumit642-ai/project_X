export function WhyChip({ text }: { text: string }) {
  return (
    <li className="rounded border border-slate-300 bg-white px-2 py-0.5 text-xs text-slate-800" data-testid="why-chip">
      {text}
    </li>
  );
}

const TIER_STYLES: Record<string, string> = {
  T0: "bg-red-700 text-white",
  T1: "bg-amber-200 text-amber-950",
  T2: "bg-slate-200 text-slate-900",
};
const TIER_WORDS: Record<string, string> = { T0: "act today", T1: "this week", T2: "routine" };

export function TierBadge({ tier }: { tier: string }) {
  return (
    <span className={`inline-block rounded px-2 py-0.5 text-xs font-bold ${TIER_STYLES[tier] ?? ""}`}>
      {tier} <span className="font-normal">· {TIER_WORDS[tier] ?? ""}</span>
    </span>
  );
}
