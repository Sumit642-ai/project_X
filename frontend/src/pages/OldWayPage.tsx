import { useState } from "react";
import { Link } from "react-router";

import { useDemoConfig } from "../lib/demo";

// A static mock of the seven portals a nurse opens today to piece Raymond together.
// Synthetic data only; the systems are invented and deliberately inconsistent.
interface Portal {
  name: string;
  url: string;
  style: string;
  login: string;
  rows: [string, string][];
  note: string;
}

const PORTALS: Portal[] = [
  {
    name: "Eligibility",
    url: "elig.plan-intranet.example/member?id=SYN-001",
    style: "bg-[#eef2e6] font-mono",
    login: "Session expires in 4 min",
    rows: [
      ["Member", "TULL, RAYMOND  (SYN-001)"],
      ["Plan", "MA-PPO · eff 01/01/2019"],
      ["Phone", "555-0177 (home) · updated 02/2023"],
      ["Address", "12 Larch St · updated 02/2023"],
      ["Representative", "Joan Tull (wife) · form on file"],
    ],
    note: "The landline was last verified in 2023. It went unanswered twice in October.",
  },
  {
    name: "PBM pharmacy",
    url: "pbm-portal.example/claims/search",
    style: "bg-[#fff8e1]",
    login: "Logged in as CM_GENERIC_07",
    rows: [
      ["09/30/2026", "FUROSEMIDE 40MG TAB · 30 DS · PAID"],
      ["10/15/2026", "METOPROLOL SUCC 50MG · 30 DS · PAID"],
      ["11/07/2026", "SACUBITRIL/VALSARTAN 24/26 · REJECTED 75 PA REQUIRED"],
      ["Profile phone", "555-0142 (as of 10/28/2026)"],
    ],
    note: "The 40 mg supply ran out on 30 Oct. Nothing shows the new 80 mg dose.",
  },
  {
    name: "HIE viewer",
    url: "hie.region.example/patient/8841207",
    style: "bg-[#e8f0fb]",
    login: "Patient match: TULL, RAYMOND J · 0.86",
    rows: [
      ["ADT A03", "Discharged 11/07/2026 14:10 · St Brigid Regional"],
      ["Med list", "Furosemide 80 mg daily; sacubitril/valsartan new; metoprolol succinate 50 mg"],
      ["Discharge summary", "Requested 11/07 · not received"],
      ["Record", "SYN-001-H (hospital-created; not linked)"],
    ],
    note: "This hospital record is a separate shell, a different person to every other system.",
  },
  {
    name: "Claims warehouse",
    url: "dw-reports.example/claims?member=SYN-001",
    style: "bg-[#f3f3f3] font-mono text-xs",
    login: "Report generated nightly",
    rows: [
      ["Data through", "2026-09-25"],
      ["Diagnoses", "I50.22 HFrEF · N18.31 CKD 3a · I10 HTN"],
      ["Last inpatient", "none in window"],
    ],
    note: "The data is 45 days old, so this week's admission is not here.",
  },
  {
    name: "UM portal",
    url: "um.plan-intranet.example/requests",
    style: "bg-[#fbeff2]",
    login: "Search by auth number only",
    rows: [
      ["Requests for SYN-001", "none found"],
      ["Tip", "Requests filed by fax may take 2 business days to appear"],
    ],
    note: "No coverage request has been filed for the rejected heart medication.",
  },
  {
    name: "Legacy CM system",
    url: "cm-legacy.example/case/SYN-001/notes",
    style: "bg-[#f0ecf9]",
    login: "Assigned: Maria",
    rows: [
      ["06/2026 note", "Wife Joan manages pills. Prefers evening calls (555-0143)."],
      ["HRA", "Completed 02/2026"],
      ["Open tasks", "none"],
    ],
    note: "The free-text note is the only place Joan's number and the best time to call are recorded.",
  },
  {
    name: "Fax inbox",
    url: "efax.example/inbox?queue=transitions",
    style: "bg-[#fafafa]",
    login: "37 unread",
    rows: [
      ["11/08 07:12", "St Brigid · 'TULL R' · discharge med rec (page 1 of 3)"],
      ["11/08 07:13", "St Brigid · page 3 of 3"],
      ["", "(page 2 missing)"],
    ],
    note: "Page 2 is missing: the fax with the dose change never arrived in full.",
  },
];

export function OldWayPage() {
  const config = useDemoConfig();
  const [active, setActive] = useState(0);
  if (config.data && !config.data.demo_mode) return <p className="p-8">This page is part of demo mode only.</p>;
  const portal = PORTALS[active];
  return (
    <main id="main" className="min-h-screen bg-slate-200 p-4 text-slate-900" data-testid="old-way">
      <h1 className="text-xl font-semibold">Before CaseCompass: Raymond Tull, seven tabs</h1>
      <p className="mb-3 text-sm text-slate-800">
        Static mock, synthetic data. A nurse opens seven systems to piece one member together. Nothing connects them, and every system holds a
        different piece.
      </p>
      <div role="tablist" aria-label="Portals" className="flex flex-wrap gap-1">
        {PORTALS.map((p, i) => (
          <button
            key={p.name}
            role="tab"
            type="button"
            aria-selected={i === active}
            onClick={() => setActive(i)}
            className={`rounded-t border border-b-0 border-slate-500 px-3 py-1 text-sm ${i === active ? "bg-white font-semibold" : "bg-slate-300"}`}
          >
            {i + 1}. {p.name}
          </button>
        ))}
      </div>
      <section role="tabpanel" aria-label={portal.name} className={`border border-slate-500 p-4 ${portal.style}`}>
        <p className="mb-2 rounded bg-white/70 px-2 py-1 font-mono text-xs text-slate-800">https://{portal.url}</p>
        <p className="mb-2 text-xs text-slate-800">{portal.login}</p>
        <table className="text-sm">
          <tbody>
            {portal.rows.map(([k, v], i) => (
              <tr key={i}>
                <th className="pr-4 text-left align-top font-semibold">{k}</th>
                <td>{v}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className="mt-3 rounded border border-amber-700 bg-amber-50 p-2 text-sm text-amber-950">{portal.note}</p>
      </section>
      <p className="mt-4 text-sm">
        Furosemide is 40 mg in one place and 80 mg in another. There are two records for the same man, and no coverage request.{" "}
        <Link to="/login" className="font-semibold text-blue-900 underline">
          Now the same member in CaseCompass →
        </Link>
      </p>
    </main>
  );
}
