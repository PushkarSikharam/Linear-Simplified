import fs from "fs";
import path from "path";
import { NextResponse } from "next/server";

function getGeminiKey(): string | undefined {
  if (process.env.GEMINI_API_KEY && process.env.GEMINI_API_KEY.trim() && process.env.GEMINI_API_KEY !== "your_gemini_api_key_here") {
    return process.env.GEMINI_API_KEY.trim();
  }
  try {
    const envPath = path.join(process.cwd(), ".env.local");
    if (fs.existsSync(envPath)) {
      const content = fs.readFileSync(envPath, "utf-8");
      const match = content.match(/GEMINI_API_KEY=([^\r\n]+)/);
      if (match && match[1]?.trim() && match[1].trim() !== "your_gemini_api_key_here") {
        return match[1].trim();
      }
    }
  } catch {
    // ignore
  }
  return undefined;
}

function pcmToWav(pcmBuffer: Buffer, sampleRate = 24000, numChannels = 1, bitsPerSample = 16): Buffer {
  const byteRate = (sampleRate * numChannels * bitsPerSample) / 8;
  const blockAlign = (numChannels * bitsPerSample) / 8;
  const dataSize = pcmBuffer.length;
  const header = Buffer.alloc(44);

  header.write("RIFF", 0);
  header.writeUInt32LE(36 + dataSize, 4);
  header.write("WAVE", 8);
  header.write("fmt ", 12);
  header.writeUInt32LE(16, 16);
  header.writeUInt16LE(1, 20); // PCM format
  header.writeUInt16LE(numChannels, 22);
  header.writeUInt32LE(sampleRate, 24);
  header.writeUInt32LE(byteRate, 28);
  header.writeUInt16LE(blockAlign, 32);
  header.writeUInt16LE(bitsPerSample, 34);
  header.write("data", 36);
  header.writeUInt32LE(dataSize, 40);

  return Buffer.concat([header, pcmBuffer]);
}

export async function POST(req: Request) {
  const geminiKey = getGeminiKey();
  const openaiKey = process.env.OPENAI_API_KEY;

  let body: { text?: string };
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ error: "Invalid JSON body" }, { status: 400 });
  }

  const text = body.text?.trim();
  if (!text) {
    return NextResponse.json({ error: "Text is required" }, { status: 400 });
  }

  // 1. Priority: Google Gemini 2.5 Flash Native Neural Audio
  if (geminiKey) {
    try {
      const payload = {
        contents: [
          {
            role: "user",
            parts: [
              {
                text: `You are Edith, a soft-spoken, warm, gentle, and natural conversational assistant for Pixel. Speak in a soft, calm, friendly female voice with unhurried conversational cadence:\n\n${text}`
              }
            ]
          }
        ],
        generationConfig: {
          responseModalities: ["AUDIO"],
          speechConfig: {
            voiceConfig: {
              prebuiltVoiceConfig: {
                voiceName: "Aoede" // Warm natural female voice from Google DeepMind
              }
            }
          }
        }
      };

      const res = await fetch(
        `https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-preview-tts:generateContent?key=${geminiKey}`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload)
        }
      );

      if (res.ok) {
        const data = await res.json();
        const b64Data = data.candidates?.[0]?.content?.parts?.[0]?.inlineData?.data;
        if (b64Data) {
          const pcmBuffer = Buffer.from(b64Data, "base64");
          const wavBuffer = pcmToWav(pcmBuffer, 24000, 1, 16);
          return new Response(new Uint8Array(wavBuffer), {
            headers: {
              "Content-Type": "audio/wav",
              "Cache-Control": "public, max-age=3600",
              "X-TTS-Engine": "gemini-2.5-flash"
            }
          });
        }
      } else {
        const errText = await res.text();
        console.warn("Gemini TTS API returned non-200:", res.status, errText);
      }
    } catch (e) {
      console.error("Gemini TTS fetch failed:", e);
    }
  }

  // 2. Fallback: OpenAI TTS (if configured)
  if (openaiKey && openaiKey.trim() && openaiKey !== "your_openai_api_key_here") {
    try {
      const response = await fetch("https://api.openai.com/v1/audio/speech", {
        method: "POST",
        headers: {
          Authorization: `Bearer ${openaiKey}`,
          "Content-Type": "application/json"
        },
        body: JSON.stringify({
          model: "tts-1",
          voice: "coral",
          input: text
        })
      });

      if (response.ok) {
        const audioBuffer = await response.arrayBuffer();
        return new Response(audioBuffer, {
          headers: {
            "Content-Type": "audio/mpeg",
            "Cache-Control": "public, max-age=3600",
            "X-TTS-Engine": "openai-tts"
          }
        });
      }
    } catch (e) {
      console.error("OpenAI TTS request failed:", e);
    }
  }

  return NextResponse.json(
    { error: "No neural TTS API key available. Use high-fidelity browser voice." },
    { status: 400 }
  );
}
