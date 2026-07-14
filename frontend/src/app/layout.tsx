import type { Metadata } from "next";
import { Providers } from "@/lib/providers";
import "./globals.css";

export const metadata: Metadata = {
  title: "MinerU Extract — NCERT PDF Extractor",
  description:
    "Extract structured content from NCERT PDFs using MinerU. Get clean markdown output from any NCERT textbook chapter.",
  keywords: [
    "NCERT",
    "PDF extractor",
    "MinerU",
    "education",
    "markdown",
    "content extraction",
  ],
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      suppressHydrationWarning
      className="h-full antialiased"
    >
      <body suppressHydrationWarning className="min-h-full flex flex-col bg-slate-50 text-slate-900">
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
