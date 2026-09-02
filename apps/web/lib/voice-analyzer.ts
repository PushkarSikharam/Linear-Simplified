export type SpectrumData = [number, number, number, number, number];

export class VoiceAnalyzer {
  private audioCtx: AudioContext | null = null;
  private analyser: AnalyserNode | null = null;
  private micStream: MediaStream | null = null;
  private source: MediaStreamAudioSourceNode | null = null;
  private animFrameId: number | null = null;
  private isAnalyzing = false;

  public async start(
    onSpectrum: (data: SpectrumData, totalVolume: number) => void,
    existingStream?: MediaStream
  ): Promise<MediaStream> {
    this.stop();

    const stream =
      existingStream ??
      (await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true
        }
      }));

    this.micStream = stream;

    const AudioContextClass =
      window.AudioContext || (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;

    this.audioCtx = new AudioContextClass();
    this.analyser = this.audioCtx.createAnalyser();
    this.analyser.fftSize = 64;
    this.analyser.smoothingTimeConstant = 0.7;

    this.source = this.audioCtx.createMediaStreamSource(stream);
    this.source.connect(this.analyser);

    const bufferLength = this.analyser.frequencyBinCount;
    const dataArray = new Uint8Array(bufferLength);
    this.isAnalyzing = true;

    const update = () => {
      if (!this.isAnalyzing || !this.analyser) return;

      this.analyser.getByteFrequencyData(dataArray);

      // Aggregate spectrum into 5 bars
      const bands = 5;
      const step = Math.floor(bufferLength / bands) || 1;
      const spectrum: SpectrumData = [0, 0, 0, 0, 0];
      let sum = 0;

      for (let i = 0; i < bands; i++) {
        let bandSum = 0;
        const count = step;
        for (let j = 0; j < count; j++) {
          const idx = i * step + j;
          if (idx < bufferLength) {
            bandSum += dataArray[idx];
          }
        }
        const avg = bandSum / count;
        // Normalize 0..255 -> 10..100% height
        spectrum[i] = Math.min(100, Math.max(12, Math.round((avg / 255) * 100 * 1.5)));
        sum += avg;
      }

      const totalVolume = Math.min(100, Math.round((sum / (bands * 255)) * 100 * 2));
      onSpectrum(spectrum, totalVolume);

      this.animFrameId = requestAnimationFrame(update);
    };

    update();
    return stream;
  }

  public stop(): void {
    this.isAnalyzing = false;
    if (this.animFrameId !== null) {
      cancelAnimationFrame(this.animFrameId);
      this.animFrameId = null;
    }
    if (this.source) {
      this.source.disconnect();
      this.source = null;
    }
    if (this.audioCtx && this.audioCtx.state !== "closed") {
      void this.audioCtx.close().catch(() => undefined);
      this.audioCtx = null;
    }
    if (this.micStream) {
      this.micStream.getTracks().forEach((track) => track.stop());
      this.micStream = null;
    }
  }

  public getStream(): MediaStream | null {
    return this.micStream;
  }
}
