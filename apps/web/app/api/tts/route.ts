import fs from "fs";
import path from "path";
import { NextResponse } from "next/server";

type TtsBody = {
  text?: string;
};

type AzureSpeechConfig = {
  key: string;
  region: string;
  voiceName: string;
  outputFormat: string;
};

const PLACEHOLDER_VALUES = new Set([
  "your_azure_speech_key_here",
  "your_gemini_api_key_here",
  "your_openai_api_key_here"
]);

let geminiCooldownUntil = 0;

function envValue(name: string): string | undefined {
  const value = process.env[name]?.trim();
  if (value && !PLACEHOLDER_VALUES.has(value)) {
    return value;
  }

  try {
    const envPath = path.join(process.cwd(), ".env.local");
    if (!fs.existsSync(envPath)) return undefined;
    const content = fs.readFileSync(envPath, "utf-8");
    const match = content.match(new RegExp(`^${name}=([^\\r\\n]+)`, "m"));
    const fileValue = match?.[1]?.trim();
    return fileValue && !PLACEHOLDER_VALUES.has(fileValue) ? fileValue : undefined;
  } catch {
    return undefined;
  }
}

function getAzureSpeechConfig(): AzureSpeechConfig | undefined {
  const key = envValue("AZURE_SPEECH_KEY");
  const region = envValue("AZURE_SPEECH_REGION");
  const voiceName = envValue("AZURE_SPEECH_VOICE_NAME") ?? "en-US-Ava:DragonHDLatestNeural";
  const outputFormat =
    envValue("AZURE_SPEECH_OUTPUT_FORMAT") ?? "audio-48khz-192kbitrate-mono-mp3";

  if (!key || !region) return undefined;

  return {
    key,
    region,
    voiceName,
    outputFormat
  };
}

function escapeSsml(value: string): string {
  return value
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&apos;");
}

function azureSsml(text: string, voiceName: string): string {
  const escapedText = escapeSsml(text);
  if (voiceName.includes(":DragonHD")) {
    return [
      "<speak version=\"1.0\" xml:lang=\"en-US\">",
      `<voice xml:lang="en-US" xml:gender="Female" name="${escapeSsml(voiceName)}">`,
      `<prosody rate="-2%" pitch="+0%">${escapedText}</prosody>`,
      "</voice>",
      "</speak>"
    ].join("");
  }

  return [
    "<speak version=\"1.0\" xmlns=\"http://www.w3.org/2001/10/synthesis\" xmlns:mstts=\"http://www.w3.org/2001/mstts\" xml:lang=\"en-US\">",
    `<voice name="${escapeSsml(voiceName)}">`,
    "<mstts:express-as style=\"chat\">",
    "<prosody rate=\"-4%\" pitch=\"+0%\">",
    escapedText,
    "</prosody>",
    "</mstts:express-as>",
    "</voice>",
    "</speak>"
  ].join("");
}

async function synthesizeWithAzure(text: string, config: AzureSpeechConfig): Promise<Response | null> {
  const response = await fetch(
    `https://${config.region}.tts.speech.microsoft.com/cognitiveservices/v1`,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/ssml+xml",
        "Ocp-Apim-Subscription-Key": config.key,
        "X-Microsoft-OutputFormat": config.outputFormat,
        "User-Agent": "Pixel-Edith-Demo"
      },
      body: azureSsml(text, config.voiceName)
    }
  );

  if (!response.ok) {
    const details = await response.text().catch(() => "");
    console.warn("Azure Speech TTS returned non-200:", response.status, details);
    return null;
  }

  const audioBuffer = await response.arrayBuffer();
  return new Response(audioBuffer, {
    headers: {
      "Content-Type": "audio/mpeg",
      "Cache-Control": "public, max-age=3600",
      "X-TTS-Engine": "azure-speech",
      "X-TTS-Voice": config.voiceName
    }
  });
}

function pcmToWav(
  pcmBuffer: Buffer,
  sampleRate = 24000,
  numChannels = 1,
  bitsPerSample = 16
): Buffer {
  const byteRate = (sampleRate * numChannels * bitsPerSample) / 8;
  const blockAlign = (numChannels * bitsPerSample) / 8;
  const dataSize = pcmBuffer.length;
  const header = Buffer.alloc(44);

  header.write("RIFF", 0);
  header.writeUInt32LE(36 + dataSize, 4);
  header.write("WAVE", 8);
  header.write("fmt ", 12);
  header.writeUInt32LE(16, 16);
  header.writeUInt16LE(1, 20);
  header.writeUInt16LE(numChannels, 22);
  header.writeUInt32LE(sampleRate, 24);
  header.writeUInt32LE(byteRate, 28);
  header.writeUInt16LE(blockAlign, 32);
  header.writeUInt16LE(bitsPerSample, 34);
  header.write("data", 36);
  header.writeUInt32LE(dataSize, 40);

  return Buffer.concat([header, pcmBuffer]);
}

async function synthesizeWithGemini(text: string, geminiKey: string): Promise<Response | null> {
  if (Date.now() <= geminiCooldownUntil) return null;

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
            voiceName: "Aoede"
          }
        }
      }
    }
  };

  const response = await fetch(
    `https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-preview-tts:generateContent?key=${geminiKey}`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    }
  );

  if (!response.ok) {
    const details = await response.text().catch(() => "");
    console.warn("Gemini TTS returned non-200:", response.status, details);
    if (response.status === 429) {
      geminiCooldownUntil = Date.now() + 5_000;
    }
    return null;
  }

  const data = await response.json();
  const base64Audio = data.candidates?.[0]?.content?.parts?.[0]?.inlineData?.data;
  if (!base64Audio) return null;

  geminiCooldownUntil = 0;
  const pcmBuffer = Buffer.from(base64Audio, "base64");
  const wavBuffer = pcmToWav(pcmBuffer, 24000, 1, 16);

  return new Response(new Uint8Array(wavBuffer), {
    headers: {
      "Content-Type": "audio/wav",
      "Cache-Control": "public, max-age=3600",
      "X-TTS-Engine": "gemini-2.5-flash"
    }
  });
}

async function synthesizeWithOpenAi(text: string, openaiKey: string): Promise<Response | null> {
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

  if (!response.ok) return null;

  const audioBuffer = await response.arrayBuffer();
  return new Response(audioBuffer, {
    headers: {
      "Content-Type": "audio/mpeg",
      "Cache-Control": "public, max-age=3600",
      "X-TTS-Engine": "openai-tts"
    }
  });
}

export async function POST(req: Request) {
  let body: TtsBody;
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ error: "Invalid JSON body" }, { status: 400 });
  }

  const text = body.text?.trim();
  if (!text) {
    return NextResponse.json({ error: "Text is required" }, { status: 400 });
  }

  const azureConfig = getAzureSpeechConfig();
  if (azureConfig) {
    try {
      const response = await synthesizeWithAzure(text, azureConfig);
      if (response) return response;
    } catch (error) {
      console.error("Azure Speech TTS failed:", error);
    }
  }

  const geminiKey = envValue("GEMINI_API_KEY");
  if (geminiKey) {
    try {
      const response = await synthesizeWithGemini(text, geminiKey);
      if (response) return response;
    } catch (error) {
      console.error("Gemini TTS failed:", error);
    }
  }

  const openaiKey = envValue("OPENAI_API_KEY");
  if (openaiKey) {
    try {
      const response = await synthesizeWithOpenAi(text, openaiKey);
      if (response) return response;
    } catch (error) {
      console.error("OpenAI TTS failed:", error);
    }
  }

  return NextResponse.json(
    { error: "No neural TTS provider is configured. Falling back to browser voice." },
    { status: 400 }
  );
}
