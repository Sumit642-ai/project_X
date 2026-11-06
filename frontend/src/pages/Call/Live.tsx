import { useState } from "react";

import { ReasonForm } from "../../components/ReasonForm";
import { api, ApiError } from "../../lib/api";
import { AiDraftPanel } from "./AiDraftPanel";
import type { EncounterOut } from "./types";

interface CrisisResult {
  instructions: string[];
  transfer_lines: { name: string; number: string }[];
  supervisor_notified: string[];
}

interface Props {
  encounter: EncounterOut;
  notes: string;
  setNotes: (v: string) => void;
  consent: boolean;
  setConsent: (v: boolean) => void;
  onVerified: (e: EncounterOut) => void;
  onWrap: () => void;
}

export function Live({ encounter, notes, setNotes, consent, setConsent, onVerified, onWrap }: Props) {
  const [crisis, setCrisis] = useState<CrisisResult | null>(null);
  const [flagging, setFlagging] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  async function verify() {
    onVerified(await api<EncounterOut>(`/encounters/${encounter.id}/verify-identity`, { method: "POST" }));
  }

  async function startCrisis() {
    // Act first: instructions come back immediately; documentation waits.
    setCrisis(await api<CrisisResult>(`/encounters/${encounter.id}/crisis`, { method: "POST" }));
  }

  return (
    <section aria-labelledby="live-title" className="space-y-3 rounded border border-slate-300 bg-white p-3" data-testid="live-pane">
      <h2 id="live-title" className="text-lg font-semibold">
        Live call · {encounter.number_used} · {encounter.outcome}
      </h2>
      <button type="button" onClick={startCrisis} className="rounded bg-red-800 px-3 py-2 font-semibold text-white">
        Crisis protocol
      </button>
      {crisis && (
        <div role="status" className="rounded border-2 border-red-800 bg-red-50 p-3 text-red-950" data-testid="crisis-panel">
          <ol className="list-decimal pl-5 text-sm">
            {crisis.instructions.map((i) => (
              <li key={i}>{i}</li>
            ))}
          </ol>
          <p className="mt-1 text-sm">
            Transfer: {crisis.transfer_lines.map((l) => `${l.name} (${l.number})`).join(" or ")}. Supervisor notified:{" "}
            {crisis.supervisor_notified.join(", ")}.
          </p>
        </div>
      )}
      {!encounter.identity_verified ? (
        <div className="rounded border border-amber-700 bg-amber-50 p-3 text-sm">
          <p className="font-semibold">Verify identity before any health detail</p>
          <p>Ask for full name and date of birth and check them against the record.</p>
          <button type="button" onClick={verify} className="mt-2 rounded bg-blue-800 px-3 py-1 text-white">
            Name and date of birth verified
          </button>
        </div>
      ) : (
        <>
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={consent} onChange={(e) => setConsent(e.target.checked)} />
            Member agreed to transcription
          </label>
          <AiDraftPanel
            encounterId={encounter.id}
            consent={consent}
            beforeDraft={() =>
              api(`/encounters/${encounter.id}/autosave`, {
                method: "POST",
                body: { payload: { pane: "live", notes, transcription_consent: consent } },
              })
            }
            onInsert={(text) => setNotes(notes.trim() ? `${notes.trimEnd()}
${text}` : text)}
          />
          <label className="block text-sm font-semibold" htmlFor="call-notes">
            Nurse notes
          </label>
          <textarea id="call-notes" value={notes} onChange={(e) => setNotes(e.target.value)} rows={5} className="w-full rounded border border-slate-500 p-2 text-sm" />
          <div className="flex flex-wrap gap-2">
            <button type="button" onClick={() => setFlagging(true)} className="rounded border border-amber-800 px-3 py-1 text-sm text-amber-950">
              Flag clinical concern
            </button>
            <button type="button" onClick={onWrap} className="rounded bg-blue-800 px-3 py-1 text-sm text-white">
              Go to wrap-up
            </button>
          </div>
          {flagging && (
            <ReasonForm
              title="Clinical concern for the supervisor"
              submitLabel="Flag concern"
              onCancel={() => setFlagging(false)}
              onSubmit={async (note) => {
                try {
                  await api(`/encounters/${encounter.id}/flag-concern`, { method: "POST", body: { note } });
                  setMessage("Concern flagged; supervisor notified.");
                } catch (e) {
                  setMessage(e instanceof ApiError ? e.reason : String(e));
                }
                setFlagging(false);
              }}
            />
          )}
        </>
      )}
      {message && (
        <p role="status" className="text-sm">
          {message}
        </p>
      )}
    </section>
  );
}
