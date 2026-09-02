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

  private isStopped = false;

  /** Clean up all running streams/audio without permanently stopping the engine */
  private cleanup(): void {
    this.stopWebRTC();
    this.stopLocalEngine();
    this.cancelSpeech();
    this.callbacks.onError("");
    this.callbacks.onSpectrumChange([15, 20, 15, 18, 12]);
  }

  public async start(): Promise<void> {
    this.isStopped = false;
    this.isSpeakingSelf = true; // Block any stray mic input during cooldown
    this.cleanup();
    this.setStatus("Connecting", "connecting");

    // Wait for speakers to fully go silent after cancelling any playing greeting audio.
    // Without this delay, the mic immediately picks up the tail-end of Edith's
    // voice from the speakers and submits it as user input.
    await new Promise((resolve) => setTimeout(resolve, 700));
    this.isSpeakingSelf = false;

    if (this.isStopped) return; // User clicked stop during cooldown

    try {
      // Check session API endpoint for OpenAI key
      const res = await fetch("/api/realtime-session");
      const sessionData = (await res.json()) as {
        success: boolean;
        mode: string;
        client_secret?: string;
        reason?: string;
      };

      if (this.isStopped) return; // User clicked stop during fetch

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
    this.isStopped = true;
    this.isSpeakingSelf = false;
    this.cleanup();
    this.setStatus("Idle", this.mode);
  }

  public pauseListening(): void {
    this.setStatus("Thinking", this.mode);
    this.stopLocalEngine();
  }

  private currentAudio: HTMLAudioElement | null = null;
  private currentAudioUrl: string | null = null;

  private isSpeakingSelf = false;

  private pauseRecognition(): void {
    this.isSpeakingSelf = true;
    if (this.recognition) {
      try {
        const rec = this.recognition as any;
        rec.onresult = null;
        rec.onend = null;
        if (typeof rec.abort === "function") rec.abort();
      } catch {
        // ignore
      }
      this.recognition = null;
    }
  }

  public async speakLocalResponse(text: string, onEnded?: () => void, resumeListening = false): Promise<void> {
    this.isStopped = false;
    this.isSpeakingSelf = true;
    this.cancelSpeech();
    this.pauseRecognition();

    // Try cloud TTS (Gemini Aoede natural voice) with a fast 1.5s timeout.
    // Falls back instantly to browser voice if cloud is slow or quota-exhausted.
    try {
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), 1500);
      const res = await fetch("/api/tts", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text }),
        signal: controller.signal
      });
      clearTimeout(timer);

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
          if (this.isStopped) {
            audio.pause();
            return;
          }
          this.setStatus("Speaking", this.mode);
          this.callbacks.onAgentSpeech(text);

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
          if (animInterval) { clearInterval(animInterval); animInterval = null; }
          this.callbacks.onSpectrumChange([15, 20, 15, 18, 12]);
          this.cancelSpeech();

          if (this.isStopped) {
            this.isSpeakingSelf = false;
            this.setStatus("Idle", this.mode);
            return;
          }

          if (resumeListening) {
            this.setStatus("Listening", this.mode);
            setTimeout(() => {
              this.isSpeakingSelf = false;
              if (!this.isStopped && this.mode === "local") {
                void this.startLocalEngine("Resuming after speech");
              }
            }, 400);
          } else {
            this.isSpeakingSelf = false;
            this.stop();
          }
          onEnded?.();
        };

        audio.onended = handleDone;
        audio.onerror = () => {
          if (animInterval) { clearInterval(animInterval); animInterval = null; }
          this.fallbackBrowserSpeech(text, onEnded, resumeListening);
        };

        await audio.play();
        return;
      }
    } catch {
      // Cloud TTS unavailable or timed out — use browser voice
    }

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

    // Soft, natural human cadence & gentle pitch
    utterance.rate = 0.94;
    utterance.pitch = 1.0;
    utterance.volume = 1.0;

    utterance.onstart = () => {
      if (this.isStopped) {
        window.speechSynthesis.cancel();
        return;
      }
      this.setStatus("Speaking", this.mode);
      this.callbacks.onAgentSpeech(text);
    };

    const finishHandler = () => {
      if (this.isStopped) {
        this.isSpeakingSelf = false;
        this.setStatus("Idle", this.mode);
        return;
      }
      if (resumeListening) {
        this.setStatus("Listening", this.mode);
        setTimeout(() => {
          this.isSpeakingSelf = false;
          if (!this.isStopped && this.mode === "local") {
            void this.startLocalEngine("Resuming listening after speech");
          }
        }, 400);
      } else {
        this.isSpeakingSelf = false;
        this.stop();
      }
      onEnded?.();
    };

    utterance.onend = finishHandler;
    utterance.onerror = finishHandler;

    try {
      window.speechSynthesis.resume();
    } catch {
      // ignore
    }
    window.speechSynthesis.speak(utterance);
  }

  private speakOnlyAbort: AbortController | null = null;
  private speakOnlyGen = 0;

  /**
   * Speak text using TTS without affecting engine status or mic.
   * Completely independent audio playback — no status changes, no recognition.
   * Used for auto-greeting and manual message playback.
   */
  // In-memory cache for TTS audio blobs to avoid re-fetching the same text
  private static ttsCache = new Map<string, Blob>();

  public speakOnly(text: string, onEnded?: () => void): void {
    this.isStopped = false;
    this.cancelSpeech();
    const gen = ++this.speakOnlyGen;

    if (typeof window === "undefined" || !("speechSynthesis" in window)) {
      onEnded?.();
      return;
    }

    const playBrowserVoice = () => {
      if (gen !== this.speakOnlyGen) return; // Stale — cancelled

      const doSpeak = () => {
        try { window.speechSynthesis.resume(); } catch { /* ignore */ }
        const utterance = new SpeechSynthesisUtterance(text);
        const voices = window.speechSynthesis.getVoices();
        const bestVoice = getBestNaturalVoice(voices);
        if (bestVoice) utterance.voice = bestVoice;
        utterance.rate = 0.94;
        utterance.pitch = 1.0;
        utterance.volume = 1.0;
        utterance.onend = () => onEnded?.();
        utterance.onerror = () => onEnded?.();
        try { window.speechSynthesis.resume(); } catch { /* ignore */ }
        window.speechSynthesis.speak(utterance);
      };

      if (window.speechSynthesis.getVoices().length > 0) {
        doSpeak();
      } else {
        const prevHandler = window.speechSynthesis.onvoiceschanged;
        window.speechSynthesis.onvoiceschanged = (e) => {
          if (prevHandler) (prevHandler as any)(e);
          doSpeak();
          window.speechSynthesis.onvoiceschanged = null;
        };
      }
    };

    const playBlob = (blob: Blob) => {
      if (gen !== this.speakOnlyGen) return;
      const url = URL.createObjectURL(blob);
      this.currentAudioUrl = url;
      const audio = new Audio(url);
      this.currentAudio = audio;
      audio.onended = () => {
        this.cancelSpeech();
        onEnded?.();
      };
      audio.onerror = () => {
        this.cancelSpeech();
        playBrowserVoice();
      };
      audio.play().catch(() => playBrowserVoice());
    };

    // Check cache first — avoids burning API quota on repeated greeting playback
    const cached = HybridVoiceEngine.ttsCache.get(text);
    if (cached) {
      playBlob(cached);
      return;
    }

    // Try cloud TTS (Gemini Aoede) with 2s timeout, fall back to browser voice
    this.speakOnlyAbort = new AbortController();
    const signal = this.speakOnlyAbort.signal;
    const fetchTimer = setTimeout(() => {
      if (gen === this.speakOnlyGen && this.speakOnlyAbort) {
        this.speakOnlyAbort.abort();
      }
    }, 2000);

    fetch("/api/tts", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
      signal
    })
      .then((res) => {
        clearTimeout(fetchTimer);
        if (gen !== this.speakOnlyGen) return;
        if (res.ok && res.headers.get("Content-Type")?.includes("audio")) {
          return res.blob().then((blob) => {
            if (gen !== this.speakOnlyGen) return;
            // Cache for future use
            HybridVoiceEngine.ttsCache.set(text, blob);
            playBlob(blob);
          });
        }
        playBrowserVoice();
      })
      .catch(() => {
        clearTimeout(fetchTimer);
        if (gen !== this.speakOnlyGen) return;
        playBrowserVoice();
      });
  }

  public cancelSpeech(): void {
    // Abort any in-flight speakOnly fetch
    if (this.speakOnlyAbort) {
      this.speakOnlyAbort.abort();
      this.speakOnlyAbort = null;
    }
    // Invalidate speakOnly generation so late callbacks are discarded
    this.speakOnlyGen++;

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
        if (this.isSpeakingSelf || this.status === "Speaking") {
          return; // Prevent Edith from listening to her own speaker output
        }
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

  // Tier 1: Soft female Microsoft Natural/Neural voices (Jenny, Aria, Ava, Emma, Sonia)
  const softFemaleNeural = pool.find((v) => {
    const name = v.name.toLowerCase();
    return (
      (name.includes("natural") || name.includes("neural") || name.includes("online")) &&
      (name.includes("jenny") || name.includes("aria") || name.includes("ava") || name.includes("emma") || name.includes("sonia"))
    );
  });
  if (softFemaleNeural) return softFemaleNeural;

  // Tier 2: Any Microsoft/Edge Natural Neural voice
  const naturalOnline = pool.find(
    (v) =>
      v.name.includes("Natural") ||
      v.name.includes("Online (Natural)") ||
      v.name.includes("Neural")
  );
  if (naturalOnline) return naturalOnline;

  // Tier 3: Google Chrome US English Female voice
  const googleVoice = pool.find(
    (v) =>
      v.name === "Google US English" ||
      v.name === "Google UK English Female" ||
      (v.name.includes("Google") && v.name.includes("English"))
  );
  if (googleVoice) return googleVoice;

  // Tier 4: Apple Soft Natural Voices (Samantha, Victoria, Karen, Siri)
  const appleVoice = pool.find(
    (v) =>
      v.name.includes("Samantha") ||
      v.name.includes("Victoria") ||
      v.name.includes("Karen") ||
      v.name.includes("Siri")
  );
  if (appleVoice) return appleVoice;

  // Tier 5: Microsoft Zira (Windows pre-installed female voice)
  const ziraVoice = pool.find((v) => v.name.toLowerCase().includes("zira"));
  if (ziraVoice) return ziraVoice;

  return pool[0];
}

