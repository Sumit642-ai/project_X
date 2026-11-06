import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";

import { AiDraftPanel, DraftView } from "./AiDraftPanel";
import type { AiDraft } from "./types";

afterEach(() => vi.unstubAllGlobals());

const DRAFT: AiDraft = {
  id: 1,
  sentences: [
    { section: "summary", text: "Weight up 2 lb.", source_turns: [8], status: "supported", reasons: [], flagged_medications: [] },
    {
      section: "summary",
      text: "Member is doing well overall.",
      source_turns: [],
      status: "unsupported",
      reasons: ["cites no transcript turn"],
      flagged_medications: [],
    },
    {
      section: "note",
      text: "Furosemide: no supply at home.",
      source_turns: [10, 13],
      status: "supported",
      reasons: [],
      flagged_medications: [],
    },
    {
      section: "note",
      text: "He should take torsemide 40 mg.",
      source_turns: [9],
      status: "blocked",
      reasons: ["dose recommendation"],
      flagged_medications: ["torsemide"],
    },
  ],
  open_questions: ["Which heart medication is 'the metro-something'?"],
  flagged_medications: ["torsemide"],
  unsupported_count: 1,
  blocked_count: 1,
  note_text: "Furosemide: no supply at home.",
  turns: [{ number: 8, speaker: "CAREGIVER", text: "So he's up 2 pounds." }],
};

test("unsupported and blocked sentences are struck through; invented medications are flagged", () => {
  const onInsert = vi.fn();
  render(<DraftView draft={DRAFT} onInsert={onInsert} />);

  const [supported, unsupported, , blocked] = screen.getAllByTestId("draft-sentence");
  expect(supported).toHaveTextContent("Weight up 2 lb. (turn 8)");
  expect(supported.querySelector("s")).toBeNull();
  expect(unsupported).toHaveTextContent("UNSUPPORTED");
  expect(within(unsupported).getByText("Member is doing well overall.").tagName).toBe("S");
  expect(blocked).toHaveTextContent("BLOCKED");
  expect(blocked).toHaveTextContent("Check medication: torsemide");
  expect(screen.getByRole("alert")).toHaveTextContent("torsemide");

  fireEvent.click(screen.getByRole("button", { name: "Insert suggested note into my notes" }));
  expect(onInsert).toHaveBeenCalledWith("Furosemide: no supply at home.");
});

function stubApi(post: () => Promise<Response>) {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockImplementation((url: string, init: RequestInit) => {
      if (url.endsWith("/ai-draft") && init.method === "POST") return post();
      const body = url.endsWith("/ai-draft") ? { enabled: true, available: false, reason: null, draft: null } : {};
      return Promise.resolve(new Response(JSON.stringify(body), { status: 200 }));
    }),
  );
}

test.each([
  ["the model failed", () => Promise.resolve(new Response(JSON.stringify({ enabled: true, available: false, reason: "AI draft unavailable", draft: null }), { status: 200 }))],
  ["the request failed", () => Promise.reject(new TypeError("network down"))],
])("when %s the nurse sees 'AI draft unavailable'", async (_label, post) => {
  stubApi(post);
  const beforeDraft = vi.fn().mockResolvedValue(undefined);
  render(<AiDraftPanel encounterId={7} consent beforeDraft={beforeDraft} onInsert={vi.fn()} />);

  fireEvent.click(await screen.findByRole("button", { name: "Draft note from transcript" }));

  expect(await screen.findByTestId("ai-draft-unavailable")).toHaveTextContent("AI draft unavailable");
  expect(beforeDraft).toHaveBeenCalled();
});

test("the panel is hidden when the draft is not switched on for the pod", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(new Response(JSON.stringify({ enabled: false, available: false, reason: "off", draft: null }), { status: 200 })),
  );
  const { container } = render(<AiDraftPanel encounterId={7} consent beforeDraft={vi.fn()} onInsert={vi.fn()} />);
  await new Promise((r) => setTimeout(r, 0));
  expect(container).toBeEmptyDOMElement();
});

test("drafting waits for transcription consent", async () => {
  stubApi(() => Promise.reject(new Error("should not be called")));
  render(<AiDraftPanel encounterId={7} consent={false} beforeDraft={vi.fn()} onInsert={vi.fn()} />);
  expect(await screen.findByRole("button", { name: "Draft note from transcript" })).toBeDisabled();
});
