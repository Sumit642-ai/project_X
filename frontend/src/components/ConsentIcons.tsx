import type { Consent } from "../lib/types";

const LABELS: Record<string, string> = {
  tcpa_sms: "SMS",
  part2: "Part 2",
  personal_representative: "Representative",
  third_party_release: "Release",
};

/** Icon + word + validity text for each consent on file. */
export function ConsentIcons({ consents }: { consents: Consent[] }) {
  if (consents.length === 0) {
    return <span className="text-sm text-slate-700">No consents on file · SMS blocked</span>;
  }
  return (
    <ul className="flex flex-wrap gap-2" aria-label="Consents">
      {consents.map((c) => (
        <li
          key={c.id}
          className={`rounded border px-2 py-0.5 text-xs ${c.valid ? "border-emerald-700 bg-emerald-50 text-emerald-900" : "border-red-700 bg-red-50 text-red-900"}`}
        >
          <span aria-hidden="true">{c.valid ? "✓" : "✕"} </span>
          {LABELS[c.type] ?? c.type}
          {c.phone ? ` ${c.phone}` : ""}
          {c.party ? ` · ${c.party}` : ""} · {c.valid ? "valid" : `expired ${c.valid_to ?? ""}`}
        </li>
      ))}
    </ul>
  );
}
