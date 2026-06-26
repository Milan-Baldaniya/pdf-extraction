import { NextResponse } from 'next/server';

export async function GET(request: Request, { params }: { params: Promise<{ id: string }> }) {
  try {
    const resolvedParams = await params;
    const generationId = resolvedParams.id;
    
    if (!generationId) {
      return NextResponse.json({ error: 'generationId is required' }, { status: 400 });
    }

    const apiKey = process.env.GAMMA_API_KEY;
    if (!apiKey) {
      return NextResponse.json({ error: 'GAMMA_API_KEY is not configured in .env' }, { status: 500 });
    }

    const response = await fetch(`https://public-api.gamma.app/v1.0/generations/${generationId}`, {
      method: 'GET',
      headers: {
        'Content-Type': 'application/json',
        'X-API-KEY': apiKey,
      },
    });

    if (!response.ok) {
      const errorData = await response.text();
      throw new Error(`Gamma API Error: ${response.status} - ${errorData}`);
    }

    const data = await response.json();
    return NextResponse.json(data);
  } catch (error: any) {
    console.error("Gamma status error:", error);
    return NextResponse.json({ error: error.message }, { status: 500 });
  }
}
