import { describe, expect, it } from "vitest";

import {
  createVoiceInputControllerState,
  voiceControllerFailed,
} from "./useVoiceInputController";

describe("voice input controller helpers", () => {
  it("records voice failures in controller state", () => {
    const state = voiceControllerFailed(
      createVoiceInputControllerState(),
      "microphone denied",
    );

    expect(state.voiceInput.status).toBe("failed");
    expect(state.voiceInput.message).toBe("microphone denied");
  });
});
