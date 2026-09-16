import { describe, expect, it } from "vitest";
import { voiceModeLabel } from "./voice-labels";

describe("voiceModeLabel", () => {
  it("names a provider only once its audio has been reported", () => {
    expect(voiceModeLabel("azure")).toBe("Microsoft Voice");
    expect(voiceModeLabel("gemini")).toBe("Cloud Voice");
    expect(voiceModeLabel("local")).toBe("Browser Voice");
  });

  it("stays neutral while no provider has answered", () => {
    expect(voiceModeLabel("connecting")).toBe("Voice");
  });
});
