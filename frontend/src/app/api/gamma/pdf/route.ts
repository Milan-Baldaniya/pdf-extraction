import { NextResponse } from 'next/server';

export async function GET(request: Request) {
  const { searchParams } = new URL(request.url);
  const url = searchParams.get('url');

  if (!url) {
    return new NextResponse('Missing URL', { status: 400 });
  }

  try {
    const response = await fetch(url);
    if (!response.ok) {
      return new NextResponse('Failed to fetch PDF', { status: response.status });
    }

    const arrayBuffer = await response.arrayBuffer();
    
    // Serve as inline PDF to force the browser to render it in the iframe
    // instead of downloading it as an attachment.
    return new NextResponse(arrayBuffer, {
      headers: {
        'Content-Type': 'application/pdf',
        'Content-Disposition': 'inline; filename="presentation.pdf"',
      },
    });
  } catch (error: any) {
    return new NextResponse(`Error fetching PDF: ${error.message}`, { status: 500 });
  }
}
