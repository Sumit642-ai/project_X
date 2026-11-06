import { useEffect, useState } from "react";

import { api } from "../../lib/api";
import type { AiDraft, DraftResponse, DraftSentence } from "./types";

const UNAVAILABLE = "AI draft unavailable. Write your notes as normal.";

function turnsLabel(turns: number[]): string {
  if (turns.length === 0) return "no turn cited";
  return `turn${turns.length > 1 ? "s" : ""} ${turns.join(", ")}`;
}

function Sentence({ s }: { s: DraftSentence }) {
  const struck = s.status !== "supported";
  return (
    <li data-testid="draft-sentence" data-status={s.status}>
      {struck ? (
        <>
          <span className="mr-1 rounded bg-red-800 px-1 text-xs font-semibold text-white">
            {s.status === "blocked" ? "BLOCKED" : "UNSUPPORTED"}
          </span>
          <s className="text-slate-600">{s.text}</s>{" "}
          <span className="text-xs text-red-900">({s.reasons.join("; ")})</span>
        </>
      ) : (
        <>
          {s.text} <span className="text-xs text-slate-700">({turnsLabel(s.source_turns)})</span>
        </>
      )}
      {s.flagged_medications.length > 0 && (
        <span className="ml-1 rounded bg-amber-200 px-1 text-xs font-semibold text-amber-950">
          Check medication: {s.flagged_medications.join(", ")}
        </span>
      )}
    </li>
  );
}

export function DraftView({ draft, onInsert }: { draft: AiDraft; onInsert: (text: string) => void }) {
  const summary = draft.sentences.filter((s) => s.section === "summary");
  const note = draft.sentences.filter((s) => s.section === "note");
  return (
    <div className="space-y-2 text-sm" data-testid="ai-draft">
      {draft.flagged_medications.length > 0 && (
        <p role="alert" className="rounded border border-amber-700 bg-amber-50 p-2 text-amber-950">
          Medication names not in the transcript or the member's record: <strong>{draft.flagged_medications.join(", ")}</strong>.
          Check them before using this draft.
        </p>
      )}
      {draft.unsupported_count + draft.blocked_count > 0 && (
        <p className="text-red-900">
          {draft.unsupported_count} unsupported and {draft.blocked_count} blocked sentence(s) are struck through and left out of the
          suggested note.
        </p>
      )}
      <h4 className="font-semibold">Summary</h4>
      <ul className="list-disc space-y-1 pl-5">
        {summary.map((s, i) => (
          <Sentence key={`s${i}`} s={s} />
        ))}
      </ul>
      <h4 className="font-semibold">Suggested note</h4>
      <ul className="list-disc space-y-1 pl-5">
        {note.map((s, i) => (
          <Sentence key={`n${i}`} s={s} />
        ))}
      </ul>
      {draft.open_questions.length > 0 && (
        <>
          <h4 className="font-semibold">Open questions</h4>
          <ul className="list-disc pl-5">
            {draft.open_questions.map((q) => (
              <li key={q}>{q}</li>
            ))}
          </ul>
        </>
      )}
      <details>
        <summary className="cursor-pointer">Transcript ({draft.turns.length} turns) to check citations</summary>
        <ol className="mt-1 space-y-0.5 text-xs">
          {draft.turns.map((t) => (
            <li key={t.number}>
              <strong>
                {t.number}. {t.speaker}:
              </strong>{" "}
              {t.text}
            </li>
          ))}
        </ol>
      </details>
      <button
        type="button"
        disabled={!draft.note_text}
        onClick={() => onInsert(draft.note_text)}
        className="rounded bg-blue-800 px-3 py-1 text-white disabled:bg-slate-500"
      >
        Insert suggested note into my notes
      </button>
      <p className="text-xs text-slate-700">Inserted text goes only into the free-text note. Edit it like anything you type.</p>
    </div>
  );
}

interface Props {
  encounterId: number;
  consent: boolean;
  beforeDraft: () => Promise<unknown>;
  onInsert: (text: string) => void;
}

export function AiDraftPanel({ encounterId, consent, beforeDraft, onInsert }: Props) {
  const [state, setState] = useState<DraftResponse | null>(null);
  const [busy, setBusy] = useState(false);
  const [unavailable, setUnavailable] = useState(false);

  useEffect(() => {
    api<DraftResponse>(`/encounters/${encounterId}/ai-draft`)
      .then(setState)
      .catch(() => setState(null));
  }, [encounterId]);

  if (!state?.enabled) return null;

  async function requestDraft() {
    setBusy(true);
    setUnavailable(false);
    try {
      await beforeDraft(); // the server checks transcription consent, so save it first
      const result = await api<DraftResponse>(`/encounters/${encounterId}/ai-draft`, { method: "POST" });
      setState(result);
      setUnavailable(!result.available);
    } catch {
      setUnavailable(true);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section aria-labelledby="ai-draft-title" className="space-y-2 rounded border border-slate-400 bg-slate-50 p-3" data-testid="ai-draft-panel">
      <h3 id="ai-draft-title" className="font-semibold">
        AI note draft (suggested)
      </h3>
      <p className="text-xs text-slate-700">
        Drafted from the call transcript. It can only fill your free-text note; it never changes medications, allergies, doses or
        assessment answers. Check every line.
      </p>
      <button
        type="button"
        onClick={requestDraft}
        disabled={!consent || busy}
        className="rounded border border-blue-800 px-3 py-1 text-sm text-blue-900 disabled:border-slate-400 disabled:text-slate-600"
      >
        {busy ? "Drafting…" : state.draft ? "Redraft from transcript" : "Draft note from transcript"}
      </button>
      {!consent && <p className="text-xs">Needs the member's agreement to transcription.</p>}
      {unavailable && (
        <p role="status" className="text-sm font-semibold" data-testid="ai-draft-unavailable">
          {UNAVAILABLE}
        </p>
      )}
      {state.draft && !unavailable && <DraftView draft={state.draft} onInsert={onInsert} />}
    </section>
  );
}
