import { fireEvent, render, screen } from "@testing-library/react";
import { expect, test, vi } from "vitest";

import { ConflictPanel, SyncStatus } from "./SyncStatus";

test("while syncing the nurse sees that the save is safe here", () => {
  render(<SyncStatus status="syncing" />);
  expect(screen.getByTestId("sync-status")).toHaveTextContent("Saved here, syncing to record");
});

test("synced and unsaved states", () => {
  const { rerender, container } = render(<SyncStatus status="synced" />);
  expect(screen.getByTestId("sync-status")).toHaveTextContent("Synced to the CM record");
  rerender(<SyncStatus status="wrapped" />);
  expect(container).toBeEmptyDOMElement();
});

test("a version conflict shows both versions and saves only on an explicit choice", () => {
  const onSave = vi.fn();
  render(
    <ConflictPanel
      conflict={{
        reason: "changed",
        base_version: 1,
        current_version: 2,
        ours: { note: { body: "Reached Raymond and Joan." } },
        theirs: { version: 2, notes: [{ body: "Called by the night team." }] },
      }}
      onSaveAgainst={onSave}
    />,
  );
  const panel = screen.getByTestId("writeback-conflict");
  expect(panel).toHaveTextContent("version 1 → 2");
  expect(panel).toHaveTextContent("Nothing was written");
  expect(panel).toHaveTextContent("Reached Raymond and Joan.");
  expect(panel).toHaveTextContent("Called by the night team.");
  expect(onSave).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: /save against version 2/ }));
  expect(onSave).toHaveBeenCalledWith(2);
});
