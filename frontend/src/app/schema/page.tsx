import { SchemaVisualizer } from "@/components/schema-visualizer"
import { FileText, ArrowLeft } from "lucide-react"

export default function SchemaPage() {
  return (
    <div className="flex h-screen w-full flex-col bg-background relative overflow-hidden">
      {/* iOS Liquid Glass Background */}
      <div className="absolute top-[-15%] left-[-10%] w-[50%] h-[50%] rounded-[100%] bg-blue-500/30 dark:bg-blue-600/20 blur-[140px] mix-blend-normal opacity-80 pointer-events-none animate-pulse" />
      <div className="absolute bottom-[-10%] right-[-10%] w-[60%] h-[60%] rounded-[100%] bg-purple-500/30 dark:bg-purple-600/20 blur-[140px] mix-blend-normal opacity-80 pointer-events-none animate-pulse" style={{ animationDelay: '2s' }} />
      <div className="absolute top-[20%] right-[10%] w-[30%] h-[30%] rounded-[100%] bg-pink-500/20 dark:bg-pink-600/20 blur-[120px] mix-blend-normal opacity-60 pointer-events-none animate-pulse" style={{ animationDelay: '4s' }} />
      
      <header className="absolute top-4 left-1/2 -translate-x-1/2 z-50 w-[96%] max-w-[1600px] rounded-full border-[0.5px] border-black/10 dark:border-white/20 bg-white/40 dark:bg-black/40 backdrop-blur-[40px] saturate-200 shadow-[0_8px_32px_0_rgba(0,0,0,0.1)] px-5 py-2.5 transition-all hover:bg-white/50 dark:hover:bg-black/50 overflow-hidden before:absolute before:inset-0 before:-z-10 before:rounded-full before:bg-gradient-to-br before:from-white/40 before:to-transparent before:opacity-50 dark:before:from-white/10 dark:before:to-transparent">
        <div className="flex h-10 items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="flex h-9 w-9 items-center justify-center rounded-full bg-primary/10 shadow-inner border-[0.5px] border-primary/20">
              <FileText className="h-4 w-4 text-primary" />
            </div>
            <span className="text-[17px] font-semibold tracking-tight text-foreground/90">
              SCHEMA VISUALIZER
            </span>
          </div>

          <div className="flex items-center gap-3">
            <a
              href="/table-fill"
              className="flex items-center gap-1.5 rounded-full px-4 py-1.5 text-sm font-medium text-foreground/70 bg-black/5 dark:bg-white/5 hover:bg-black/10 dark:hover:bg-white/10 hover:text-foreground transition-all border-[0.5px] border-transparent hover:border-black/10 dark:hover:border-white/10"
            >
              <ArrowLeft className="h-3.5 w-3.5" />
              Back to Fill Data
            </a>
          </div>
        </div>
      </header>

      <main className="mx-auto flex w-full max-w-[1600px] flex-1 flex-col p-4 pt-24 lg:p-6 lg:pt-24 relative z-10 overflow-hidden">
        <SchemaVisualizer />
      </main>
    </div>
  )
}
