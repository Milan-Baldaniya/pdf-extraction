"use client";

import { useState } from "react";
import type { ExtractionResponse } from "@/lib/api";
import { ExtractionForm } from "@/components/extraction-form";
import { ExtractionViewer } from "@/components/extraction-viewer";
import { Cpu, ExternalLink, FileText } from "lucide-react";

export default function HomePage() {
  const [extraction, setExtraction] = useState<ExtractionResponse | null>(null);

  return (
    <div className="flex min-h-screen flex-col bg-background relative overflow-hidden">
      {/* iOS Liquid Glass Background */}
      <div className="absolute top-[-15%] left-[-10%] w-[50%] h-[50%] rounded-[100%] bg-blue-500/30 dark:bg-blue-600/20 blur-[140px] mix-blend-normal opacity-80 pointer-events-none animate-pulse" />
      <div className="absolute bottom-[-10%] right-[-10%] w-[60%] h-[60%] rounded-[100%] bg-purple-500/30 dark:bg-purple-600/20 blur-[140px] mix-blend-normal opacity-80 pointer-events-none animate-pulse" style={{ animationDelay: '2s' }} />
      <div className="absolute top-[20%] right-[10%] w-[30%] h-[30%] rounded-[100%] bg-pink-500/20 dark:bg-pink-600/20 blur-[120px] mix-blend-normal opacity-60 pointer-events-none animate-pulse" style={{ animationDelay: '4s' }} />
      
      <header className="sticky top-0 z-50 border-b-[0.5px] border-black/5 dark:border-white/10 bg-white/40 dark:bg-black/40 backdrop-blur-[24px] saturate-150 shadow-[0_4px_30px_rgba(0,0,0,0.05)]">
        <div className="mx-auto flex h-14 max-w-screen-2xl items-center justify-between px-4 lg:px-8">
          <div className="flex items-center gap-2.5">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary/10 shadow-md">
              <FileText className="h-4 w-4 text-primary" />
            </div>
            <span className="text-[17px] font-semibold tracking-tight text-foreground/90">
              PDF EXTRACTOR
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

      <main className={`mx-auto flex w-full max-w-screen-2xl flex-1 gap-0 p-4 lg:gap-6 lg:p-8 relative z-10 ${!extraction ? 'items-center justify-center' : ''}`}>
        <aside
          className={`shrink-0 transition-all duration-500 ease-out ${
            extraction
              ? "w-full lg:w-[380px] xl:w-[420px]"
              : "w-full max-w-2xl"
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
      </main>

      <footer className="border-t-[0.5px] border-black/5 dark:border-white/10 bg-white/30 dark:bg-black/30 backdrop-blur-[24px] saturate-150 py-4 relative z-10">
        <div className="mx-auto flex max-w-screen-2xl items-center justify-between px-4 text-xs text-muted-foreground/50 lg:px-8">
          <span>Educational PDF Intelligence</span>
          <span>MinerU CPU Pipeline</span>
        </div>
      </footer>
    </div>
  );
}
