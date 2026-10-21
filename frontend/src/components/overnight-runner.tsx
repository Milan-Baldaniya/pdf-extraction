"use client"

/**
 * The overnight extraction queue, as one page.
 *
 * Three things a person needs, in the order they need them:
 *
 *   1. Start it before going home, stop it on arriving. One button, which is
 *      whichever of those two is currently possible.
 *   2. "What did it do last night?" answered in a sentence, before any table.
 *   3. The detail underneath, for the morning it did something surprising.
 *
 * The queue runs as a detached process on the server, so this page is a reader.
 * Nothing here holds the run open: closing the tab, or the laptop, does not
 * stop it -- which is the entire point.
 */

import { useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import {
  AlertTriangle,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Clock,
  Cpu,
  FileText,
  Loader2,
  MemoryStick,
  Moon,
  Play,
  RefreshCw,
  ScrollText,
  Square,
  XCircle,
} from "lucide-react"
import {
  fetchNightLog,
  fetchNights,
  fetchQueueOverview,
  fetchQueueStatus,
  startQueue,
  stopQueue,
  type Night,
  type QueueStatus,
} from "@/lib/api"

const GLASS =
  "rounded-3xl border-[0.5px] border-black/10 dark:border-white/20 bg-white/50 dark:bg-black/40 backdrop-blur-[40px] saturate-200 shadow-[0_8px_32px_0_rgba(0,0,0,0.08)]"

/** How a status reads to someone who has never seen this page before. */
const STATUS_WORDS: Record<string, { label: string; tone: string; help: string }> = {
  idle: {
    label: "Not running",
    tone: "bg-black/5 text-foreground/70 dark:bg-white/10 dark:text-white/70",
    help: "Nothing is extracting. Press Start to begin tonight's run.",
  },
  running: {
    label: "Running",
    tone: "bg-green-500/15 text-green-700 dark:text-green-400 border-green-500/30",
    help: "Chapters are being extracted right now. You can close this tab safely.",
  },
  stopping: {
    label: "Stopping",
    tone: "bg-amber-500/15 text-amber-700 dark:text-amber-400 border-amber-500/30",
    help: "Finishing the chapter already in progress, then it will stop.",
  },
  finished: {
    label: "Finished",
    tone: "bg-blue-500/15 text-blue-700 dark:text-blue-400 border-blue-500/30",
    help: "Every chapter in the queue was dealt with.",
  },
  stopped: {
    label: "Stopped by you",
    tone: "bg-blue-500/15 text-blue-700 dark:text-blue-400 border-blue-500/30",
    help: "The run stopped when you asked it to. Unfinished chapters stay pending.",
  },
  interrupted: {
    label: "Interrupted",
    tone: "bg-amber-500/15 text-amber-700 dark:text-amber-400 border-amber-500/30",
    help: "The run was cut short. Everything it finished was saved.",
  },
  crashed: {
    label: "Ended unexpectedly",
    tone: "bg-red-500/15 text-red-700 dark:text-red-400 border-red-500/30",
    help: "The computer slept, shut down, or the window was closed. Finished chapters are safe.",
  },
}

const CHAPTER_TONE: Record<string, string> = {
  done: "bg-green-500/15 text-green-700 dark:text-green-400",
  skipped: "bg-black/5 text-foreground/60 dark:bg-white/10 dark:text-white/60",
  failed: "bg-red-500/15 text-red-700 dark:text-red-400",
  extracted: "bg-amber-500/15 text-amber-700 dark:text-amber-400",
  running: "bg-blue-500/15 text-blue-700 dark:text-blue-400",
  pending: "bg-black/5 text-foreground/60 dark:bg-white/10 dark:text-white/60",
  disabled: "bg-black/5 text-foreground/40 dark:bg-white/5 dark:text-white/40",
}

/** Plain words for the sheet/ledger status values. */
const CHAPTER_WORDS: Record<string, string> = {
  done: "Extracted",
  skipped: "Already had it",
  failed: "Failed",
  extracted: "Extracted, not saved",
  running: "Was in progress",
  pending: "Waiting",
  disabled: "Turned off",
}

/** "class9_cbse_queue.xlsx" -> "Class 9 CBSE". A filename is not a label. */
function prettySheet(name: string): string {
  const stem = name.replace(/\.xlsx$/i, "").replace(/_queue$/i, "")
  return stem
    .split("_")
    .map((part) =>
      /^class\d+$/i.test(part)
        ? `Class ${part.replace(/\D/g, "")}`
        : part.length <= 5
          ? part.toUpperCase()
          : part.charAt(0).toUpperCase() + part.slice(1)
    )
    .join(" ")
}

function Pill({ tone, children }: { tone: string; children: React.ReactNode }) {
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-full border-[0.5px] border-transparent px-2.5 py-1 text-xs font-semibold ${tone}`}>
      {children}
    </span>
  )
}

function ProgressBar({ percent, tone = "bg-primary" }: { percent: number; tone?: string }) {
  return (
    <div className="h-2 w-full overflow-hidden rounded-full bg-black/10 dark:bg-white/10">
      <div
        className={`h-full rounded-full ${tone} transition-all duration-700`}
        style={{ width: `${Math.min(100, Math.max(0, percent))}%` }}
      />
    </div>
  )
}

// ---------------------------------------------------------------------------
// the control
// ---------------------------------------------------------------------------

function ControlPanel({ status, sheet }: { status: QueueStatus; sheet: string | null }) {
  const queryClient = useQueryClient()
  const [note, setNote] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const refreshAll = () => {
    queryClient.invalidateQueries({ queryKey: ["queue-status"] })
    queryClient.invalidateQueries({ queryKey: ["queue-nights"] })
    queryClient.invalidateQueries({ queryKey: ["queue-overview"] })
  }

  const start = useMutation({
    mutationFn: () => startQueue({ sheet, batch_size: 2 }),
    onSuccess: (data) => {
      setError(null)
      setNote(data.message)
      refreshAll()
    },
    onError: (err: unknown) => {
      const detail =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
        (err as Error)?.message
      setNote(null)
      setError(detail || "Could not start the run.")
    },
  })

  const stop = useMutation({
    mutationFn: () => stopQueue(sheet),
    onSuccess: (data) => {
      setError(null)
      setNote(data.message)
      refreshAll()
    },
    onError: (err: unknown) => {
      const detail =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
        (err as Error)?.message
      setNote(null)
      setError(detail || "Could not stop the run.")
    },
  })

  const words = STATUS_WORDS[status.state] ?? STATUS_WORDS.idle
  const busy = start.isPending || stop.isPending
  // Low memory is the one thing worth warning about BEFORE a night, because it
  // is the difference between two chapters at a time and one.
  const lowMemory = typeof status.free_gb === "number" && status.free_gb > 0 && status.free_gb < 9

  return (
    <div className={`${GLASS} p-6 md:p-8`}>
      <div className="flex flex-col gap-6 md:flex-row md:items-center md:justify-between">
        <div className="flex items-start gap-4">
          <div className="flex h-14 w-14 shrink-0 items-center justify-center rounded-2xl border-[0.5px] border-indigo-500/20 bg-indigo-500/10">
            <Moon className="h-7 w-7 text-indigo-600 dark:text-indigo-400" />
          </div>
          <div>
            <div className="flex flex-wrap items-center gap-2">
              <h2 className="text-xl font-bold tracking-tight">Overnight extraction</h2>
              <Pill tone={words.tone}>
                {status.running && <Loader2 className="h-3 w-3 animate-spin" />}
                {words.label}
              </Pill>
            </div>
            <p className="mt-1 max-w-xl text-sm text-muted-foreground">{status.message}</p>
            <p className="mt-0.5 text-xs text-muted-foreground/70">{words.help}</p>
          </div>
        </div>

        <div className="flex shrink-0 items-center gap-3">
          {status.running ? (
            <button
              onClick={() => stop.mutate()}
              disabled={busy || status.stop_requested}
              className="flex items-center gap-2 rounded-2xl border-[0.5px] border-red-500/30 bg-red-500/15 px-6 py-4 text-base font-semibold text-red-700 transition-all hover:bg-red-500/25 disabled:opacity-50 dark:text-red-400"
            >
              {stop.isPending ? <Loader2 className="h-5 w-5 animate-spin" /> : <Square className="h-5 w-5" />}
              {status.stop_requested ? "Stopping…" : "Stop after this chapter"}
            </button>
          ) : (
            <button
              onClick={() => start.mutate()}
              disabled={busy || !status.sheet_exists}
              className="flex items-center gap-2 rounded-2xl border-[0.5px] border-green-500/30 bg-green-500/15 px-6 py-4 text-base font-semibold text-green-700 transition-all hover:bg-green-500/25 disabled:opacity-50 dark:text-green-400"
            >
              {start.isPending ? <Loader2 className="h-5 w-5 animate-spin" /> : <Play className="h-5 w-5" />}
              Start overnight run
            </button>
          )}
        </div>
      </div>

      {/* A run in flight: progress, what it is chewing on, and the counters. */}
      {(status.running || status.state === "stopping") && (
        <div className="mt-6 space-y-4 border-t border-black/5 pt-6 dark:border-white/10">
          <div>
            <div className="mb-2 flex items-center justify-between text-sm">
              <span className="font-medium">
                {status.finished_count ?? 0} of {status.total ?? 0} chapters
              </span>
              <span className="text-muted-foreground">
                running for {status.elapsed_human} · started {status.started_human}
              </span>
            </div>
            <ProgressBar percent={status.percent ?? 0} tone="bg-green-500" />
          </div>

          {(status.current ?? []).length > 0 && (
            <div className="grid gap-3 sm:grid-cols-2">
              {(status.current ?? []).map((chapter) => (
                <div
                  key={chapter.label}
                  className="rounded-2xl border-[0.5px] border-black/10 bg-white/50 p-4 dark:border-white/10 dark:bg-white/5"
                >
                  <div className="flex items-center gap-2 text-xs font-semibold text-green-700 dark:text-green-400">
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    EXTRACTING NOW
                  </div>
                  <p className="mt-1.5 text-sm font-medium leading-snug">{chapter.title}</p>
                  <p className="mt-0.5 text-xs text-muted-foreground">
                    {chapter.subject} · chapter {chapter.chapter}
                    {chapter.attempt > 1 && ` · attempt ${chapter.attempt}`}
                  </p>
                </div>
              ))}
            </div>
          )}

          <CounterRow counts={status.counts ?? {}} />

          <div className="flex flex-wrap items-center gap-4 text-xs text-muted-foreground">
            <span className="flex items-center gap-1.5">
              <MemoryStick className="h-3.5 w-3.5" />
              {status.free_gb} GB free
            </span>
            <span className="flex items-center gap-1.5">
              <Cpu className="h-3.5 w-3.5" />
              {status.degraded
                ? "one chapter at a time (after repeated failures)"
                : `${status.plan?.batch_size ?? 2} at a time when memory allows`}
            </span>
            {(status.low_memory_batches ?? 0) > 0 && (
              <span>{status.low_memory_batches} batch(es) ran singly for lack of memory</span>
            )}
          </div>
        </div>
      )}

      {lowMemory && !status.running && (
        <div className="mt-5 flex items-start gap-3 rounded-2xl border-[0.5px] border-amber-500/30 bg-amber-500/10 p-4 text-sm">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-amber-600 dark:text-amber-400" />
          <p className="text-amber-800 dark:text-amber-300">
            Only <strong>{status.free_gb} GB</strong> of memory is free. One chapter needs about
            4.4&nbsp;GB, so two at a time needs roughly 9&nbsp;GB. It will still run, one chapter at
            a time — close your browser and editor first to get the full speed.
          </p>
        </div>
      )}

      {!status.sheet_exists && (
        <div className="mt-5 rounded-2xl border-[0.5px] border-red-500/30 bg-red-500/10 p-4 text-sm text-red-800 dark:text-red-300">
          No queue sheet found on the server. Build one first with{" "}
          <code className="rounded bg-black/10 px-1.5 py-0.5 text-xs dark:bg-white/10">
            python -m scripts.build_extraction_sheet --standard 10 --subject Science
          </code>
        </div>
      )}

      {note && (
        <p className="mt-4 rounded-2xl border-[0.5px] border-green-500/25 bg-green-500/10 p-3 text-sm text-green-800 dark:text-green-300">
          {note}
        </p>
      )}
      {error && (
        <p className="mt-4 rounded-2xl border-[0.5px] border-red-500/25 bg-red-500/10 p-3 text-sm text-red-800 dark:text-red-300">
          {error}
        </p>
      )}
    </div>
  )
}

function CounterRow({ counts }: { counts: Record<string, number> }) {
  const shown = ["done", "skipped", "failed", "extracted"].filter((key) => counts[key])
  if (!shown.length) return null
  return (
    <div className="flex flex-wrap gap-2">
      {shown.map((key) => (
        <Pill key={key} tone={CHAPTER_TONE[key] ?? CHAPTER_TONE.pending}>
          {counts[key]} {CHAPTER_WORDS[key] ?? key}
        </Pill>
      ))}
    </div>
  )
}

// ---------------------------------------------------------------------------
// one night
// ---------------------------------------------------------------------------

function NightCard({ night, defaultOpen }: { night: Night; defaultOpen: boolean }) {
  const [open, setOpen] = useState(defaultOpen)
  const [showLog, setShowLog] = useState(false)

  const { data: log, isLoading: logLoading } = useQuery({
    queryKey: ["queue-log", night.run_id],
    queryFn: () => fetchNightLog(night.run_id),
    enabled: showLog && !!night.log_file,
  })

  const words = STATUS_WORDS[night.state] ?? STATUS_WORDS.finished
  const failures = night.chapters.filter((c) => c.status === "failed")

  return (
    <div className={`${GLASS} overflow-hidden`}>
      <button
        onClick={() => setOpen(!open)}
        className="flex w-full items-start gap-4 p-5 text-left transition-colors hover:bg-white/30 dark:hover:bg-white/5"
      >
        <div className="mt-0.5 shrink-0 text-muted-foreground">
          {open ? <ChevronDown className="h-5 w-5" /> : <ChevronRight className="h-5 w-5" />}
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-sm font-semibold text-muted-foreground">{night.when_human}</span>
            <Pill tone={words.tone}>
              {night.live && <Loader2 className="h-3 w-3 animate-spin" />}
              {words.label}
            </Pill>
          </div>
          <p className="mt-1 text-base font-bold tracking-tight">{night.headline}</p>
          <ul className="mt-2 space-y-1">
            {night.details.map((line, index) => (
              <li key={index} className="flex items-start gap-2 text-sm text-muted-foreground">
                <span className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-current opacity-50" />
                {line}
              </li>
            ))}
          </ul>
        </div>
        <div className="hidden shrink-0 text-right sm:block">
          <p className="text-2xl font-bold tabular-nums">{night.counts.done ?? 0}</p>
          <p className="text-xs text-muted-foreground">chapters</p>
        </div>
      </button>

      {open && (
        <div className="border-t border-black/5 px-5 pb-5 dark:border-white/10">
          {night.subjects.length > 0 && (
            <div className="mt-4 flex flex-wrap gap-2">
              {night.subjects.map((subject) => (
                <Pill
                  key={subject.name}
                  tone={
                    subject.complete
                      ? CHAPTER_TONE.done
                      : "bg-black/5 text-foreground/70 dark:bg-white/10 dark:text-white/70"
                  }
                >
                  {subject.complete ? <CheckCircle2 className="h-3 w-3" /> : null}
                  {subject.name}: {subject.done}/{subject.touched}
                </Pill>
              ))}
            </div>
          )}

          {failures.length > 0 && (
            <div className="mt-4 rounded-2xl border-[0.5px] border-red-500/25 bg-red-500/5 p-4">
              <p className="mb-2 flex items-center gap-2 text-sm font-semibold text-red-700 dark:text-red-400">
                <XCircle className="h-4 w-4" />
                What went wrong
              </p>
              <ul className="space-y-1.5">
                {failures.map((chapter) => (
                  <li key={chapter.key} className="text-sm">
                    <span className="font-medium">{chapter.label}</span>
                    <span className="text-muted-foreground"> — {chapter.error}</span>
                  </li>
                ))}
              </ul>
              <p className="mt-2 text-xs text-muted-foreground">
                These stay pending and are tried again on the next run. Nothing was lost.
              </p>
            </div>
          )}

          <div className="mt-4 overflow-x-auto">
            <table className="w-full min-w-[640px] text-sm">
              <thead>
                <tr className="border-b border-black/5 text-left text-xs uppercase tracking-wide text-muted-foreground dark:border-white/10">
                  <th className="py-2 pr-3 font-medium">Chapter</th>
                  <th className="py-2 pr-3 font-medium">Result</th>
                  <th className="py-2 pr-3 text-right font-medium">Took</th>
                  <th className="py-2 pr-3 text-right font-medium">Pages</th>
                  <th className="py-2 pr-3 text-right font-medium">Characters</th>
                  <th className="py-2 text-right font-medium">Row id</th>
                </tr>
              </thead>
              <tbody>
                {night.chapters.map((chapter) => (
                  <tr key={chapter.key} className="border-b border-black/5 last:border-0 dark:border-white/5">
                    <td className="py-2 pr-3">
                      <span className="font-medium">{chapter.label}</span>
                    </td>
                    <td className="py-2 pr-3">
                      <Pill tone={CHAPTER_TONE[chapter.status] ?? CHAPTER_TONE.pending}>
                        {CHAPTER_WORDS[chapter.status] ?? chapter.status}
                      </Pill>
                    </td>
                    <td className="py-2 pr-3 text-right tabular-nums text-muted-foreground">
                      {chapter.duration_human}
                    </td>
                    <td className="py-2 pr-3 text-right tabular-nums text-muted-foreground">
                      {chapter.pages ?? "-"}
                    </td>
                    <td className="py-2 pr-3 text-right tabular-nums text-muted-foreground">
                      {chapter.md_chars ? chapter.md_chars.toLocaleString() : "-"}
                    </td>
                    <td className="py-2 text-right tabular-nums text-muted-foreground">
                      {chapter.extraction_id ?? "-"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {night.log_file && (
            <div className="mt-4">
              <button
                onClick={() => setShowLog(!showLog)}
                className="flex items-center gap-2 rounded-full border-[0.5px] border-black/10 bg-white/50 px-4 py-2 text-xs font-medium transition-colors hover:bg-white/80 dark:border-white/10 dark:bg-white/5 dark:hover:bg-white/10"
              >
                <ScrollText className="h-3.5 w-3.5" />
                {showLog ? "Hide" : "Show"} the full log
              </button>
              {showLog && (
                <div className="mt-3 max-h-96 overflow-auto rounded-2xl bg-black/85 p-4 dark:bg-black/60">
                  {logLoading ? (
                    <p className="text-xs text-white/60">Loading…</p>
                  ) : (
                    <pre className="whitespace-pre-wrap break-words font-mono text-[11px] leading-relaxed text-green-300/90">
                      {log?.text || "No log recorded for this run."}
                    </pre>
                  )}
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// what is still waiting
// ---------------------------------------------------------------------------

function QueueOverviewPanel({ sheet }: { sheet: string | null }) {
  const { data, isLoading } = useQuery({
    queryKey: ["queue-overview", sheet],
    queryFn: () => fetchQueueOverview(sheet),
    refetchInterval: 30_000,
  })

  if (isLoading) {
    return (
      <div className={`${GLASS} p-6 text-sm text-muted-foreground`}>Reading the queue sheet…</div>
    )
  }
  if (!data?.exists) {
    return (
      <div className={`${GLASS} p-6 text-sm text-muted-foreground`}>
        No queue sheet on the server yet.
      </div>
    )
  }

  return (
    <div className={`${GLASS} p-6`}>
      <div className="mb-4 flex items-center justify-between">
        <div>
          <h3 className="text-lg font-bold tracking-tight">What is still waiting</h3>
          <p className="text-sm text-muted-foreground">
            {data.pending} of {data.total_rows} chapters still to extract
          </p>
        </div>
        <FileText className="h-5 w-5 text-muted-foreground" />
      </div>

      <div className="space-y-4">
        {data.subjects.map((subject) => (
          <div key={subject.name}>
            <div className="mb-1.5 flex items-center justify-between text-sm">
              <span className="font-medium">{subject.name}</span>
              <span className="tabular-nums text-muted-foreground">
                {subject.settled}/{subject.total}
              </span>
            </div>
            <ProgressBar
              percent={subject.percent}
              tone={subject.percent === 100 ? "bg-green-500" : "bg-primary"}
            />
          </div>
        ))}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------

export function OvernightRunner() {
  // Which sheet the controls act on. Null means "let the server decide", which
  // is right until the user picks: with one sheet there is nothing to choose,
  // and with several the server prefers whichever is actually running.
  const [sheet, setSheet] = useState<string | null>(null)

  const { data: status } = useQuery({
    queryKey: ["queue-status", sheet],
    queryFn: () => fetchQueueStatus(sheet),
    // Three seconds while something is happening, half a minute when idle. The
    // endpoint only reads a small JSON file, so this is cheap either way.
    refetchInterval: (query) => (query.state.data?.running ? 3_000 : 30_000),
  })

  const { data: nights, isLoading: nightsLoading } = useQuery({
    queryKey: ["queue-nights"],
    queryFn: () => fetchNights(30),
    refetchInterval: status?.running ? 15_000 : 60_000,
  })

  const queryClient = useQueryClient()
  const sheets = status?.sheets ?? []
  const active = sheet ?? status?.sheet ?? null

  return (
    <div className="mx-auto w-full max-w-5xl space-y-6">
      {sheets.length > 1 && (
        <div className={`${GLASS} flex flex-wrap items-center gap-2 p-4`}>
          <span className="mr-1 text-sm font-medium text-muted-foreground">Queue:</span>
          {sheets.map((name) => (
            <button
              key={name}
              onClick={() => setSheet(name)}
              className={`rounded-full border-[0.5px] px-4 py-1.5 text-sm font-medium transition-colors ${
                active === name
                  ? "border-primary/30 bg-primary/15 text-primary"
                  : "border-black/10 bg-white/50 hover:bg-white/80 dark:border-white/10 dark:bg-white/5"
              }`}
            >
              {prettySheet(name)}
            </button>
          ))}
        </div>
      )}

      <ControlPanel
        sheet={active}
        status={
          status ?? {
            running: false,
            state: "idle",
            message: "Checking…",
            sheet_exists: true,
          }
        }
      />

      <QueueOverviewPanel sheet={active} />

      <div>
        <div className="mb-3 flex items-center justify-between px-1">
          <div>
            <h3 className="text-lg font-bold tracking-tight">Every night so far</h3>
            <p className="text-sm text-muted-foreground">
              Newest first. Open one to see every chapter and the full log.
            </p>
          </div>
          <button
            onClick={() => {
              queryClient.invalidateQueries({ queryKey: ["queue-nights"] })
              queryClient.invalidateQueries({ queryKey: ["queue-status"] })
            }}
            className="flex items-center gap-1.5 rounded-full border-[0.5px] border-black/10 bg-white/50 px-3 py-1.5 text-xs font-medium transition-colors hover:bg-white/80 dark:border-white/10 dark:bg-white/5"
          >
            <RefreshCw className="h-3.5 w-3.5" />
            Refresh
          </button>
        </div>

        {nightsLoading ? (
          <div className={`${GLASS} p-6 text-sm text-muted-foreground`}>Reading the run history…</div>
        ) : !nights?.length ? (
          <div className={`${GLASS} flex items-center gap-3 p-6 text-sm text-muted-foreground`}>
            <Clock className="h-4 w-4" />
            No runs yet. Press Start and come back in the morning.
          </div>
        ) : (
          <div className="space-y-3">
            {nights.map((night, index) => (
              <NightCard key={night.run_id} night={night} defaultOpen={index === 0} />
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
