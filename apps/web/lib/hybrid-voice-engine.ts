import { SpectrumData, VoiceAnalyzer } from "@/lib/voice-analyzer";

export type VoiceEngineMode = "gemini" | "webrtc" | "local" | "connecting";
export type VoiceEngineStatus = "Idle" | "Connecting" | "Listening" | "Thinking" | "Speaking" | "Error";

export type HybridVoiceCallbacks = {
  onStatusChange: (status: VoiceEngineStatus, mode: VoiceEngineMode) => void;
  onSpectrumChange: (spectrum: SpectrumData) => void;
  onUserTranscript: (text: string, isFinal: boolean) => void;
  onAgentSpeech: (text: string) => void;
  onError: (errorMsg: string) => void;
};

export class HybridVoiceEngine {
  private mode: VoiceEngineMode = "connecting";
  private status: VoiceEngineStatus = "Idle";
  private analyzer = new VoiceAnalyzer();
  private callbacks: HybridVoiceCallbacks;

  // Local engine properties
  private recognition: unknown = null;
  private currentStream: MediaStream | null = null;
  private isBargeInTriggered = false;

  // WebRTC properties
  private pc: RTCPeerConnection | null = null;
  private dataChannel: RTCDataChannel | null = null;

  constructor(callbacks: HybridVoiceCallbacks) {
    this.callbacks = callbacks;
  }

  public async start(): Promise<void> {
    this.stop();
    this.setStatus("Connecting", "connecting");

    try {
      // Check session API endpoint for OpenAI key
      const res = await fetch("/api/realtime-session");
      const sessionData = (await res.json()) as {
        success: boolean;
        mode: string;
        client_secret?: string;
        reason?: string;
      };

      if (sessionData.success && sessionData.client_secret) {
        // Start WebRTC mode with OpenAI
        await this.startWebRTC(sessionData.client_secret);
      } else {
        // Fallback to Enhanced Web Audio Local Mode
        await this.startLocalEngine(sessionData.reason ?? "Using Web Audio Engine");
      }
    } catch (err) {
      await this.startLocalEngine("Failed to reach server session endpoint");
    }
  }

  public stop(): void {
    this.stopWebRTC();
    this.stopLocalEngine();
    this.setStatus("Idle", this.mode);
    this.callbacks.onError("");
    this.callbacks.onSpectrumChange([15, 20, 15, 18, 12]);
  }

  public pauseListening(): void {
    this.setStatus("Thinking", this.mode);
    this.stopLocalEngine();
  }

  private currentAudio: HTMLAudioElement | null = null;
  private currentAudioUrl: string | null = null;

  public async speakLocalResponse(text: string, onEnded?: () => void, resumeListening = false): Promise<void> {
    this.cancelSpeech();

    // 1. Try server-side Studio Neural TTS first (Gemini 2.5 Flash native voice or OpenAI)
    try {
      const res = await fetch("/api/tts", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text })
      });

      if (res.ok && res.headers.get("Content-Type")?.includes("audio")) {
        const engineType = res.headers.get("X-TTS-Engine");
        if (engineType?.includes("gemini")) {
          this.mode = "gemini";
        }

        const blob = await res.blob();
        const audioUrl = URL.createObjectURL(blob);
        this.currentAudioUrl = audioUrl;

        const audio = new Audio(audioUrl);
        this.currentAudio = audio;

        let animInterval: ReturnType<typeof setInterval> | null = null;

        audio.onplay = () => {
          this.setStatus("Speaking", this.mode);
          this.callbacks.onAgentSpeech(text);

          // Animate spectrum visualizer while Gemini is speaking
          animInterval = setInterval(() => {
            if (!this.currentAudio || this.currentAudio.paused) {
              if (animInterval) clearInterval(animInterval);
              return;
            }
            const randomBars: SpectrumData = [
              Math.floor(25 + Math.random() * 45),
              Math.floor(40 + Math.random() * 55),
              Math.floor(35 + Math.random() * 50),
              Math.floor(30 + Math.random() * 45),
              Math.floor(20 + Math.random() * 35)
            ];
            this.callbacks.onSpectrumChange(randomBars);
          }, 80);
        };

        const handleDone = () => {
          if (animInterval) {
            clearInterval(animInterval);
            animInterval = null;
          }
          this.callbacks.onSpectrumChange([15, 20, 15, 18, 12]);
          if (this.status === "Speaking") {
            if (resumeListening) {
              this.setStatus("Listening", this.mode);
            } else {
              this.stop();
            }
          }
          this.cancelSpeech();
          onEnded?.();
        };

        audio.onended = handleDone;
        audio.onerror = () => {
          if (animInterval) {
            clearInterval(animInterval);
            animInterval = null;
          }
          this.fallbackBrowserSpeech(text, onEnded, resumeListening);
        };

        await audio.play();
        return;
      }
    } catch {
      // Server neural TTS not available, fall back to browser natural voice
    }

    // 2. High-fidelity Natural Browser Voice fallback
    this.fallbackBrowserSpeech(text, onEnded, resumeListening);
  }

  private fallbackBrowserSpeech(text: string, onEnded?: () => void, resumeListening = false): void {
    if (typeof window === "undefined" || !("speechSynthesis" in window)) {
      this.setStatus("Idle", this.mode);
      return;
    }

    window.speechSynthesis.cancel();
    const utterance = new SpeechSynthesisUtterance(text);

    // Pick top-tier natural/neural voice installed on device
    const voices = window.speechSynthesis.getVoices();
    const bestVoice = getBestNaturalVoice(voices);

    if (bestVoice) {
      utterance.voice = bestVoice;
    }

    // Natural human cadence and pitch (avoids robotic frequency distortion)
    utterance.rate = 0.98;
    utterance.pitch = 1.0;

    utterance.onstart = () => {
      this.setStatus("Speaking", this.mode);
      this.callbacks.onAgentSpeech(text);
    };

    utterance.onend = () => {
      if (this.status === "Speaking") {
        if (resumeListening) {
          this.setStatus("Listening", this.mode);
        } else {
          this.stop();
        }
      }
      onEnded?.();
    };

    utterance.onerror = () => {
      if (this.status === "Speaking") {
        if (resumeListening) {
          this.setStatus("Listening", this.mode);
        } else {
          this.stop();
        }
      }
      onEnded?.();
    };

    try {
      window.speechSynthesis.resume();
    } catch {
      // ignore
    }
    window.speechSynthesis.speak(utterance);
  }

  /**
   * Speak text using TTS without starting mic/listening.
   * Used for auto-greeting and manual message playback.
   */
  public speakOnly(text: string, onEnded?: () => void): void {
    void this.speakLocalResponse(text, onEnded, false);
  }

  public cancelSpeech(): void {
    if (this.currentAudio) {
      this.currentAudio.pause();
      this.currentAudio = null;
    }
    if (this.currentAudioUrl) {
      URL.revokeObjectURL(this.currentAudioUrl);
      this.currentAudioUrl = null;
    }
    if (typeof window !== "undefined" && "speechSynthesis" in window) {
      window.speechSynthesis.cancel();
    }
  }

  // --- Local Web Audio Engine ---
  private async startLocalEngine(reasonNote: string): Promise<void> {
    this.mode = "local";

    try {
      // 1. Start audio analyzer & mic stream
      this.currentStream = await this.analyzer.start((spectrum) => {
        this.callbacks.onSpectrumChange(spectrum);
      });

      // 2. Start Speech Recognition
      const RecognitionClass =
        (window as unknown as { SpeechRecognition?: new () => unknown }).SpeechRecognition ||
        (window as unknown as { webkitSpeechRecognition?: new () => unknown }).webkitSpeechRecognition;

      if (!RecognitionClass) {
        this.callbacks.onError("Speech recognition is not supported in this browser.");
        this.setStatus("Error", "local");
        return;
      }

      const recognition = new (RecognitionClass as new () => any)();
      recognition.continuous = true;
      recognition.interimResults = true;
      recognition.lang = "en-US";

      recognition.onstart = () => {
        this.setStatus("Listening", "local");
      };

      recognition.onresult = (event: any) => {
        let interim = "";
        let final = "";

        for (let i = event.resultIndex; i < event.results.length; i++) {
          const res = event.results[i];
          const transcriptText = res[0]?.transcript ?? "";
          if (res.isFinal) {
            final += transcriptText;
          } else {
            interim += transcriptText;
          }
        }

        const fullText = (final.trim() + " " + interim.trim()).trim();
        if (fullText) {
          this.callbacks.onUserTranscript(fullText, Boolean(final.trim()));
        }
      };

      recognition.onerror = (err: any) => {
        // "no-speech", "aborted", and "canceled" are benign lifecycle events from deliberate stops
        if (err.error !== "no-speech" && err.error !== "aborted" && err.error !== "canceled") {
          this.callbacks.onError(`Speech error: ${err.error}`);
        }
      };

      recognition.onend = () => {
        if (this.status === "Listening") {
          try {
            recognition.start();
          } catch {
            // Already started or stopped
          }
        }
      };

      this.recognition = recognition;
      recognition.start();
    } catch (err) {
      this.callbacks.onError("Microphone access permission was denied or failed.");
      this.setStatus("Error", "local");
    }
  }

  private stopLocalEngine(): void {
    this.cancelSpeech();
    this.analyzer.stop();
    if (this.recognition) {
      try {
        const rec = this.recognition as any;
        rec.onerror = null; // detach handlers to suppress trailing "aborted" event
        rec.onend = null;
        if (typeof rec.abort === "function") {
          rec.abort();
        } else if (typeof rec.stop === "function") {
          rec.stop();
        }
      } catch {
        // ignore
      }
      this.recognition = null;
    }
    if (this.currentStream) {
      try {
        this.currentStream.getTracks().forEach((track) => track.stop());
      } catch {
        // ignore
      }
      this.currentStream = null;
    }
    this.callbacks.onSpectrumChange([15, 20, 15, 18, 12]);
  }

  // --- WebRTC OpenAI Engine ---
  private async startWebRTC(ephemeralKey: string): Promise<void> {
    try {
      this.pc = new RTCPeerConnection();

      // Audio track for playing back agent response
      const audioEl = document.createElement("audio");
      audioEl.autoplay = true;
      this.pc.ontrack = (e) => {
        audioEl.srcObject = e.streams[0];
      };

      // Get microphone stream & attach analyzer
      const stream = await this.analyzer.start((spectrum) => {
        this.callbacks.onSpectrumChange(spectrum);
      });
      this.currentStream = stream;

      stream.getTracks().forEach((track) => this.pc?.addTrack(track, stream));

      // Data Channel for real-time events & text
      this.dataChannel = this.pc.createDataChannel("oai-events");
      this.dataChannel.onmessage = (event) => {
        try {
          const msg = JSON.parse(event.data);
          if (msg.type === "response.audio_transcript.delta") {
            this.callbacks.onAgentSpeech(msg.delta);
            this.setStatus("Speaking", "webrtc");
          } else if (msg.type === "conversation.item.input_audio_transcription.completed") {
            this.callbacks.onUserTranscript(msg.transcript || "", true);
            this.setStatus("Thinking", "webrtc");
          }
        } catch {
          // ignore parsing error
        }
      };

      // Create WebRTC Offer
      const offer = await this.pc.createOffer();
      await this.pc.setLocalDescription(offer);

      const sdpRes = await fetch(
        `https://api.openai.com/v1/realtime?model=gpt-4o-realtime-preview`,
        {
          method: "POST",
          body: offer.sdp,
          headers: {
            Authorization: `Bearer ${ephemeralKey}`,
            "Content-Type": "application/sdp"
          }
        }
      );

      if (!sdpRes.ok) {
        throw new Error(`OpenAI SDP handshake failed with ${sdpRes.status}`);
      }

      const answerSdp = await sdpRes.text();
      await this.pc.setRemoteDescription({ type: "answer", sdp: answerSdp });

      this.setStatus("Listening", "webrtc");
    } catch (err) {
      // Fallback to local mode if WebRTC fails
      this.stopWebRTC();
      await this.startLocalEngine("WebRTC connection failed. Reverting to Web Audio Engine.");
    }
  }

  private stopWebRTC(): void {
    if (this.dataChannel) {
      this.dataChannel.close();
      this.dataChannel = null;
    }
    if (this.pc) {
      this.pc.close();
      this.pc = null;
    }
  }

  private setStatus(status: VoiceEngineStatus, mode: VoiceEngineMode): void {
    this.status = status;
    this.mode = mode;
    this.callbacks.onStatusChange(status, mode);
  }
}

/**
 * Intelligent voice selector that prioritizes high-fidelity Neural and Natural
 * browser voices (e.g. Edge Natural, Google US English, Apple Natural) and
 * strictly avoids obsolete, mechanical SAPI 5 synthesizers (e.g. Microsoft Zira/David Desktop).
 */
export function getBestNaturalVoice(voices: SpeechSynthesisVoice[]): SpeechSynthesisVoice | undefined {
  if (!voices || voices.length === 0) return undefined;
  const englishVoices = voices.filter((v) => v.lang.startsWith("en"));
  const pool = englishVoices.length > 0 ? englishVoices : voices;

  // Tier 1: Microsoft Edge / Windows Online Natural Neural voices (crystal-clear human quality)
  const naturalOnline = pool.find(
    (v) =>
      v.name.includes("Natural") ||
      v.name.includes("Online (Natural)") ||
      v.name.includes("Neural")
  );
  if (naturalOnline) return naturalOnline;

  // Tier 2: Google Chrome US/UK High-Definition Female/Conversational voices
  const googleVoice = pool.find(
    (v) =>
      v.name === "Google US English" ||
      v.name === "Google UK English Female" ||
      (v.name.includes("Google") && v.name.includes("English"))
  );
  if (googleVoice) return googleVoice;

  // Tier 3: Apple High-Quality Natural Voices (Samantha, Karen, Siri, Victoria)
  const appleVoice = pool.find(
    (v) =>
      v.name.includes("Samantha") ||
      v.name.includes("Karen") ||
      v.name.includes("Siri") ||
      v.name.includes("Victoria")
  );
  if (appleVoice) return appleVoice;

  // Tier 4: Modern Conversational Assistants (Jenny, Aria, Michelle, Ava)
  const modernVoice = pool.find(
    (v) =>
      v.name.includes("Jenny") ||
      v.name.includes("Aria") ||
      v.name.includes("Ava") ||
      v.name.includes("Michelle")
  );
  if (modernVoice) return modernVoice;

  // Tier 5: Any English voice that is NOT an obsolete robotic SAPI 5 synthesizer
  const nonRobotic = pool.find((v) => {
    const lower = v.name.toLowerCase();
    return (
      !lower.includes("desktop") &&
      !lower.includes("zira") &&
      !lower.includes("david") &&
      !lower.includes("mark") &&
      !lower.includes("hazel") &&
      !lower.includes("george")
    );
  });
  if (nonRobotic) return nonRobotic;

  // Last resort fallback
  return pool[0];
}

