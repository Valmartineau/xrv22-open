import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook } from "@testing-library/react";
import { useLiveBus } from "./useLiveBus";

class FakeWS {
  static OPEN = 1;
  static last: FakeWS | null = null;
  readyState = FakeWS.OPEN;
  send = vi.fn();
  close = vi.fn();
  onopen: (() => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  onmessage: ((ev: { data: string }) => void) | null = null;
  constructor() { FakeWS.last = this; }
}

beforeEach(() => {
  FakeWS.last = null;
  vi.stubGlobal("WebSocket", FakeWS as unknown as typeof WebSocket);
});

describe("useLiveBus.send", () => {
  it("envoie le JSON quand le WS est ouvert", () => {
    const { result } = renderHook(() => useLiveBus(() => {}));
    result.current.send({ type: "jog.alive", rid: "robot_1" });
    expect(FakeWS.last?.send).toHaveBeenCalledWith(
      JSON.stringify({ type: "jog.alive", rid: "robot_1" }));
  });

  it("no-op quand le WS est ferme", () => {
    const { result } = renderHook(() => useLiveBus(() => {}));
    if (FakeWS.last) FakeWS.last.readyState = 3;   // CLOSED
    result.current.send({ type: "jog.alive", rid: "robot_1" });
    expect(FakeWS.last?.send).not.toHaveBeenCalled();
  });
});
