import { describe, expect, it } from "vitest";

import { isEchoOfAgent } from "@/lib/voice-echo";

const GREETING = "Welcome to Pixel. I'm Edith, your guide to planning work, tracking tickets, and connecting your team's tools. What brought you to check us out today?";
const REPLY = "I found LIN-142, assigned to Maya Chen. I'll open that ticket.";

describe("voice echo detection", () => {
  it("recognises Edith's own words coming back through the microphone", () => {
    expect(isEchoOfAgent("your guide to planning work tracking tickets", [GREETING])).toBe(true);
    expect(isEchoOfAgent("I found LIN-142 assigned to Maya Chen", [REPLY])).toBe(true);
    // Recognisers mishear a word or two.
    expect(isEchoOfAgent("I found lin 142 assigned to Maya chin", [REPLY])).toBe(true);
  });

  it("never drops a real question that shares words with Edith", () => {
    // Each of these was silently ignored by the old keyword filter.
    for (const question of [
      "Edith, show sprint planning",
      "What can Pixel do with Slack?",
      "Welcome me to the planning view",
      "I found a bug in the login page",
      "Can you open Maya's ticket please",
      "assign it to Noah"
    ]) {
      expect(isEchoOfAgent(question, [GREETING, REPLY])).toBe(false);
    }
  });

  it("treats short phrases as the visitor's, even when Edith used them", () => {
    expect(isEchoOfAgent("open that ticket", [REPLY])).toBe(false);
  });

  it("with nothing said yet, nothing is an echo", () => {
    expect(isEchoOfAgent("I found LIN-142 assigned to Maya Chen", [])).toBe(false);
    expect(isEchoOfAgent("", [REPLY])).toBe(false);
  });
});
