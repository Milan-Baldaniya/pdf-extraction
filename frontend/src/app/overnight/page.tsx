import { OvernightRunner } from "@/components/overnight-runner"
import { Moon, ArrowLeft, FileText } from "lucide-react"

export default function OvernightPage() {
  return (
    <div className="flex min-h-screen flex-col bg-background relative overflow-hidden">
      {/* iOS Liquid Glass Background */}
      <div className="absolute top-[-15%] left-[-10%] w-[50%] h-[50%] rounded-[100%] bg-indigo-500/30 dark:bg-indigo-600/20 blur-[140px] mix-blend-normal opacity-80 pointer-events-none animate-pulse" />
      <div className="absolute bottom-[-10%] right-[-10%] w-[60%] h-[60%] rounded-[100%] bg-purple-500/30 dark:bg-purple-600/20 blur-[140px] mix-blend-normal opacity-80 pointer-events-none animate-pulse" style={{ animationDelay: '2s' }} />
      <div className="absolute top-[20%] right-[10%] w-[30%] h-[30%] rounded-[100%] bg-blue-500/20 dark:bg-blue-600/20 blur-[120px] mix-blend-normal opacity-60 pointer-events-none animate-pulse" style={{ animationDelay: '4s' }} />

      <header className="fixed top-4 left-1/2 -translate-x-1/2 z-50 w-[96%] max-w-[1600px] rounded-full border-[0.5px] border-black/10 dark:border-white/20 bg-white/40 dark:bg-black/40 backdrop-blur-[40px] saturate-200 shadow-[0_8px_32px_0_rgba(0,0,0,0.1)] px-5 py-2.5 transition-all hover:bg-white/50 dark:hover:bg-black/50">
        <div className="flex h-10 items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="flex h-9 w-9 items-center justify-center rounded-full bg-indigo-500/10 shadow-inner border-[0.5px] border-indigo-500/20">
              <Moon className="h-4 w-4 text-indigo-600 dark:text-indigo-400" />
            </div>
            <span className="text-[17px] font-semibold tracking-tight text-foreground/90">
              OVERNIGHT EXTRACTION
            </span>
          </div>

          <div className="flex items-center gap-3">
            <a
              href="/table-fill"
              className="flex items-center gap-1.5 rounded-full px-4 py-1.5 text-sm font-medium text-primary bg-primary/10 hover:bg-primary/20 transition-all border-[0.5px] border-primary/20"
            >
              <FileText className="h-3.5 w-3.5" />
              Queues
            </a>
            <a
              href="/"
              className="flex items-center gap-1.5 rounded-full px-4 py-1.5 text-sm font-medium text-foreground/70 hover:bg-black/5 dark:hover:bg-white/10 transition-all"
            >
              <ArrowLeft className="h-3.5 w-3.5" />
              Home
            </a>
          </div>
        </div>
      </header>

      <main className="relative z-10 w-full flex-1 px-4 pb-16 pt-28 md:px-6">
        <div className="mx-auto mb-6 w-full max-w-5xl px-1">
          <h1 className="text-3xl font-bold tracking-tight">Extract chapters overnight</h1>
          <p className="mt-1.5 max-w-3xl text-muted-foreground">
            Start it before you leave, stop it when you arrive. It works through the queue sheet
            two chapters at a time, subject by subject, and keeps going on its own — a broken
            link or a failed chapter never stops the rest. Closing this page does not stop it.
          </p>
        </div>
        <OvernightRunner />
      </main>
    </div>
  )
}
