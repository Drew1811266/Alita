import { describe, expect, it } from "vitest";
import type { PreferencesView } from "./preferencesApi";
import {
  createPreferencesControllerState,
  preferencesLoaded,
} from "./usePreferencesController";

describe("preferences controller helpers", () => {
  it("stores loaded preferences and clears loading state", () => {
    const preferences = { schemaVersion: 3 } as unknown as PreferencesView;

    const state = preferencesLoaded(
      createPreferencesControllerState(),
      preferences,
    );

    expect(state.preferences).toBe(preferences);
    expect(state.loading).toBe(false);
    expect(state.error).toBeNull();
  });
});
