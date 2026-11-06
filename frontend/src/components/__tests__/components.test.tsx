import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, test, vi } from "vitest";

import { compact, scoreText } from "../../lib/format";
import type { Conflict, Fact, PendingLink } from "../../lib/types";
import { ConflictCard } from "../ConflictCard";
import { DueTime } from "../DueTime";
import { FreshnessBadge } from "../FreshnessBadge";
import { MatchBanner } from "../MatchBanner";
import { UnknownPill } from "../UnknownPill";

describe("FreshnessBadge", () => {
  test.each([
    ["green", "Fresh"],
    ["amber", "Aging"],
    ["red", "Stale"],
    ["grey", "Never received"],
  ] as const)("%s carries the word %s, not colour alone", (freshness, word) => {
    render(<FreshnessBadge freshness={freshness} />);
    expect(screen.getByTestId("freshness-badge")).toHaveTextContent(word);
  });

  test("tooltip names the source and the event date", () => {
    render(<FreshnessBadge freshness="red" sourceSystem="pharmacy_ncpdp" type="medication" eventDate="2026-10-28" />);
    expect(screen.getByRole("tooltip", { hidden: true })).toHaveTextContent("PBM · fill 28 Oct");
    expect(screen.getByTestId("freshness-badge")).toHaveAttribute("tabindex", "0");
  });
});

test("an undated record we hold is not called 'never received'", () => {
  render(<FreshnessBadge freshness="grey" undated />);
  expect(screen.getByTestId("freshness-badge")).toHaveTextContent("Undated");
});

describe("UnknownPill", () => {
  test("shows UNKNOWN with its reason", () => {
    render(<UnknownPill reason="practice not connected" />);
    const pill = screen.getByTestId("unknown-pill");
    expect(pill).toHaveTextContent("UNKNOWN");
    expect(pill).toHaveTextContent("practice not connected");
  });
});

function fact(id: number, source: string, strength: string): Fact {
  return {
    id,
    type: "medication",
    key: "furosemide",
    value: { strength },
    event_date: "2026-11-07",
    loaded_at: "2026-11-09T13:00:00Z",
    source_system: source,
    source_record_id: `R${id}`,
    status: "raw",
    confidence: "1.000",
    freshness: "green",
    masked: false,
  };
}

const conflict: Conflict = {
  label: "flagged by data layer",
  id: 7,
  fact_type: "medication",
  key: "furosemide",
  kind: "dose",
  summary: "furosemide: pharmacy 40 mg vs St Brigid Regional 80 mg",
  status: "open",
  fact_ids: [1, 2],
  detected_at: "2026-11-09T13:00:00Z",
};

describe("ConflictCard", () => {
  test("shows both sources, never a winner, and offers member-report choices", () => {
    const onReport = vi.fn();
    const onSend = vi.fn();
    render(
      <ConflictCard
        conflict={conflict}
        facts={[fact(1, "pharmacy_ncpdp", "40 mg"), fact(2, "ccda", "80 mg")]}
        onMemberReport={onReport}
        onSendToPrescriber={onSend}
      />,
    );
    const card = screen.getByTestId("conflict-card");
    expect(card).toHaveTextContent("flagged by data layer");
    expect(card).toHaveTextContent("PBM: 40 mg");
    expect(card).toHaveTextContent("Hospital document: 80 mg");
    expect(within(card).queryByRole("button", { name: /resolve/i })).toBeNull();

    const choices = within(screen.getByRole("group")).getAllByRole("button").map((b) => b.textContent);
    expect(choices).toEqual(["40 mg", "80 mg", "none on hand", "unsure", "Send to prescriber"]);
    fireEvent.click(screen.getByRole("button", { name: "none on hand" }));
    fireEvent.click(screen.getByRole("button", { name: "Send to prescriber" }));
    expect(onReport).toHaveBeenCalledWith("none on hand");
    expect(onSend).toHaveBeenCalledOnce();
  });

  test("is read-only while an identity match is pending", () => {
    render(
      <ConflictCard
        conflict={conflict}
        facts={[fact(1, "pharmacy_ncpdp", "40 mg")]}
        blockedReason="Confirm or reject the possible duplicate before charting."
        onMemberReport={vi.fn()}
        onSendToPrescriber={vi.fn()}
      />,
    );
    expect(screen.getByText(/possible duplicate before charting/)).toBeInTheDocument();
    for (const button of screen.getAllByRole("button")) expect(button).toBeDisabled();
  });
});

const link: PendingLink = {
  id: 88,
  source_system: "hospital",
  source_record_id: "SYN-001-H",
  confidence: "0.860",
  status: "needs_review",
  label: "flagged by data layer",
};

describe("MatchBanner", () => {
  test("labels the duplicate as flagged by the data layer and asks a person to decide", () => {
    const onConfirm = vi.fn();
    const onReject = vi.fn();
    render(<MatchBanner links={[link]} onConfirm={onConfirm} onReject={onReject} />);
    const banner = screen.getByTestId("match-banner");
    expect(banner).toHaveTextContent("Possible duplicate · flagged by data layer");
    expect(banner).toHaveTextContent("SYN-001-H");
    expect(banner).toHaveTextContent("0.86");
    expect(banner).toHaveTextContent("Charting is paused");
    fireEvent.click(screen.getByRole("button", { name: /confirm/i }));
    fireEvent.click(screen.getByRole("button", { name: /not the same person/i }));
    expect(onConfirm).toHaveBeenCalledWith(88);
    expect(onReject).toHaveBeenCalledWith(88);
  });

  test("renders nothing when there is no pending match", () => {
    const { container } = render(<MatchBanner links={[]} onConfirm={vi.fn()} onReject={vi.fn()} />);
    expect(container).toBeEmptyDOMElement();
  });
});

describe("DueTime and score text", () => {
  test("shows local clock time and turns red under 24 hours", () => {
    const { rerender } = render(<DueTime dueAt="2026-11-10T22:00:00Z" tz="America/New_York" now="2026-11-09T13:00:00Z" />);
    expect(screen.getByTestId("due-time")).toHaveTextContent("Tue 10 Nov, 17:00");
    expect(screen.getByTestId("due-time").className).not.toContain("red");
    rerender(<DueTime dueAt="2026-11-09T22:00:00Z" tz="America/New_York" now="2026-11-09T13:00:00Z" />);
    expect(screen.getByTestId("due-time")).toHaveTextContent("in 9 h");
    expect(screen.getByTestId("due-time").className).toContain("red");
  });

  test("score explanation uses the compact annex style", () => {
    expect(compact("0.880")).toBe(".88");
    expect(compact("1.0000")).toBe("1.0");
    expect(scoreText({ r: "0.880", u: "1.0000", m: "1.000", a: "0.820" }, "93.4")).toBe(
      "Risk .88 x40 + Urgency 1.0 x30 + Fixable 1.0 x20 + Reach .82 x10 = 93.4",
    );
  });
});
