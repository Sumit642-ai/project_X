import { useState } from "react";
import { Link, useParams } from "react-router";

import { ConflictCard } from "../components/ConflictCard";
import { ConsentIcons } from "../components/ConsentIcons";
import { FreshnessBadge } from "../components/FreshnessBadge";
import { MatchBanner } from "../components/MatchBanner";
import { ProvenanceChip, ProvenanceDrawer } from "../components/Provenance";
import { ReasonForm } from "../components/ReasonForm";
import { UnknownPill } from "../components/UnknownPill";
import { api, ApiError } from "../lib/api";
import { daysBetween, describeFact, languageName, longDate, shortDate } from "../lib/format";
import { isUnknown, type Fact, type Member360, type Part2Reveal } from "../lib/types";
import { useApi } from "../lib/useApi";

const MATCH_BLOCK = "Confirm or reject the possible duplicate before charting.";
const TABS = ["Timeline", "Care plan", "SDOH", "Documents", "Risk"] as const;
type Tab = (typeof TABS)[number];

function FactLine({ fact, onOpen }: { fact: Fact; onOpen: (f: Fact) => void }) {
  return (
    <li className="flex flex-wrap items-center gap-2 border-b border-slate-100 py-1 text-sm">
      <FreshnessBadge freshness={fact.freshness} sourceSystem={fact.source_system} type={fact.type} eventDate={fact.event_date} value={fact.value} undated={!fact.event_date} />
      <span className="text-slate-700">{fact.event_date ? shortDate(fact.event_date) : "no date"}</span>
      <span className="text-slate-900">{describeFact(fact)}</span>
      <ProvenanceChip fact={fact} onOpen={onOpen} />
    </li>
  );
}

function Part2Panel({ data, onError }: { data: Member360; onError: (m: string) => void }) {
  const notes = data.facts.filter((f) => f.key === "part2:counselling_note");
  const consent = data.consents.find((c) => c.type === "part2" && c.valid);
  const [asking, setAsking] = useState(false);
  const [revealed, setRevealed] = useState<Part2Reveal | null>(null);
  const [error, setError] = useState<string | null>(null);
  if (notes.length === 0) return null;

  async function reveal(reason: string) {
    try {
      setRevealed(await api<Part2Reveal>(`/members/${data.member.member_id}/part2/reveal`, { method: "POST", body: { reason } }));
      setAsking(false);
    } catch (e) {
      const text = e instanceof ApiError ? e.reason : String(e);
      setError(text);
      onError(text);
    }
  }

  return (
    <section aria-labelledby="part2-title" className="rounded border border-slate-400 bg-white p-3" data-testid="part2-panel">
      <h2 id="part2-title" className="flex items-center gap-2 font-semibold">
        <span aria-hidden="true">🔒</span> Records restricted
      </h2>
      <p className="text-sm text-slate-800">
        {notes.length} record(s) from a 42 CFR Part 2 program are masked. Revealing needs valid consent and is audited.
      </p>
      {!revealed && consent && !asking && (
        <button type="button" onClick={() => setAsking(true)} className="mt-2 rounded bg-blue-800 px-2 py-1 text-sm text-white">
          Reveal restricted records
        </button>
      )}
      {!consent && <p className="mt-2 text-sm text-red-800">No valid Part 2 consent on file: records cannot be revealed.</p>}
      {asking && (
        <ReasonForm title="Why do you need these records?" submitLabel="Reveal (audited)" error={error} onCancel={() => setAsking(false)} onSubmit={reveal} />
      )}
      {revealed && (
        <div className="mt-2" data-testid="part2-notes">
          <p className="rounded border border-red-700 bg-red-50 p-2 text-xs text-red-950">{revealed.redisclosure_notice}</p>
          <ul className="mt-2 space-y-2">
            {revealed.notes.map((n) => (
              <li key={n.fact_id} className="text-sm">
                <strong>{longDate(n.service_date)}</strong> · {n.program} · {n.counselor}
                <p>{n.note_text}</p>
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}

function TabPanel({ tab, data, onOpen, onRequery }: { tab: Tab; data: Member360; onOpen: (f: Fact) => void; onRequery: (id: number) => void }) {
  const sorted = [...data.facts].sort((a, b) => (b.event_date ?? "").localeCompare(a.event_date ?? ""));
  if (tab === "Timeline") {
    return (
      <>
        <p className="text-sm text-slate-800" data-testid="claims-as-of">
          Claims as of {longDate(data.claims_as_of)}: later visits may appear only in ADT.
        </p>
        <ul className="mt-2">{sorted.filter((f) => !f.masked).map((f) => <FactLine key={f.id} fact={f} onOpen={onOpen} />)}</ul>
      </>
    );
  }
  if (tab === "Care plan") return <UnknownPill reason="no care plan recorded yet" />;
  if (tab === "SDOH") {
    const screens = sorted.filter((f) => f.type === "sdoh");
    if (screens.length === 0) return <UnknownPill reason="no SDOH screens on file" />;
    return (
      <ul className="space-y-2">
        {screens.map((f) => {
          const age = f.event_date ? daysBetween(f.event_date, data.now) : null;
          return (
            <li key={f.id} className="flex flex-wrap items-center gap-2 text-sm">
              <FreshnessBadge freshness={f.freshness} sourceSystem={f.source_system} type={f.type} eventDate={f.event_date} />
              <span>{describeFact(f)}</span>
              <span className="rounded border border-slate-500 px-1 text-xs">{age === null ? "age UNKNOWN" : `${age} days old`}</span>
              {age !== null && age > 180 && <span className="font-medium text-amber-900">Re-screen on the next call</span>}
            </li>
          );
        })}
      </ul>
    );
  }
  if (tab === "Documents") {
    if (data.documents.length === 0) return <UnknownPill reason="no documents requested or received" />;
    return (
      <ul className="space-y-2">
        {data.documents.map((d) => (
          <li key={d.id} className="flex flex-wrap items-center gap-2 text-sm" data-testid="document-row">
            <strong>{d.type.replace(/_/g, " ")}</strong> · {d.facility ?? "UNKNOWN facility"} ·{" "}
            <span className={d.status === "received" ? "text-emerald-900" : "text-amber-900"}>{d.status}</span>
            {d.requested_at && <span>requested {shortDate(d.requested_at)}</span>}
            {d.status !== "received" && (
              <button type="button" onClick={() => onRequery(d.id)} className="rounded border border-slate-600 px-2 py-0.5">
                Re-query
              </button>
            )}
          </li>
        ))}
      </ul>
    );
  }
  const risk = data.risk;
  return (
    <dl className="grid max-w-md grid-cols-2 gap-1 text-sm">
      <dt className="font-medium">Risk score</dt>
      <dd>{isUnknown(risk.value) ? <UnknownPill reason={risk.value.reason} /> : risk.value}</dd>
      <dt className="font-medium">Basis</dt>
      <dd>{risk.basis === "plan" ? "Plan risk model" : "Cohort median (VERIFY)"}</dd>
      <dt className="font-medium">Model</dt>
      <dd>{risk.model ?? "UNKNOWN"}</dd>
      <dt className="font-medium">Scored</dt>
      <dd>{longDate(risk.scored_at)}</dd>
    </dl>
  );
}

/** Shown while the ADT feed is late or paused: the nurse records a discharge she learned of. */
function AddDischarge({ onSave, busy }: { onSave: (facility: string, at: string) => void; busy: boolean }) {
  const [open, setOpen] = useState(false);
  const [facility, setFacility] = useState("");
  const [at, setAt] = useState("");
  return (
    <div role="alert" className="rounded border border-red-800 bg-red-50 p-2 text-sm text-red-950" data-testid="adt-down">
      <strong>ADT feed is down:</strong> admissions and discharges may be missing from this record.{" "}
      {!open ? (
        <button type="button" onClick={() => setOpen(true)} className="ml-1 rounded bg-red-800 px-2 py-0.5 text-white">
          Add discharge
        </button>
      ) : (
        <form
          className="mt-2 flex flex-wrap items-end gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            onSave(facility, `${at}:00-05:00`);
            setOpen(false);
          }}
        >
          <label className="flex flex-col">
            Facility
            <input required value={facility} onChange={(e) => setFacility(e.target.value)} className="rounded border border-slate-600 px-1" />
          </label>
          <label className="flex flex-col">
            Discharged at (Eastern)
            <input required type="datetime-local" value={at} onChange={(e) => setAt(e.target.value)} className="rounded border border-slate-600 px-1" />
          </label>
          <button type="submit" disabled={busy} className="rounded bg-red-800 px-2 py-1 text-white">
            Save discharge (member reported)
          </button>
        </form>
      )}
    </div>
  );
}

export function Member360Page() {
  const { id = "" } = useParams();
  const view = useApi<Member360>(`/members/${id}/360`);
  const explain = useApi<{ explanation: string }>(`/members/${id}/score/explain`);
  const [drawer, setDrawer] = useState<Fact | null>(null);
  const [tab, setTab] = useState<Tab>("Timeline");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [notNow, setNotNow] = useState(false);
  const [showAll, setShowAll] = useState(false);

  if (view.error) return <p role="status">Member view unavailable: {view.error}</p>;
  if (!view.data) return <p>Loading member…</p>;
  const data = view.data;
  const blocked = data.pending_links.length > 0 ? MATCH_BLOCK : null;
  const nba = data.since_last_contact.signals[0] ?? null;
  const facts = new Map(data.facts.map((f) => [f.id, f]));
  const pcp = data.care_team.find((m) => m.role === "PCP");
  const since = data.since_last_contact.facts.filter((f) => !f.masked);
  const sinceShown = showAll ? since : since.slice(0, 8);

  async function act(path: string, body?: unknown, done?: string) {
    setBusy(true);
    try {
      await api(path, { method: "POST", body });
      if (done) setNotice(done);
      view.reload();
      explain.reload();
    } catch (e) {
      setNotice(e instanceof ApiError ? e.reason : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-4">
      <header className="space-y-2 rounded border border-slate-300 bg-white p-3">
        <h1 className="text-xl font-semibold">
          {data.member.name} <span className="text-base font-normal text-slate-700">{data.member.member_id}</span>
        </h1>
        <p className="text-sm text-slate-800">
          {data.member.age} y · DOB {longDate(data.member.dob)} · {data.member.plan ?? "UNKNOWN plan"} {data.member.lob ?? ""} · Language{" "}
          {languageName(data.member.language)}
          {data.member.proxy_language ? ` (caregiver: ${languageName(data.member.proxy_language)})` : ""} · PCP{" "}
          {pcp && isUnknown(pcp.name) ? <UnknownPill reason={pcp.name.reason} /> : String(pcp?.name ?? "UNKNOWN")}
          {explain.data && <span> · Score {explain.data.explanation}</span>}
        </p>
        <ConsentIcons consents={data.consents} />
        <MatchBanner
          links={data.pending_links}
          busy={busy}
          onConfirm={(linkId) => act(`/members/${id}/links/${linkId}/confirm`, undefined, "Match confirmed: hospital records now appear in this member's record.")}
          onReject={(linkId) => act(`/members/${id}/links/${linkId}/reject`, undefined, "Match rejected: it will not be suggested again.")}
        />
        {data.adt_feed_stale && (
          <AddDischarge
            busy={busy}
            onSave={(facility, at) =>
              act(`/members/${id}/discharges`, { facility, discharge_at: at }, "Discharge recorded as member reported; signals re-checked.")
            }
          />
        )}
        {notice && (
          <p role="status" className="text-sm text-slate-900">
            {notice}
          </p>
        )}
      </header>

      <div className="grid gap-4 lg:grid-cols-3">
        <section aria-labelledby="since-title" className="rounded border border-slate-300 bg-white p-3 lg:col-span-2">
          <h2 id="since-title" className="font-semibold">
            Since last contact
          </h2>
          <p className="text-xs text-slate-700">{data.since_last_contact.reference}</p>
          <ul className="mt-1">{sinceShown.map((f) => <FactLine key={f.id} fact={f} onOpen={setDrawer} />)}</ul>
          {since.length > 8 && (
            <button type="button" onClick={() => setShowAll(!showAll)} className="mt-1 text-sm text-blue-900 underline">
              {showAll ? "Show fewer" : `Show all ${since.length}`}
            </button>
          )}
          <h3 className="mt-3 text-sm font-semibold">Last call note</h3>
          <UnknownPill reason={data.last_call_note.reason} />
          <h3 className="mt-2 text-sm font-semibold">Member goal</h3>
          <UnknownPill reason={data.member_goal.reason} />
        </section>

        <section aria-labelledby="nba-title" className="rounded border-2 border-blue-800 bg-white p-3" data-testid="nba-card">
          <h2 id="nba-title" className="font-semibold">
            Next best action (suggested)
          </h2>
          {nba ? (
            <>
              <p className="mt-1">{nba.suggested_step}</p>
              <p className="mt-1 text-sm text-slate-800">Reason: {nba.insight_text}</p>
              <p className="mt-1 inline-block rounded bg-slate-100 px-1.5 text-xs text-slate-800">Drafted wording · rule template</p>
            </>
          ) : (
            <p className="mt-1 text-sm">No open suggestion.</p>
          )}
          <div className="mt-3 flex gap-2">
            {blocked ? (
              <button type="button" disabled aria-describedby="start-call-note" className="rounded bg-blue-800 px-3 py-1 text-white opacity-60">
                Start call
              </button>
            ) : (
              <Link to={`/members/${id}/call`} className="rounded bg-blue-800 px-3 py-1 text-white">
                Start call
              </Link>
            )}
            <button type="button" disabled={Boolean(blocked) || !nba} onClick={() => setNotNow(true)} className="rounded border border-slate-600 px-3 py-1 disabled:opacity-60">
              Not now
            </button>
          </div>
          <p id="start-call-note" className="mt-1 text-xs text-slate-700">
            {blocked ?? "Opens the simulated call: pre-call, live, wrap-up."}
          </p>
          {notNow && nba && (
            <ReasonForm
              title="Not now"
              submitLabel="Record"
              onCancel={() => setNotNow(false)}
              onSubmit={async (reason) => {
                setNotNow(false);
                await act(`/members/${id}/not-now`, { reason, rule_id: nba.rule_id }, "Recorded: suggestion deferred.");
              }}
            />
          )}
        </section>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <section aria-labelledby="conflicts-title" className="space-y-2">
          <h2 id="conflicts-title" className="font-semibold">
            Conflicts
          </h2>
          {data.conflicts.length === 0 && <p className="text-sm text-slate-800">No conflicts flagged by the data layer.</p>}
          {data.conflicts.map((c) => (
            <ConflictCard
              key={c.id}
              conflict={c}
              facts={c.fact_ids.map((fid) => facts.get(fid)).filter((f): f is Fact => Boolean(f))}
              blockedReason={blocked}
              busy={busy}
              onMemberReport={(value) => act(`/conflicts/${c.id}/member-reports`, { value: `Member reports: ${value}` }, `Recorded member report: ${value}. Conflict stays open.`)}
              onSendToPrescriber={() => act(`/conflicts/${c.id}/send-to-prescriber`, undefined, "Sent to prescriber.")}
            />
          ))}
        </section>
        <section aria-labelledby="reach-title" className="rounded border border-slate-300 bg-white p-3">
          <h2 id="reach-title" className="font-semibold">
            Reach ladder
          </h2>
          <ol className="mt-1 space-y-1" data-testid="reach-ladder">
            {data.contacts.map((c) => (
              <li key={c.number} className={`text-sm ${c.callable ? "text-slate-900" : "text-slate-600"}`} data-callable={c.callable}>
                <strong>{c.number}</strong> · {c.owner_name ?? c.owner} ({c.owner}) · confidence {Number(c.confidence).toFixed(2)} · best{" "}
                {c.best_window ?? "UNKNOWN"} · {c.authorised ? "authorised" : "not authorised"}
                {c.consent_sms ? " · SMS consent" : " · no SMS consent"}
                {!c.callable && <span className="font-medium"> · not callable ({c.not_callable_reason})</span>}
              </li>
            ))}
          </ol>
        </section>
      </div>

      <p className="text-sm text-slate-800" data-testid="care-team">
        <strong>Care team:</strong>{" "}
        {data.care_team.map((m) => `${m.role}: ${isUnknown(m.name) ? "UNKNOWN" : m.name}${m.detail ? ` (${m.detail})` : ""}`).join(" · ")}
      </p>

      <Part2Panel data={data} onError={setNotice} />

      <section aria-label="Details" className="rounded border border-slate-300 bg-white p-3">
        <div role="tablist" aria-label="Member details" className="flex gap-1 border-b border-slate-300">
          {TABS.map((t) => (
            <button
              key={t}
              type="button"
              role="tab"
              id={`tab-${t}`}
              aria-selected={tab === t}
              aria-controls={`panel-${t}`}
              tabIndex={tab === t ? 0 : -1}
              onClick={() => setTab(t)}
              onKeyDown={(e) => {
                const i = TABS.indexOf(t);
                if (e.key === "ArrowRight") setTab(TABS[(i + 1) % TABS.length]);
                if (e.key === "ArrowLeft") setTab(TABS[(i + TABS.length - 1) % TABS.length]);
              }}
              className={`rounded-t px-3 py-1 text-sm ${tab === t ? "bg-blue-800 text-white" : "text-slate-900"}`}
            >
              {t}
            </button>
          ))}
        </div>
        <div role="tabpanel" id={`panel-${tab}`} aria-labelledby={`tab-${tab}`} className="pt-3">
          <TabPanel tab={tab} data={data} onOpen={setDrawer} onRequery={(docId) => act(`/documents/${docId}/requery`, undefined, "Re-query sent to the HIE.")} />
        </div>
      </section>

      <ProvenanceDrawer fact={drawer} onClose={() => setDrawer(null)} />
    </div>
  );
}
