import { CurriculumTableFill } from "@/components/curriculum-table-fill"
import { ChapterTableFill } from "@/components/chapter-table-fill"
import { SemanticTableFill } from "@/components/semantic-table-fill"
import { ExternalLink, FileText, ArrowLeft } from "lucide-react"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"

export default function TableFillPage() {
  return (
    <div className="flex min-h-screen flex-col bg-background relative overflow-hidden">
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

          <div className="flex items-center gap-3">
            <a
              href="/schema"
              className="flex items-center gap-1.5 rounded-full px-4 py-1.5 text-sm font-medium text-purple-600 dark:text-purple-400 bg-purple-500/10 hover:bg-purple-500/20 transition-all border-[0.5px] border-purple-500/20"
            >
              Schema Visualizer
            </a>
            <a
              href="/"
              className="flex items-center gap-1.5 rounded-full px-4 py-1.5 text-sm font-medium text-foreground/70 bg-black/5 dark:bg-white/5 hover:bg-black/10 dark:hover:bg-white/10 hover:text-foreground transition-all border-[0.5px] border-transparent hover:border-black/10 dark:hover:border-white/10"
            >
              <ArrowLeft className="h-3.5 w-3.5" />
              Back to Home
            </a>
          </div>
        </div>
      </header>

      <main className="mx-auto flex w-full max-w-screen-2xl flex-1 flex-col gap-6 p-4 pt-28 lg:p-6 lg:pt-28 relative z-10">
        <Tabs defaultValue="curriculum" className="w-full">
          <div className="flex justify-center mb-6">
            <TabsList className="bg-black/5 dark:bg-white/5 border border-black/5 dark:border-white/10 rounded-full p-1 inline-flex h-12 items-center justify-center">
              <TabsTrigger value="curriculum" className="rounded-full px-8 py-2 text-sm font-medium transition-all duration-300 data-[state=active]:bg-white dark:data-[state=active]:bg-black data-[state=active]:shadow-sm">Curriculum Queue</TabsTrigger>
              <TabsTrigger value="chapter" className="rounded-full px-8 py-2 text-sm font-medium transition-all duration-300 data-[state=active]:bg-white dark:data-[state=active]:bg-black data-[state=active]:shadow-sm">Chapters Queue</TabsTrigger>
              <TabsTrigger value="semantic" className="rounded-full px-8 py-2 text-sm font-medium transition-all duration-300 data-[state=active]:bg-white dark:data-[state=active]:bg-black data-[state=active]:shadow-sm">Semantic Intelligence</TabsTrigger>
            </TabsList>
          </div>
          <TabsContent value="curriculum" className="mt-0 focus-visible:outline-none">
            <CurriculumTableFill />
          </TabsContent>
          <TabsContent value="chapter" className="mt-0 focus-visible:outline-none">
            <ChapterTableFill />
          </TabsContent>
          <TabsContent value="semantic" className="mt-0 focus-visible:outline-none">
            <SemanticTableFill />
          </TabsContent>
        </Tabs>
      </main>

      <footer className="mt-auto border-t-[0.5px] border-black/5 dark:border-white/10 bg-white/30 dark:bg-black/30 backdrop-blur-[24px] saturate-150 py-4 relative z-10 shrink-0">
        <div className="mx-auto flex max-w-screen-2xl items-center justify-between px-4 text-xs text-muted-foreground/50 lg:px-8">
          <span>Educational PDF Intelligence</span>
          <span>MinerU CPU Pipeline</span>
        </div>
      </footer>
    </div>
  )
}
