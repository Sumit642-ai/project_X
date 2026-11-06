import { useState } from "react";

import { api, ApiError } from "../../lib/api";
import { languageName } from "../../lib/format";
import type { CallPlan, EncounterOut } from "./types";

interface Props {
  plan: CallPlan;
  onStarted: (encounter: EncounterOut) => void;
}

export function PreCall({ plan, onStarted }: Props) {
  const callable = plan.ladder.filter((e) => e.callable);
  const firstPhone = callable.find((e) => e.channel === "phone");
  const [number, setNumber] = useState(firstPhone?.number ?? "");
  const [interpreter, setInterpreter] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const spoken = plan.proxy_language ?? plan.language;
  const needsInterpreter = Boolean(spoken && spoken !== "en");

  async function dial() {
    setMessage(null);
    try {
      onStarted(
        await api<EncounterOut>("/encounters", {
          method: "POST",
          body: { member_id: plan.member_id, number, channel: "phone", interpreter_booked: interpreter },
        }),
      );
    } catch (e) {
      setMessage(e instanceof ApiError ? e.reason : String(e));
    }
  }

  async function text(to: string) {
    try {
      await api(`/members/${plan.member_id}/sms`, {
        method: "POST",
        body: { number: to, text: "Evergreen Health Plan would like to speak with you. Please call 555-0101." },
      });
      setMessage(`Text sent to ${to} (simulated). No health details were included.`);
    } catch (e) {
      setMessage(e instanceof ApiError ? e.reason : String(e));
    }
  }

  return (
    <section aria-labelledby="pre-title" className="space-y-3 rounded border border-slate-300 bg-white p-3" data-testid="pre-call">
      <h2 id="pre-title" className="text-lg font-semibold">
        Pre-call
      </h2>
      <p className="rounded bg-blue-50 p-2 font-medium text-blue-950" data-testid="call-summary">
        {plan.summary}
      </p>
      <p className="text-sm">
        Language: {languageName(plan.language)}
        {plan.proxy_language ? ` (caregiver speaks ${languageName(plan.proxy_language)})` : ""}
      </p>
      <fieldset>
        <legend className="text-sm font-semibold">Reach ladder</legend>
        <ul className="mt-1 space-y-1">
          {plan.ladder.map((e) => (
            <li key={`${e.number}-${e.channel}`} className={`flex flex-wrap items-center gap-2 text-sm ${e.callable ? "" : "text-slate-600"}`}>
              {e.channel === "phone" ? (
                <label className="flex items-center gap-2">
                  <input type="radio" name="number" value={e.number} checked={number === e.number} disabled={!e.callable} onChange={() => setNumber(e.number)} />
                  Call {e.number}
                </label>
              ) : (
                <button type="button" onClick={() => text(e.number)} className="rounded border border-slate-600 px-2 py-0.5">
                  Text {e.number}
                </button>
              )}
              <span>
                · {e.owner_name ?? e.owner} · confidence {Number(e.confidence).toFixed(2)} · best {e.best_window ?? "UNKNOWN"}
                {!e.callable && " · not callable"}
              </span>
            </li>
          ))}
        </ul>
      </fieldset>
      {needsInterpreter && (
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={interpreter} onChange={(e) => setInterpreter(e.target.checked)} />
          {languageName(spoken)} interpreter booked for this call
        </label>
      )}
      <div className="grid gap-2 text-sm md:grid-cols-3">
        <div className="rounded border border-slate-300 p-2">
          <h3 className="font-semibold">1. Opening</h3>
          <p>{plan.opening_script}</p>
        </div>
        <div className="rounded border border-slate-300 p-2">
          <h3 className="font-semibold">2. Verify identity first</h3>
          <p>{plan.identity_step}</p>
          <p className="text-xs text-slate-700">No health detail until name and date of birth match.</p>
        </div>
        <div className="rounded border border-slate-300 p-2">
          <h3 className="font-semibold">If voicemail</h3>
          <p data-testid="voicemail-script">{plan.voicemail_script}</p>
          <p className="text-xs text-slate-700">No health details in voicemails.</p>
        </div>
      </div>
      <button type="button" onClick={dial} disabled={!number} className="rounded bg-blue-800 px-4 py-2 text-white disabled:opacity-60">
        Dial {number} (simulated)
      </button>
      {message && (
        <p role="status" className="text-sm text-slate-900">
          {message}
        </p>
      )}
    </section>
  );
}
