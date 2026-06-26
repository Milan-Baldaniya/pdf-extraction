import { NextResponse } from 'next/server';

export async function POST(request: Request) {
  try {
    const { prompt, numCards } = await request.json();
    
    if (!prompt) {
      return NextResponse.json({ error: 'Prompt is required' }, { status: 400 });
    }

    const apiKey = process.env.GAMMA_API_KEY;
    if (!apiKey) {
      return NextResponse.json({ error: 'GAMMA_API_KEY is not configured in .env' }, { status: 500 });
    }

    const response = await fetch('https://public-api.gamma.app/v1.0/generations', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-API-KEY': apiKey,
      },
      body: JSON.stringify({
        inputText: prompt,
        textMode: "generate",
        format: "presentation",
        numCards: numCards || 10,
        exportAs: "pdf",
        temperature: 0.7,
        frequencyPenalty: 0.5,
        presencePenalty: 0.5,
      }),
    });

    if (!response.ok) {
      const errorData = await response.text();
      throw new Error(`Gamma API Error: ${response.status} - ${errorData}`);
    }

    const data = await response.json();
    return NextResponse.json(data);
  } catch (error: any) {
    console.error("Gamma generation error:", error);
    return NextResponse.json({ error: error.message }, { status: 500 });
  }
}
