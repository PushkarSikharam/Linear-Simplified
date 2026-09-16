import type { VoiceEngineMode } from "@/lib/hybrid-voice-engine";

// A provider is named only after the API has reported that it produced the audio.
export function voiceModeLabel(mode: VoiceEngineMode): string {
  if (mode === "azure") return "Microsoft Voice";
  if (mode === "gemini") return "Cloud Voice";
  if (mode === "local") return "Browser Voice";
  return "Voice";
}
