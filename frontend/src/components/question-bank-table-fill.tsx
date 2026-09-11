"use client"

import React, { useState, useEffect, Fragment } from "react"
import { Button } from "@/components/ui/button"
import { CustomSelect } from "@/components/ui/custom-select"
import { apiUrl } from "@/lib/api-url"
import { runJob } from "@/lib/api"

interface QuestionBankRecord {
  id: number
  document_tittle: string
  subject_name: string
  standard: number
  syear: string
  chapter_number: string
  chapter_id: number | null
  board: string
  sub_institute_id: number
  extraction_status: string
  created_at: string
  is_processed: boolean
}

interface ValidationEntry { code: string; message: string }

interface Figure {
  url: string | null
  sha256: string | null
  width: number | null
  height: number | null
  page: number | null
  caption: string | null
  /** Text read out of the figure. On a graph question this is often the only
   *  place the axis values appear, so it is worth showing when OCR found any. */
  ocr_text: string | null
}

interface PreviewItem {
  item_number: string
  exam_section: string
  item_form: string
  marks: number
  stem: string
  options: Array<{ label: string; text: string; is_correct: boolean }>
  correct_option: string | null
  answer_text: string | null
  source_page: number | null
  assertion: string | null
  reason: string | null
  sub_part_labels: string[]
  figure_required: boolean
  figures: Figure[]
  validation: { failed: ValidationEntry[]; warnings: ValidationEntry[] } | null
}

interface ProcessResult {
  status: string
  extraction_id: number
  dry_run: boolean
  parsed: number
  total_marks: number
  blueprint: { matches_cbse_pattern: boolean; observed: Record<string, number>; expected: Record<string, number> }
  sections: Record<string, number>
  question_types: Record<string, number>
  validation: { failed: number; with_warnings: number; by_code: Record<string, number> }
  warnings: string[]
  attribution: string
  inserted?: number
  options?: number
  assets?: number
  held?: number
  published?: number
  skipped_duplicate?: number
  preview?: PreviewItem[]
}

const SECTION_ORDER = ["A", "B", "C", "D", "E"]

const FORM_LABEL: Record<string, string> = {
  mcq: "MCQ",
  assertion_reason: "Assertion-Reason",
  very_short_answer: "Very short",
  short_answer: "Short answer",
  long_answer: "Long answer",
  case_study: "Case study",
}

function formLabel(form: string) {
  return FORM_LABEL[form] ?? form.replace(/_/g, " ")
}

/** One question as the reviewer sees it: stem, any figure, options, answer. */
function PreviewCard({ item }: { item: PreviewItem }) {
  const failed = item.validation?.failed ?? []
  const warnings = item.validation?.warnings ?? []
  // A held item is the one thing a reviewer must not miss, so the whole card
  // changes colour rather than relying on a badge alone.
  const tone = failed.length
    ? "border-rose-500/40 bg-rose-500/[0.04]"
    : warnings.length
      ? "border-amber-500/40 bg-amber-500/[0.03]"
      : "border-black/10 dark:border-white/10 bg-black/[0.015] dark:bg-white/[0.02]"

  return (
    <div className={`rounded-xl border p-3 text-xs ${tone}`}>
      <div className="mb-2 flex flex-wrap items-center gap-1.5">
        <span className="rounded-md bg-foreground/90 px-1.5 py-0.5 font-semibold tabular-nums text-background">
          Q{item.item_number}
        </span>
        <span className="rounded-full border border-black/10 px-2 py-0.5 dark:border-white/15">
          {formLabel(item.item_form)}
        </span>
        <span className="rounded-full border border-black/10 px-2 py-0.5 tabular-nums dark:border-white/15">
          {item.marks} {item.marks === 1 ? "mark" : "marks"}
        </span>
        {item.source_page != null && (
          <span className="text-[10px] text-muted-foreground/70">p.{item.source_page}</span>
        )}
        <div className="flex-1" />
        {failed.map(f => (
          <span
            key={f.code}
            title={f.message}
            className="rounded-full bg-rose-500/15 px-2 py-0.5 font-medium text-rose-700 dark:text-rose-400"
          >
            {f.code}
          </span>
        ))}
        {warnings.map(w => (
          <span
            key={w.code}
            title={w.message}
            className="rounded-full bg-amber-500/15 px-2 py-0.5 font-medium text-amber-700 dark:text-amber-500"
          >
            {w.code}
          </span>
        ))}
      </div>

      {item.assertion || item.reason ? (
        <div className="mb-2 space-y-1">
          {item.assertion && (
            <div className="rounded-lg border-l-2 border-l-sky-500/60 bg-sky-500/[0.06] px-2.5 py-1.5">
              <span className="font-semibold text-sky-700 dark:text-sky-400">Assertion (A): </span>
              <span className="text-foreground/85">{item.assertion}</span>
            </div>
          )}
          {item.reason && (
            <div className="rounded-lg border-l-2 border-l-violet-500/60 bg-violet-500/[0.06] px-2.5 py-1.5">
              <span className="font-semibold text-violet-700 dark:text-violet-400">Reason (R): </span>
              <span className="text-foreground/85">{item.reason}</span>
            </div>
          )}
        </div>
      ) : (
        <div className="whitespace-pre-wrap leading-relaxed text-foreground/85">{item.stem}</div>
      )}

      {item.sub_part_labels.length > 0 && (
        <div className="mt-1.5 text-[11px] text-muted-foreground">
          Sub-parts: {item.sub_part_labels.join(", ")}
        </div>
      )}

      <FigureStrip item={item} />

      {item.options.length > 0 && (
        <div className="mt-2 grid gap-1 sm:grid-cols-2">
          {item.options.map(o => (
            <div
              key={o.label}
              className={`flex items-start gap-1.5 rounded-lg border px-2 py-1 ${
                o.is_correct
                  ? "border-emerald-500/40 bg-emerald-500/10 text-emerald-800 dark:text-emerald-300"
                  : "border-black/[0.07] bg-background/60 text-muted-foreground dark:border-white/10"
              }`}
            >
              <span className="font-mono font-semibold">({o.label})</span>
              <span className="min-w-0 flex-1 break-words">{o.text}</span>
              {o.is_correct && <span aria-label="correct answer">✓</span>}
            </div>
          ))}
        </div>
      )}

      {item.options.length === 0 && item.answer_text && (
        <div className="mt-2 rounded-lg border border-black/[0.07] border-l-2 border-l-emerald-500/60 bg-emerald-500/[0.04] px-2.5 py-1.5 dark:border-white/10">
          <div className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
            Solution
          </div>
          <div className="mt-0.5 whitespace-pre-wrap text-foreground/80">{item.answer_text}</div>
        </div>
      )}
    </div>
  )
}

/** Figures attached to a question, plus the honest empty state when the text
 *  asks for a figure that the extractor never found (validator V-07). */
function FigureStrip({ item }: { item: PreviewItem }) {
  if (item.figures.length === 0) {
    if (!item.figure_required) return null
    return (
      <div className="mt-2 rounded-lg border border-dashed border-amber-500/50 px-2.5 py-1.5 text-[11px] text-amber-700 dark:text-amber-500">
        This question refers to a figure, but none was captured — held for review.
      </div>
    )
  }
  return (
    <div className="mt-2 flex flex-wrap gap-2">
      {item.figures.map((fig, i) => (
        <figure
          key={fig.sha256 ?? i}
          className="overflow-hidden rounded-lg border border-black/10 bg-white dark:border-white/10"
        >
          {fig.url ? (
            /* eslint-disable-next-line @next/next/no-img-element */
            <img
              src={fig.url}
              alt={fig.caption || `Figure for question ${item.item_number}`}
              loading="lazy"
              className="max-h-44 w-auto max-w-full object-contain"
            />
          ) : null}
          {(fig.caption || fig.ocr_text) && (
            <figcaption className="max-w-[260px] space-y-0.5 px-2 py-1 text-[10px] leading-snug text-muted-foreground">
              {fig.caption && <div>{fig.caption}</div>}
              {fig.ocr_text && (
                <div className="line-clamp-3 opacity-70" title={fig.ocr_text}>
                  Read from image: {fig.ocr_text}
                </div>
              )}
            </figcaption>
          )}
        </figure>
      ))}
    </div>
  )
}

export function QuestionBankTableFill() {
  const [records, setRecords] = useState<QuestionBankRecord[]>([])
  const [loading, setLoading] = useState(false)
  const [busyId, setBusyId] = useState<number | null>(null)
  const [busyMessage, setBusyMessage] = useState<string | null>(null)
  const [result, setResult] = useState<ProcessResult | null>(null)
  const [expandedRowId, setExpandedRowId] = useState<number | null>(null)

  const [filterBoard, setFilterBoard] = useState<string>("All")
  const [filterSubject, setFilterSubject] = useState<string>("All")
  const [filterStandard, setFilterStandard] = useState<string>("All")

  const boards = ["All", ...Array.from(new Set(records.map(r => r.board).filter(Boolean)))]
  const subjects = ["All", ...Array.from(new Set(records.map(r => r.subject_name).filter(Boolean)))]
  const standards = ["All", ...Array.from(new Set(records.map(r => r.standard).filter(Boolean)))]

  const filtered = records
    .filter(r => {
      if (filterBoard !== "All" && r.board !== filterBoard) return false
      if (filterSubject !== "All" && r.subject_name !== filterSubject) return false
      if (filterStandard !== "All" && String(r.standard) !== String(filterStandard)) return false
      return true
    })
    .sort((a, b) => (parseInt(a.chapter_number) || 0) - (parseInt(b.chapter_number) || 0))

  const fetchRecords = async () => {
    setLoading(true)
    try {
      const res = await fetch(apiUrl("/question-banks"))
      if (res.ok) setRecords(await res.json())
    } catch (err) {
      console.error(err)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { fetchRecords() }, [])

  // Preview is a dry run: it parses and validates and writes nothing, so an
  // operator can see the blueprint match and the held items before committing.
  const handlePreview = async (id: number) => {
    setExpandedRowId(id); setBusyId(id); setResult(null); setBusyMessage("Parsing…")
    try {
      const res = await fetch(apiUrl(`/exam-questions/${id}/process?dry_run=true`), { method: "POST" })
      const data = await res.json()
      if (!res.ok) throw new Error(data?.detail || "Preview failed")
      setResult(data)
    } catch (err) {
      alert("Preview failed: " + (err as Error).message)
    } finally {
      setBusyId(null); setBusyMessage(null)
    }
  }

  const handleProceed = async (record: QuestionBankRecord) => {
    let replace = false
    if (record.is_processed) {
      if (!window.confirm(
        "This chapter has already been processed. Proceeding will REPLACE every question " +
        "previously extracted from it. Continue?"
      )) return
      replace = true
    }
    setExpandedRowId(record.id); setBusyId(record.id); setResult(null)
    try {
      const data = await runJob<ProcessResult>(
        `${apiUrl(`/jobs/exam-questions/${record.id}/process`)}?replace=${replace}`,
        undefined,
        (status) => setBusyMessage(status.message),
      )
      setResult(data)
      fetchRecords()
    } catch (err) {
      alert("Processing failed: " + (err as Error).message)
    } finally {
      setBusyId(null); setBusyMessage(null)
    }
  }

  const renderBlueprint = (r: ProcessResult) => (
    <div className="flex flex-wrap gap-2">
      {SECTION_ORDER.map(letter => {
        const got = r.blueprint.observed[letter] ?? 0
        const want = r.blueprint.expected[letter] ?? 0
        const ok = got === want
        return (
          <div
            key={letter}
            className={`rounded-xl border px-3 py-2 text-xs font-medium ${
              ok
                ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-700 dark:text-emerald-400"
                : "border-amber-500/30 bg-amber-500/10 text-amber-700 dark:text-amber-400"
            }`}
          >
            <div className="font-semibold">Section {letter}</div>
            <div className="tabular-nums">{got} / {want} items</div>
          </div>
        )
      })}
    </div>
  )

  const renderExpanded = (record: QuestionBankRecord) => {
    if (expandedRowId !== record.id) return null
    if (busyId === record.id) {
      return (
        <tr className="bg-black/[0.02] dark:bg-white/[0.02]">
          <td colSpan={8} className="p-6 border-b border-black/5 dark:border-white/5">
            <div className="text-sm text-muted-foreground animate-pulse">
              {busyMessage || "Working…"}
            </div>
          </td>
        </tr>
      )
    }
    if (!result || result.extraction_id !== record.id) return null

    const held = result.held ?? result.validation.failed
    return (
      <tr className="bg-black/[0.02] dark:bg-white/[0.02] shadow-inner">
        <td colSpan={8} className="p-6 border-b border-black/5 dark:border-white/5">
          <div className="space-y-5 animate-in fade-in slide-in-from-top-4 duration-500">

            <div className={`rounded-xl border px-4 py-3 text-sm font-medium ${
              result.blueprint.matches_cbse_pattern
                ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-800 dark:text-emerald-300"
                : "border-amber-500/30 bg-amber-500/10 text-amber-800 dark:text-amber-300"
            }`}>
              {result.blueprint.matches_cbse_pattern
                ? `Matches the CBSE paper pattern — ${result.parsed} items, ${result.total_marks} marks.`
                : `Parsed ${result.parsed} items (${result.total_marks} marks) but the section counts do not match the CBSE pattern. Review before publishing.`}
              {result.dry_run && <span className="ml-2 opacity-70">(preview only — nothing was saved)</span>}
            </div>

            {renderBlueprint(result)}

            <div className="flex flex-wrap gap-2 text-xs">
              {Object.entries(result.question_types).map(([form, n]) => (
                <span key={form} className="rounded-full bg-black/5 dark:bg-white/10 px-3 py-1">
                  {form.replace(/_/g, " ")}: <span className="tabular-nums font-semibold">{n}</span>
                </span>
              ))}
            </div>

            {!result.dry_run && (
              <div className="flex flex-wrap gap-2 text-xs">
                <span className="rounded-full bg-emerald-500/10 text-emerald-700 dark:text-emerald-400 px-3 py-1">
                  published <span className="tabular-nums font-semibold">{result.published ?? 0}</span>
                </span>
                <span className="rounded-full bg-amber-500/10 text-amber-700 dark:text-amber-400 px-3 py-1">
                  held for review <span className="tabular-nums font-semibold">{held}</span>
                </span>
                <span className="rounded-full bg-black/5 dark:bg-white/10 px-3 py-1">
                  options <span className="tabular-nums font-semibold">{result.options ?? 0}</span>
                </span>
                <span className="rounded-full bg-black/5 dark:bg-white/10 px-3 py-1">
                  figures <span className="tabular-nums font-semibold">{result.assets ?? 0}</span>
                </span>
              </div>
            )}

            {held > 0 && (
              <div className="rounded-xl border border-amber-500/30 bg-amber-500/5 p-4">
                <div className="text-sm font-semibold text-amber-800 dark:text-amber-300 mb-2">
                  {held} item{held === 1 ? "" : "s"} held for a teacher
                </div>
                <div className="text-xs text-muted-foreground">
                  {Object.entries(result.validation.by_code).map(([code, n]) => (
                    <span key={code} className="mr-3">{code} × {n}</span>
                  ))}
                </div>
              </div>
            )}

            {result.warnings?.length > 0 && (
              <ul className="text-xs text-muted-foreground list-disc pl-5 space-y-1">
                {result.warnings.slice(0, 6).map((w, i) => <li key={i}>{w}</li>)}
              </ul>
            )}

            {result.preview && result.preview.length > 0 && (
              <div className="space-y-3 max-h-[560px] overflow-y-auto pr-1">
                {SECTION_ORDER.filter(sec => result.preview!.some(i => i.exam_section === sec)).map(sec => {
                  const items = result.preview!.filter(i => i.exam_section === sec)
                  return (
                    <div key={sec}>
                      <div className="sticky top-0 z-10 -mx-1 mb-2 flex items-center gap-2 bg-background/95 px-1 py-1 backdrop-blur">
                        <span className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
                          Section {sec}
                        </span>
                        <span className="text-[11px] text-muted-foreground/70">
                          {items.length} {items.length === 1 ? "question" : "questions"} ·{" "}
                          {items.reduce((n, i) => n + (i.marks || 0), 0)} marks
                        </span>
                        <div className="h-px flex-1 bg-black/10 dark:bg-white/10" />
                      </div>
                      <div className="space-y-2">
                        {items.map((item, i) => (
                          <PreviewCard key={`${sec}-${item.item_number}-${i}`} item={item} />
                        ))}
                      </div>
                    </div>
                  )
                })}
              </div>
            )}

            <div className="text-[11px] text-muted-foreground/70 border-t border-black/5 dark:border-white/5 pt-3">
              Source: {result.attribution}
            </div>

            {!result.dry_run && (
              <Button
                onClick={() => window.open(apiUrl(`/exam-questions/${record.id}/result`), "_blank")}
                className="self-start bg-blue-600 hover:bg-blue-700 text-white rounded-full shadow-md"
              >
                View stored questions
              </Button>
            )}
          </div>
        </td>
      </tr>
    )
  }

  return (
    <div className="w-full max-w-6xl mx-auto rounded-[2rem] border-[0.5px] border-black/10 dark:border-white/20 bg-white/40 dark:bg-black/40 backdrop-blur-[40px] saturate-200 shadow-[0_8px_32px_0_rgba(0,0,0,0.1)] p-6 md:p-10 relative overflow-hidden before:absolute before:inset-0 before:-z-10 before:rounded-[2rem] before:bg-gradient-to-br before:from-white/40 before:to-transparent before:opacity-50 dark:before:from-white/10 dark:before:to-transparent">

      <div className="mb-8">
        <h2 className="text-3xl font-bold tracking-tight text-foreground/90">Question Bank Queue</h2>
        <p className="text-muted-foreground/70 mt-2 text-sm max-w-2xl">
          Turn an extracted question-bank chapter into structured exam items — question, options,
          correct answer, worked solution, marks and CBSE section — and store them in the question
          bank. Preview first to see the blueprint match; Proceed writes them.
        </p>
      </div>

      <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center mb-6 gap-4">
        <div className="flex gap-3 z-[60]">
          <div className="w-[150px]">
            <CustomSelect value={filterBoard} onChange={setFilterBoard}
              options={boards.map(b => ({ value: String(b), label: b === "All" ? "All Boards" : String(b) }))} />
          </div>
          <div className="w-[160px]">
            <CustomSelect value={filterSubject} onChange={setFilterSubject}
              options={subjects.map(s => ({ value: String(s), label: s === "All" ? "All Subjects" : String(s) }))} />
          </div>
          <div className="w-[150px]">
            <CustomSelect value={filterStandard} onChange={setFilterStandard}
              options={standards.map(s => ({ value: String(s), label: s === "All" ? "All Classes" : `Class ${s}` }))} />
          </div>
        </div>
        <Button onClick={fetchRecords} disabled={loading}
          className="rounded-full bg-black/5 dark:bg-white/10 hover:bg-black/10 text-foreground/80">
          {loading ? "Refreshing…" : "Refresh"}
        </Button>
      </div>

      <div className="overflow-x-auto rounded-2xl border-[0.5px] border-black/10 dark:border-white/10">
        <table className="w-full text-sm">
          <thead className="bg-black/[0.03] dark:bg-white/[0.03]">
            <tr className="text-left text-xs uppercase tracking-wider text-muted-foreground/70">
              <th className="px-4 py-3 font-medium">Ch.</th>
              <th className="px-4 py-3 font-medium">Chapter</th>
              <th className="px-4 py-3 font-medium">Board</th>
              <th className="px-4 py-3 font-medium">Class</th>
              <th className="px-4 py-3 font-medium">Subject</th>
              <th className="px-4 py-3 font-medium">Mapped chapter</th>
              <th className="px-4 py-3 font-medium">Status</th>
              <th className="px-4 py-3 font-medium text-right">Action</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-black/5 dark:divide-white/5">
            {filtered.length === 0 && (
              <tr><td colSpan={8} className="px-4 py-10 text-center text-muted-foreground/70">
                {loading ? "Loading…" : "No question-bank extractions yet. Upload a chapter PDF with Document Type “Question Bank”."}
              </td></tr>
            )}
            {filtered.map(r => (
              <Fragment key={r.id}>
                <tr className="hover:bg-black/[0.02] dark:hover:bg-white/[0.02] transition-colors">
                  <td className="px-4 py-3 tabular-nums text-muted-foreground">{r.chapter_number}</td>
                  <td className="px-4 py-3 font-medium text-foreground/90">{r.document_tittle}</td>
                  <td className="px-4 py-3">
                    <span className="rounded-full bg-black/5 dark:bg-white/10 px-2.5 py-1 text-xs">
                      {r.board} · t{r.sub_institute_id}
                    </span>
                  </td>
                  <td className="px-4 py-3 tabular-nums">{r.standard}</td>
                  <td className="px-4 py-3 text-muted-foreground">{r.subject_name}</td>
                  <td className="px-4 py-3">
                    {r.chapter_id ? (
                      <span className="tabular-nums text-muted-foreground">#{r.chapter_id}</span>
                    ) : (
                      // Without a chapter the questions have nothing to hang off,
                      // so Proceed is refused rather than writing orphans.
                      <span className="rounded-full bg-rose-500/10 text-rose-700 dark:text-rose-400 px-2.5 py-1 text-xs">
                        not mapped
                      </span>
                    )}
                  </td>
                  <td className="px-4 py-3">
                    <span className={`rounded-full px-2.5 py-1 text-xs ${
                      r.extraction_status === "extracted"
                        ? "bg-emerald-500/10 text-emerald-700 dark:text-emerald-400"
                        : r.extraction_status === "failed"
                        ? "bg-rose-500/10 text-rose-700 dark:text-rose-400"
                        : "bg-amber-500/10 text-amber-700 dark:text-amber-400"
                    }`}>
                      {r.extraction_status || "pending"}
                    </span>
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex gap-2 justify-end">
                      <Button
                        onClick={() => handlePreview(r.id)}
                        disabled={busyId !== null || !r.chapter_id || r.extraction_status !== "extracted"}
                        className="rounded-full bg-black/5 dark:bg-white/10 hover:bg-black/10 text-foreground/80 px-4"
                      >
                        Preview
                      </Button>
                      <Button
                        onClick={() => handleProceed(r)}
                        disabled={busyId !== null || !r.chapter_id || r.extraction_status !== "extracted"}
                        className="rounded-full bg-blue-600 hover:bg-blue-700 text-white px-5 shadow-md"
                      >
                        {busyId === r.id ? "Working…" : "Proceed"}
                      </Button>
                    </div>
                  </td>
                </tr>
                {renderExpanded(r)}
              </Fragment>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
