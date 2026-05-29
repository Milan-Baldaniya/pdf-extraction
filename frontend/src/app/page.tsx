"use client";

import { useState } from "react";
import type { ExtractionResponse } from "@/lib/api";
import { ExtractionForm } from "@/components/extraction-form";
import { ExtractionViewer } from "@/components/extraction-viewer";
import { Cpu, ExternalLink, FileText } from "lucide-react";

export default function HomePage() {
  const [extraction, setExtraction] = useState<ExtractionResponse | null>(null);

  return (
    <div className="flex h-[100dvh] max-h-[100dvh] flex-col bg-background relative overflow-hidden">
      {/* iOS Liquid Glass Background */}
      <div className="absolute top-[-15%] left-[-10%] w-[50%] h-[50%] rounded-[100%] bg-blue-500/30 dark:bg-blue-600/20 blur-[140px] mix-blend-normal opacity-80 pointer-events-none animate-pulse" />
      <div className="absolute bottom-[-10%] right-[-10%] w-[60%] h-[60%] rounded-[100%] bg-purple-500/30 dark:bg-purple-600/20 blur-[140px] mix-blend-normal opacity-80 pointer-events-none animate-pulse" style={{ animationDelay: '2s' }} />
      <div className="absolute top-[20%] right-[10%] w-[30%] h-[30%] rounded-[100%] bg-pink-500/20 dark:bg-pink-600/20 blur-[120px] mix-blend-normal opacity-60 pointer-events-none animate-pulse" style={{ animationDelay: '4s' }} />
      
      <header className="fixed top-4 left-1/2 -translate-x-1/2 z-50 w-[96%] max-w-[1600px] rounded-full border-[0.5px] border-black/10 dark:border-white/20 bg-white/40 dark:bg-black/40 backdrop-blur-[40px] saturate-200 shadow-[0_8px_32px_0_rgba(0,0,0,0.1)] px-5 py-2.5 transition-all hover:bg-white/50 dark:hover:bg-black/50 overflow-hidden before:absolute before:inset-0 before:-z-10 before:rounded-full before:bg-gradient-to-br before:from-white/40 before:to-transparent before:opacity-50 dark:before:from-white/10 dark:before:to-transparent">
        <div className="flex h-10 items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="flex h-9 w-9 items-center justify-center rounded-full bg-primary/10 shadow-inner border-[0.5px] border-primary/20">
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
            className="flex items-center gap-1.5 rounded-full px-4 py-1.5 text-sm font-medium text-foreground/70 bg-black/5 dark:bg-white/5 hover:bg-black/10 dark:hover:bg-white/10 hover:text-foreground transition-all border-[0.5px] border-transparent hover:border-black/10 dark:hover:border-white/10"
          >
            MinerU Pipeline
            <ExternalLink className="h-3.5 w-3.5" />
          </a>
        </div>
      </header>

      <main className={`mx-auto flex w-full max-w-screen-2xl flex-1 flex-col lg:flex-row gap-0 p-4 pt-24 lg:gap-6 lg:p-6 lg:pt-24 relative z-10 min-h-0 ${!extraction ? 'items-center justify-center' : ''}`}>
        <aside
          className={`shrink-0 transition-all duration-500 ease-out flex flex-col min-h-0 h-full ${
            extraction
              ? "w-full lg:w-[380px] xl:w-[420px]"
              : "w-full max-w-2xl"
          }`}
        >
          <ExtractionForm onSuccess={(data) => setExtraction(data)} />
        </aside>

        {extraction && (
          <section className="mt-6 min-w-0 flex-1 lg:mt-0 flex flex-col min-h-0 h-full">
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
