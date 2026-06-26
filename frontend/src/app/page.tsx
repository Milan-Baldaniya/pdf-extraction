"use client";

import { useState } from "react";
import Link from "next/link";
import { BookOpen, FileText, Database, ArrowRight, BrainCircuit, Sparkles, MonitorPlay, Presentation } from "lucide-react";

export default function MainLandingPage() {
  const [isGenerateModalOpen, setIsGenerateModalOpen] = useState(false);

  return (
    <div className="flex h-[100dvh] max-h-[100dvh] flex-col bg-background relative overflow-hidden items-center justify-center">
      {/* iOS Liquid Glass Background */}
      <div className="absolute top-[-15%] left-[-10%] w-[50%] h-[50%] rounded-[100%] bg-blue-500/30 dark:bg-blue-600/20 blur-[140px] mix-blend-normal opacity-80 pointer-events-none animate-pulse" />
      <div className="absolute bottom-[-10%] right-[-10%] w-[60%] h-[60%] rounded-[100%] bg-purple-500/30 dark:bg-purple-600/20 blur-[140px] mix-blend-normal opacity-80 pointer-events-none animate-pulse" style={{ animationDelay: '2s' }} />
      <div className="absolute top-[20%] right-[10%] w-[30%] h-[30%] rounded-[100%] bg-pink-500/20 dark:bg-pink-600/20 blur-[120px] mix-blend-normal opacity-60 pointer-events-none animate-pulse" style={{ animationDelay: '4s' }} />
      
      <header className="fixed top-4 left-1/2 -translate-x-1/2 z-50 w-[96%] max-w-[1600px] rounded-full border-[0.5px] border-black/10 dark:border-white/20 bg-white/40 dark:bg-black/40 backdrop-blur-[40px] saturate-200 shadow-[0_8px_32px_0_rgba(0,0,0,0.1)] px-5 py-2.5 transition-all hover:bg-white/50 dark:hover:bg-black/50 overflow-hidden before:absolute before:inset-0 before:-z-10 before:rounded-full before:bg-gradient-to-br before:from-white/40 before:to-transparent before:opacity-50 dark:before:from-white/10 dark:before:to-transparent">
        <div className="flex h-10 items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="flex h-9 w-9 items-center justify-center rounded-full bg-primary/10 shadow-inner border-[0.5px] border-primary/20">
              <BrainCircuit className="h-5 w-5 text-primary" />
            </div>
            <span className="text-[17px] font-semibold tracking-tight text-foreground/90">
              LMS INTELLIGENCE SUITE
            </span>
          </div>
        </div>
      </header>

      <main className="relative z-10 w-full max-w-5xl px-6 py-20 flex flex-col items-center justify-center">
        <div className="text-center mb-16">
          <h1 className="text-4xl md:text-5xl font-bold tracking-tight text-foreground mb-4">
            Welcome to the Intelligence Suite
          </h1>
          <p className="text-lg text-muted-foreground max-w-2xl mx-auto">
            Select an engine to proceed. Generate highly tailored AI lesson plans or extract structured knowledge directly into your LMS.
          </p>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-8 w-full max-w-6xl mx-auto">
          {/* Card 1: Lesson Plan */}
          <Link href="/master-calendar" className="group">
            <div className="h-full relative overflow-hidden rounded-3xl border-[0.5px] border-black/10 dark:border-white/20 bg-white/40 dark:bg-black/40 backdrop-blur-[40px] saturate-200 shadow-[0_8px_32px_0_rgba(0,0,0,0.1)] p-8 transition-all duration-300 hover:scale-[1.02] hover:bg-white/60 dark:hover:bg-black/60 before:absolute before:inset-0 before:-z-10 before:bg-gradient-to-br before:from-blue-500/10 before:to-purple-500/5 before:opacity-50 group-hover:before:opacity-100 flex flex-col items-center text-center">
              <div className="flex h-16 w-16 items-center justify-center rounded-full bg-blue-500/10 shadow-inner border-[0.5px] border-blue-500/20 mb-4 group-hover:bg-blue-500/20 transition-colors">
                <BookOpen className="h-8 w-8 text-blue-600 dark:text-blue-400" />
              </div>
              <h2 className="text-xl font-bold text-foreground mb-2">
                Lesson Plan
              </h2>
              <p className="text-sm text-muted-foreground flex-1 mb-6">
                Create comprehensive Macro, Meso, and Micro lesson plans utilizing existing LMS capacity and semantic intelligence data.
              </p>
              <div className="mt-auto px-6 py-2.5 text-sm rounded-full border-[0.5px] border-black/10 dark:border-white/20 bg-white/40 dark:bg-black/40 backdrop-blur-[40px] saturate-200 shadow-[0_8px_32px_0_rgba(0,0,0,0.1)] text-foreground font-semibold transition-all flex items-center justify-center gap-2 group-hover:bg-blue-500/10 group-hover:text-blue-600 dark:group-hover:text-blue-400 border-transparent group-hover:border-blue-500/20">
                Launch Engine <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-1" />
              </div>
            </div>
          </Link>

          {/* Card 2: Extract Data */}
          <Link href="/extract" className="group">
            <div className="h-full relative overflow-hidden rounded-3xl border-[0.5px] border-black/10 dark:border-white/20 bg-white/40 dark:bg-black/40 backdrop-blur-[40px] saturate-200 shadow-[0_8px_32px_0_rgba(0,0,0,0.1)] p-8 transition-all duration-300 hover:scale-[1.02] hover:bg-white/60 dark:hover:bg-black/60 before:absolute before:inset-0 before:-z-10 before:bg-gradient-to-br before:from-purple-500/10 before:to-pink-500/5 before:opacity-50 group-hover:before:opacity-100 flex flex-col items-center text-center">
              <div className="flex h-16 w-16 items-center justify-center rounded-full bg-purple-500/10 shadow-inner border-[0.5px] border-purple-500/20 mb-4 group-hover:bg-purple-500/20 transition-colors">
                <Database className="h-8 w-8 text-purple-600 dark:text-purple-400" />
              </div>
              <h2 className="text-xl font-bold text-foreground mb-2">
                Extract Data & Fill LMS
              </h2>
              <p className="text-sm text-muted-foreground flex-1 mb-6">
                Extract concepts, learning outcomes, abilities, and semantic intelligence from educational PDFs directly into your LMS tables.
              </p>
              <div className="mt-auto px-6 py-2.5 text-sm rounded-full border-[0.5px] border-black/10 dark:border-white/20 bg-white/40 dark:bg-black/40 backdrop-blur-[40px] saturate-200 shadow-[0_8px_32px_0_rgba(0,0,0,0.1)] text-foreground font-semibold transition-all flex items-center justify-center gap-2 group-hover:bg-purple-500/10 group-hover:text-purple-600 dark:group-hover:text-purple-400 border-transparent group-hover:border-purple-500/20">
                Launch Engine <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-1" />
              </div>
            </div>
          </Link>

          {/* Card 3: Generate Content */}
          <div onClick={() => setIsGenerateModalOpen(true)} className="group cursor-pointer">
            <div className="h-full relative overflow-hidden rounded-3xl border-[0.5px] border-black/10 dark:border-white/20 bg-white/40 dark:bg-black/40 backdrop-blur-[40px] saturate-200 shadow-[0_8px_32px_0_rgba(0,0,0,0.1)] p-8 transition-all duration-300 hover:scale-[1.02] hover:bg-white/60 dark:hover:bg-black/60 before:absolute before:inset-0 before:-z-10 before:bg-gradient-to-br before:from-amber-500/10 before:to-orange-500/5 before:opacity-50 group-hover:before:opacity-100 flex flex-col items-center text-center">
              <div className="flex h-16 w-16 items-center justify-center rounded-full bg-amber-500/10 shadow-inner border-[0.5px] border-amber-500/20 mb-4 group-hover:bg-amber-500/20 transition-colors">
                <Sparkles className="h-8 w-8 text-amber-600 dark:text-amber-400" />
              </div>
              <h2 className="text-xl font-bold text-foreground mb-2">
                Generate Content
              </h2>
              <p className="text-sm text-muted-foreground flex-1 mb-6">
                Instantly create interactive classroom materials or comprehensive teacher training modules using AI.
              </p>
              <div className="mt-auto px-6 py-2.5 text-sm rounded-full border-[0.5px] border-black/10 dark:border-white/20 bg-white/40 dark:bg-black/40 backdrop-blur-[40px] saturate-200 shadow-[0_8px_32px_0_rgba(0,0,0,0.1)] text-foreground font-semibold transition-all flex items-center justify-center gap-2 group-hover:bg-amber-500/10 group-hover:text-amber-600 dark:group-hover:text-amber-400 border-transparent group-hover:border-amber-500/20">
                Open Menu <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-1" />
              </div>
            </div>
          </div>
        </div>
      </main>

      {/* GENERATE CONTENT MODAL */}
      {isGenerateModalOpen && (
        <div className="fixed inset-0 z-[100] flex items-center justify-center p-4">
          {/* Backdrop */}
          <div 
            className="absolute inset-0 bg-black/20 dark:bg-black/40 backdrop-blur-sm transition-opacity" 
            onClick={() => setIsGenerateModalOpen(false)}
          />
          
          {/* Modal Container */}
          <div className="relative w-full max-w-3xl bg-white/80 dark:bg-[#111111]/80 backdrop-blur-[60px] rounded-[2.5rem] border border-white/40 dark:border-white/10 shadow-2xl overflow-hidden p-10 animate-in fade-in zoom-in-95 duration-300">
            
            <button 
              onClick={() => setIsGenerateModalOpen(false)}
              className="absolute top-6 right-6 w-10 h-10 flex items-center justify-center rounded-full bg-black/5 dark:bg-white/5 hover:bg-black/10 dark:hover:bg-white/10 transition-colors text-slate-500 dark:text-slate-400"
            >
              ✕
            </button>

            <div className="text-center mb-10">
              <h2 className="text-3xl font-bold text-slate-800 dark:text-slate-100 mb-3">Select Generation Type</h2>
              <p className="text-slate-500 dark:text-slate-400 max-w-xl mx-auto">Choose what type of content you want the intelligence engine to generate based on your LMS data.</p>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
              {/* Classroom Content Box */}
              <Link href="/generate/classroom-content" className="group cursor-pointer h-full relative overflow-hidden rounded-3xl border border-black/10 dark:border-white/10 bg-white/50 dark:bg-black/50 hover:bg-white dark:hover:bg-black/80 transition-all duration-300 p-8 flex flex-col items-center text-center shadow-sm hover:shadow-xl hover:-translate-y-1">
                <div className="absolute inset-0 bg-gradient-to-br from-emerald-500/5 to-transparent opacity-0 group-hover:opacity-100 transition-opacity" />
                <div className="flex h-16 w-16 items-center justify-center rounded-full bg-emerald-500/10 mb-5 group-hover:scale-110 transition-transform shadow-inner border border-emerald-500/20">
                  <MonitorPlay className="h-8 w-8 text-emerald-600 dark:text-emerald-400" />
                </div>
                <h3 className="text-xl font-bold text-foreground mb-2">Classroom Content</h3>
                <p className="text-sm text-muted-foreground">Generate slides, interactive quizzes, worksheets, and reading materials for student consumption.</p>
              </Link>

              {/* Teacher Training Box */}
              <Link href="/generate/teacher-training" className="group cursor-pointer h-full relative overflow-hidden rounded-3xl border border-black/10 dark:border-white/10 bg-white/50 dark:bg-black/50 hover:bg-white dark:hover:bg-black/80 transition-all duration-300 p-8 flex flex-col items-center text-center shadow-sm hover:shadow-xl hover:-translate-y-1">
                <div className="absolute inset-0 bg-gradient-to-br from-indigo-500/5 to-transparent opacity-0 group-hover:opacity-100 transition-opacity" />
                <div className="flex h-16 w-16 items-center justify-center rounded-full bg-indigo-500/10 mb-5 group-hover:scale-110 transition-transform shadow-inner border border-indigo-500/20">
                  <Presentation className="h-8 w-8 text-indigo-600 dark:text-indigo-400" />
                </div>
                <h3 className="text-xl font-bold text-foreground mb-2">Teacher Training</h3>
                <p className="text-sm text-muted-foreground">Generate comprehensive delivery guides, pedagogical strategies, and assessment rubrics for educators.</p>
              </Link>
            </div>
          </div>
        </div>
      )}

      <footer className="absolute bottom-0 w-full border-t-[0.5px] border-black/5 dark:border-white/10 bg-white/30 dark:bg-black/30 backdrop-blur-[24px] saturate-150 py-4 z-10">
        <div className="mx-auto flex max-w-screen-2xl items-center justify-between px-4 text-xs text-muted-foreground/50 lg:px-8">
          <span>LMS Intelligence Suite</span>
          <span>Powered by Agentic AI</span>
        </div>
      </footer>
    </div>
  );
}
