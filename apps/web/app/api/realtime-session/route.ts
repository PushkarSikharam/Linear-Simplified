import { NextResponse } from "next/server";

export async function GET() {
  const apiKey = process.env.OPENAI_API_KEY;

  if (!apiKey || apiKey.trim() === "" || apiKey === "your_openai_api_key_here") {
    return NextResponse.json({
      success: false,
      mode: "local",
      reason: "No OPENAI_API_KEY configured in environment. Using Enhanced Web Audio Voice Engine."
    });
  }

  try {
    const response = await fetch("https://api.openai.com/v1/realtime/sessions", {
      method: "POST",
      headers: {
        Authorization: `Bearer ${apiKey}`,
        "Content-Type": "application/json"
      },
      body: JSON.stringify({
        model: "gpt-4o-realtime-preview",
        modalities: ["audio", "text"],
        voice: "coral",
        instructions:
          "You are Edith, the product guide for Pixel (Linear Simplified). Speak naturally, concisely, and conversationally like a human product manager."
      })
    });

    if (!response.ok) {
      const errorText = await response.text();
      return NextResponse.json({
        success: false,
        mode: "local",
        reason: `OpenAI API returned ${response.status}: ${errorText}`
      });
    }

    const data = await response.json();
    return NextResponse.json({
      success: true,
      mode: "webrtc",
      client_secret: data.client_secret?.value ?? data.value,
      session: data
    });
  } catch (error) {
    return NextResponse.json({
      success: false,
      mode: "local",
      reason: `Failed to connect to OpenAI API: ${error instanceof Error ? error.message : String(error)}`
    });
  }
}
