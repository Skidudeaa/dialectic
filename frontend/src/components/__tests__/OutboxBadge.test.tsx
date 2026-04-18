// OutboxBadge tests — renders nothing when queued=0, renders the count + popover
// when queued>0. Mocks the api helper so we don't hit real fetch.

import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, fireEvent, cleanup } from "@testing-library/react";

import OutboxBadge from "../OutboxBadge";
import * as api from "../../lib/api";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("OutboxBadge", () => {
  it("renders nothing when queued is 0", async () => {
    vi.spyOn(api, "fetchOutboxStatus").mockResolvedValue({
      queued: 0,
      byRoom: {},
      oldest: null,
      newest: null,
      totalBytes: 0,
      replayCap: 500,
    });
    const { container } = render(<OutboxBadge />);
    // Wait a tick for the fetch promise to settle.
    await waitFor(() => {
      expect(api.fetchOutboxStatus).toHaveBeenCalled();
    });
    expect(container.firstChild).toBeNull();
  });

  it("renders the count when queued > 0", async () => {
    vi.spyOn(api, "fetchOutboxStatus").mockResolvedValue({
      queued: 5,
      byRoom: { "room-A": 3, "room-B": 2 },
      oldest: new Date(Date.now() - 60_000).toISOString(),
      newest: new Date().toISOString(),
      totalBytes: 4096,
      replayCap: 500,
    });
    render(<OutboxBadge />);
    const button = await screen.findByRole("button", {
      name: /5 snapshots queued/i,
    });
    expect(button.textContent).toContain("5");
  });

  it("opens a popover with per-room breakdown on click", async () => {
    vi.spyOn(api, "fetchOutboxStatus").mockResolvedValue({
      queued: 3,
      byRoom: { "room-A": 2, "room-B": 1 },
      oldest: new Date(Date.now() - 120_000).toISOString(),
      newest: new Date().toISOString(),
      totalBytes: 2048,
      replayCap: 500,
    });
    render(<OutboxBadge />);
    const button = await screen.findByRole("button", { name: /queued/i });
    fireEvent.click(button);
    const dialog = await screen.findByRole("dialog", { name: /outbox/i });
    expect(dialog.textContent).toContain("room-A");
    expect(dialog.textContent).toContain("room-B");
    expect(dialog.textContent).toContain("cap 500");
  });

  it("renders nothing if the fetch fails (graceful degrade)", async () => {
    vi.spyOn(api, "fetchOutboxStatus").mockRejectedValue(new Error("net"));
    const { container } = render(<OutboxBadge />);
    await waitFor(() => {
      expect(api.fetchOutboxStatus).toHaveBeenCalled();
    });
    expect(container.firstChild).toBeNull();
  });

  // ── Drain-now button ──────────────────────────────────────────────────
  // The popover surfaces a manual "Drain now" button when there's something
  // queued. Hidden when queued=0 (the badge itself is hidden), visible and
  // clickable when queued>0, and successful clicks toast + refetch.

  it("does not render the drain button when queued=0 (badge is hidden too)", async () => {
    vi.spyOn(api, "fetchOutboxStatus").mockResolvedValue({
      queued: 0,
      byRoom: {},
      oldest: null,
      newest: null,
      totalBytes: 0,
      replayCap: 500,
    });
    const { container } = render(<OutboxBadge />);
    await waitFor(() => {
      expect(api.fetchOutboxStatus).toHaveBeenCalled();
    });
    // Badge hidden -> popover never renders -> button never renders.
    expect(container.firstChild).toBeNull();
    expect(
      screen.queryByRole("button", { name: /drain queued snapshots now/i }),
    ).toBeNull();
  });

  it("shows the drain button in the popover when queued > 0", async () => {
    vi.spyOn(api, "fetchOutboxStatus").mockResolvedValue({
      queued: 4,
      byRoom: { "room-A": 4 },
      oldest: new Date(Date.now() - 30_000).toISOString(),
      newest: new Date().toISOString(),
      totalBytes: 1024,
      replayCap: 500,
    });
    render(<OutboxBadge />);
    const badge = await screen.findByRole("button", { name: /queued/i });
    fireEvent.click(badge);
    const drainBtn = await screen.findByRole("button", {
      name: /drain queued snapshots now/i,
    });
    expect(drainBtn).toBeTruthy();
    expect(drainBtn.textContent).toContain("Drain now");
    expect(drainBtn.hasAttribute("disabled")).toBe(false);
  });

  it("clicking drain calls replayOutbox and refetches status", async () => {
    const fetchSpy = vi.spyOn(api, "fetchOutboxStatus").mockResolvedValue({
      queued: 2,
      byRoom: { "room-A": 2 },
      oldest: new Date(Date.now() - 5_000).toISOString(),
      newest: new Date().toISOString(),
      totalBytes: 512,
      replayCap: 500,
    });
    const replaySpy = vi.spyOn(api, "replayOutbox").mockResolvedValue({
      replayed: 2,
      remaining: 0,
      perRoom: [
        { roomId: "room-A", replayed: 2, remaining: 0, errors: [] },
      ],
      dialecticUrl: "http://localhost:8002",
      durationMs: 42,
    });

    render(<OutboxBadge />);
    const badge = await screen.findByRole("button", { name: /queued/i });
    fireEvent.click(badge);
    const drainBtn = await screen.findByRole("button", {
      name: /drain queued snapshots now/i,
    });
    fireEvent.click(drainBtn);
    await waitFor(() => {
      expect(replaySpy).toHaveBeenCalledTimes(1);
    });
    // The drain handler refetches status after a successful replay so the
    // badge immediately reflects the empty queue. fetch is therefore called
    // at least twice (mount + post-drain refetch).
    await waitFor(() => {
      expect(fetchSpy.mock.calls.length).toBeGreaterThanOrEqual(2);
    });
  });
});
