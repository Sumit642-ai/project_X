import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router";

import { api } from "../../lib/api";
import { useApi } from "../../lib/useApi";
import { Live } from "./Live";
import { PreCall } from "./PreCall";
import type { CallPlan, EncounterOut, Pane } from "./types";
import { WrapUp } from "./WrapUp";

const AUTOSAVE_MS = 10_000;

export function CallPage() {
  const { id = "" } = useParams();
  const navigate = useNavigate();
  const plan = useApi<CallPlan>(`/members/${id}/call-plan`);
  const [encounter, setEncounter] = useState<EncounterOut | null>(null);
  const [pane, setPane] = useState<Pane>("pre");
  const [notes, setNotes] = useState("");
  const [consent, setConsent] = useState(false);
  const [savedAt, setSavedAt] = useState<string | null>(null);
  const latest = useRef({ pane, notes, consent });
  latest.current = { pane, notes, consent };

  // Autosave every 10 s while a call is open, so a dropped call can resume.
  useEffect(() => {
    if (!encounter || encounter.status === "synced") return;
    const timer = window.setInterval(async () => {
      const { pane: p, notes: n, consent: c } = latest.current;
      const result = await api<{ saved_at: string }>(`/encounters/${encounter.id}/autosave`, {
        method: "POST",
        body: { payload: { pane: p, notes: n, transcription_consent: c } },
      }).catch(() => null);
      if (result) setSavedAt(result.saved_at);
    }, AUTOSAVE_MS);
    return () => window.clearInterval(timer);
  }, [encounter]);

  async function resume(encounterId: number) {
    const loaded = await api<EncounterOut>(`/encounters/${encounterId}`);
    setEncounter(loaded);
    setNotes(loaded.autosave?.notes ?? loaded.notes ?? "");
    setConsent(loaded.autosave?.transcription_consent ?? loaded.transcription_consent);
    setPane(loaded.autosave?.pane ?? (loaded.status === "wrapped" ? "wrap" : "live"));
  }

  function started(e: EncounterOut) {
    setEncounter(e);
    setPane(e.outcome === "connected" ? "live" : "wrap");
  }

  if (plan.error) return <p role="status">Call plan unavailable: {plan.error}</p>;
  if (!plan.data) return <p>Loading call plan…</p>;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="text-xl font-semibold">Call · {plan.data.member_name}</h1>
        <Link to={`/members/${id}`} className="text-sm text-blue-900 underline">
          Back to member
        </Link>
        <span className="text-xs text-slate-700" role="status">
          {savedAt ? "Autosaved" : encounter ? "Autosave every 10 s" : ""}
        </span>
      </div>
      <ol className="flex gap-2 text-sm" aria-label="Call steps">
        {(["pre", "live", "wrap"] as const).map((p) => (
          <li key={p} aria-current={pane === p ? "step" : undefined} className={`rounded px-2 py-0.5 ${pane === p ? "bg-blue-800 text-white" : "bg-slate-200 text-slate-900"}`}>
            {{ pre: "Pre-call", live: "Live", wrap: "Wrap-up" }[p]}
          </li>
        ))}
      </ol>
      {!encounter && plan.data.resumable_encounter_id && (
        <div role="status" className="rounded border border-amber-700 bg-amber-50 p-3 text-sm">
          A call with this member was interrupted.{" "}
          <button type="button" onClick={() => resume(plan.data!.resumable_encounter_id!)} className="rounded bg-blue-800 px-2 py-1 text-white">
            Resume call
          </button>
        </div>
      )}
      {pane === "pre" && <PreCall plan={plan.data} onStarted={started} />}
      {pane === "live" && encounter && (
        <Live encounter={encounter} notes={notes} setNotes={setNotes} consent={consent} setConsent={setConsent} onVerified={setEncounter} onWrap={() => setPane("wrap")} />
      )}
      {pane === "wrap" && encounter && encounter.outcome !== "connected" && (
        <section className="rounded border border-slate-300 bg-white p-3 text-sm" data-testid="attempt-pane">
          <p>
            Outcome: <strong>{encounter.outcome}</strong>. {encounter.outcome === "voicemail" ? `Leave this message: “${plan.data.voicemail_script}”` : ""}
          </p>
          <button
            type="button"
            onClick={async () => {
              await api(`/encounters/${encounter.id}/wrap-up`, { method: "POST", body: { notes } });
              navigate(`/members/${id}`);
            }}
            className="mt-2 rounded bg-blue-800 px-3 py-1 text-white"
          >
            Log attempt
          </button>
        </section>
      )}
      {pane === "wrap" && encounter && encounter.outcome === "connected" && (
        <WrapUp encounter={encounter} notes={notes} onChange={setEncounter} onSaved={() => navigate("/queue")} />
      )}
    </div>
  );
}
