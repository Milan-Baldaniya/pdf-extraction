"use client";

import { useState } from "react";
import type { ExtractionResponse } from "@/lib/api";
import { ExtractionForm } from "@/components/extraction-form";
import { ExtractionViewer } from "@/components/extraction-viewer";
import { Cpu, ExternalLink, FileText } from "lucide-react";

export default function HomePage() {
  const [extraction, setExtraction] = useState<ExtractionResponse | null>(null);

  return (
    <div className="flex min-h-screen flex-col bg-background">
      <header className="sticky top-0 z-50 border-b border-border/40 bg-background/80 backdrop-blur-xl">
        <div className="mx-auto flex h-14 max-w-screen-2xl items-center justify-between px-4 lg:px-8">
          <div className="flex items-center gap-2.5">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary/10 shadow-md">
              <FileText className="h-4 w-4 text-primary" />
            </div>
            <span className="text-lg font-bold tracking-tight">
              EduExtract
              <span className="font-normal text-muted-foreground"> CPU</span>
            </span>
          </div>

          <a
            href="https://github.com/opendatalab/MinerU"
            target="_blank"
            rel="noopener noreferrer"
            className="flex items-center gap-1.5 text-sm text-muted-foreground transition-colors hover:text-foreground"
          >
            <ExternalLink className="h-4 w-4" />
            MinerU
          </a>
        </div>
      </header>

      <main className="mx-auto flex w-full max-w-screen-2xl flex-1 gap-0 p-4 lg:gap-6 lg:p-8">
        <aside
          className={`shrink-0 transition-all duration-500 ease-out ${
            extraction
              ? "w-full lg:w-[380px] xl:w-[420px]"
              : "w-full lg:w-1/2 xl:w-[540px]"
          }`}
        >
          <div className="sticky top-24">
            <ExtractionForm onSuccess={(data) => setExtraction(data)} />
          </div>
        </aside>

        {extraction && (
          <section className="mt-6 min-w-0 flex-1 lg:mt-0">
            <ExtractionViewer
              data={extraction}
              onReset={() => setExtraction(null)}
            />
          </section>
        )}

        {!extraction && (
          <section className="hidden flex-1 items-center justify-center lg:flex">
            <div className="w-full max-w-md rounded-lg border border-border/30 bg-card/40 p-6 shadow-xl">
              <div className="mb-5 flex items-center gap-3">
                <div className="flex h-10 w-10 items-center justify-center rounded-md bg-primary/10">
                  <Cpu className="h-5 w-5 text-primary" />
                </div>
                <div>
                  <p className="text-sm font-medium">Ready for extraction</p>
                  <p className="text-xs text-muted-foreground">
                    CPU pipeline mode is active
                  </p>
                </div>
              </div>
              <div className="grid gap-3">
                {[
                  "OCR + layout analysis",
                  "Tables and formulas",
                  "Images, captions, and diagnostics",
                ].map((item) => (
                  <div
                    key={item}
                    className="flex items-center gap-3 rounded-md border border-border/20 bg-background/40 px-3 py-2 text-sm text-muted-foreground"
                  >
                    <FileText className="h-4 w-4 text-muted-foreground/70" />
                    {item}
                  </div>
                ))}
              </div>
            </div>
          </section>
        )}
      </main>

      <footer className="border-t border-border/20 py-4">
        <div className="mx-auto flex max-w-screen-2xl items-center justify-between px-4 text-xs text-muted-foreground/50 lg:px-8">
          <span>NCERT Educational PDF Intelligence</span>
          <span>MinerU CPU Pipeline + FastAPI</span>
        </div>
      </footer>
    </div>
  );
}
