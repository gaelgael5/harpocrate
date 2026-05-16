import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

import * as adminApi from "./adminApi";
import {
  runGDriveOAuthFlow,
  runGDriveReauthorize,
  PopupBlockedError,
  OAuthAbortedError,
  OAuthError,
} from "./gdriveOAuth";

const FAKE_PARAMS = {
  client_id: "cid",
  client_secret: "csec",
  folder_name: "F",
  name: "N",
} as const;

function fakePopup(opts: { closed?: boolean } = {}) {
  const p = { closed: opts.closed ?? false, close: vi.fn() };
  return p as unknown as Window;
}

describe("runGDriveOAuthFlow", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("happy path : popup ouvre, postMessage reçu, retourne state + email", async () => {
    vi.spyOn(adminApi, "startGDriveOAuth").mockResolvedValue({
      auth_url: "https://accounts.google.com/...",
      state: "ST",
    });
    vi.spyOn(adminApi, "fetchGDriveOAuthSession").mockResolvedValue({
      status: "authorized",
      result: { user_email: "ok@x.y" },
    });
    const popup = fakePopup();
    vi.spyOn(window, "open").mockReturnValue(popup);

    const flow = runGDriveOAuthFlow(FAKE_PARAMS);

    setTimeout(() => {
      window.dispatchEvent(
        new MessageEvent("message", {
          data: { type: "gdrive_oauth_done", state: "ST", ok: true },
          origin: window.location.origin,
        }),
      );
    }, 10);

    await vi.advanceTimersByTimeAsync(20);
    const result = await flow;
    expect(result.state).toBe("ST");
    expect(result.user_email).toBe("ok@x.y");
  });

  it("popup bloquée : throw PopupBlockedError", async () => {
    vi.spyOn(adminApi, "startGDriveOAuth").mockResolvedValue({
      auth_url: "x",
      state: "ST",
    });
    vi.spyOn(window, "open").mockReturnValue(null);
    await expect(runGDriveOAuthFlow(FAKE_PARAMS)).rejects.toBeInstanceOf(
      PopupBlockedError,
    );
  });

  it("postMessage depuis mauvaise origin : ignoré jusqu'à popup.closed", async () => {
    vi.spyOn(adminApi, "startGDriveOAuth").mockResolvedValue({
      auth_url: "x",
      state: "ST",
    });
    const popup = fakePopup();
    vi.spyOn(window, "open").mockReturnValue(popup);

    const flow = runGDriveOAuthFlow(FAKE_PARAMS);
    // Register rejection handler immediately to avoid unhandled rejection warnings
    const assertion = expect(flow).rejects.toBeInstanceOf(OAuthAbortedError);

    setTimeout(() => {
      window.dispatchEvent(
        new MessageEvent("message", {
          data: { type: "gdrive_oauth_done", state: "ST", ok: true },
          origin: "https://evil.example.com",
        }),
      );
      (popup as unknown as { closed: boolean }).closed = true;
    }, 10);

    await vi.advanceTimersByTimeAsync(2000);
    await assertion;
  });

  it("postMessage avec mauvais state : ignoré jusqu'à popup.closed", async () => {
    vi.spyOn(adminApi, "startGDriveOAuth").mockResolvedValue({
      auth_url: "x",
      state: "ST",
    });
    const popup = fakePopup();
    vi.spyOn(window, "open").mockReturnValue(popup);

    const flow = runGDriveOAuthFlow(FAKE_PARAMS);
    // Register rejection handler immediately to avoid unhandled rejection warnings
    const assertion = expect(flow).rejects.toBeInstanceOf(OAuthAbortedError);

    setTimeout(() => {
      window.dispatchEvent(
        new MessageEvent("message", {
          data: { type: "gdrive_oauth_done", state: "WRONG", ok: true },
          origin: window.location.origin,
        }),
      );
      (popup as unknown as { closed: boolean }).closed = true;
    }, 10);

    await vi.advanceTimersByTimeAsync(2000);
    await assertion;
  });

  it("postMessage ok:false : throw OAuthError", async () => {
    vi.spyOn(adminApi, "startGDriveOAuth").mockResolvedValue({
      auth_url: "x",
      state: "ST",
    });
    const popup = fakePopup();
    vi.spyOn(window, "open").mockReturnValue(popup);

    const flow = runGDriveOAuthFlow(FAKE_PARAMS);
    // Register rejection handler immediately to avoid unhandled rejection warnings
    const assertion = expect(flow).rejects.toBeInstanceOf(OAuthError);

    setTimeout(() => {
      window.dispatchEvent(
        new MessageEvent("message", {
          data: {
            type: "gdrive_oauth_done",
            state: "ST",
            ok: false,
            error: "access_denied",
          },
          origin: window.location.origin,
        }),
      );
    }, 10);

    await vi.advanceTimersByTimeAsync(20);
    await assertion;
  });

  it("popup fermée sans message : reject OAuthAbortedError", async () => {
    vi.spyOn(adminApi, "startGDriveOAuth").mockResolvedValue({
      auth_url: "x",
      state: "ST",
    });
    const popup = fakePopup();
    vi.spyOn(window, "open").mockReturnValue(popup);

    const flow = runGDriveOAuthFlow(FAKE_PARAMS);
    // Register rejection handler immediately to avoid unhandled rejection warnings
    const assertion = expect(flow).rejects.toBeInstanceOf(OAuthAbortedError);

    setTimeout(() => {
      (popup as unknown as { closed: boolean }).closed = true;
    }, 50);

    await vi.advanceTimersByTimeAsync(2000);
    await assertion;
  });
});

describe("runGDriveReauthorize", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("appelle reauthorizeGDriveConnection puis le flow popup", async () => {
    const popup = fakePopup();
    vi.spyOn(window, "open").mockReturnValue(popup);
    vi.spyOn(adminApi, "reauthorizeGDriveConnection").mockResolvedValue({
      auth_url: "https://accounts.google.com/...",
      state: "REAUTH-X",
    });
    vi.spyOn(adminApi, "fetchGDriveOAuthSession").mockResolvedValue({
      status: "authorized",
      result: { user_email: "r@x.y" },
    });

    const flow = runGDriveReauthorize("conn-id-1");

    setTimeout(() => {
      window.dispatchEvent(
        new MessageEvent("message", {
          data: { type: "gdrive_oauth_done", state: "REAUTH-X", ok: true },
          origin: window.location.origin,
        }),
      );
    }, 10);

    await vi.advanceTimersByTimeAsync(20);
    const result = await flow;
    expect(result.user_email).toBe("r@x.y");
    expect(adminApi.reauthorizeGDriveConnection).toHaveBeenCalledWith(
      "conn-id-1",
    );
  });
});
