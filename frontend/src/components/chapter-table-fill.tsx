"use client"

import React, { useState, useEffect, Fragment } from "react"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Badge } from "@/components/ui/badge"
import { ScrollArea } from "@/components/ui/scroll-area"
import { CustomSelect } from "@/components/ui/custom-select"
import { apiUrl } from "@/lib/api-url"
import { runJob } from "@/lib/api"

interface CurriculumRecord {
  id: number
  document_tittle: string
  subject_name: string
  standard: number
  syear: string
  chapter_number: string
  created_at: string
  is_processed: boolean
  // This queue produces the topics and concepts too, so a row that says
  // "processed" but shows none of either is a run that died halfway. That has
  // to be visible without opening the row.
  topic_count: number
  concept_count: number
  mean_confidence: number | null
}

/**
 * How much evidence stands behind a concept. Grey means the row predates
 * confidence entirely -- it is not the same as a low score, and must never
 * render as 0.00.
 */
function ConfidenceDot({ value, status }: { value: number | null; status?: string }) {
  if (value == null) {
    return (
      <span
        className="h-2 w-2 rounded-full bg-black/20 dark:bg-white/20 shrink-0 inline-block"
        title="Written before confidence was recorded. Reprocess the chapter to score it."
      />
    )
  }
  const tone = value >= 0.8 ? "bg-green-500" : value >= 0.55 ? "bg-amber-500" : "bg-red-500"
  return (
    <span
      className={`h-2 w-2 rounded-full shrink-0 inline-block ${tone}`}
      title={`Confidence ${value.toFixed(2)}${status ? ` (${status.replace(/_/g, " ")})` : ""}`}
    />
  )
}

/** What one run of the chapter job actually did, at a glance. */
function RunStats({ result }: { result: any }) {
  const audit = result.audit || {}
  const curriculum = result.curriculum || {}
  const stats = [
    { label: "Topics", value: result.topics_extracted, tone: "bg-green-500/10 text-green-700 dark:text-green-400 border-green-500/20" },
    { label: "Concepts", value: result.concepts_extracted, tone: "bg-green-500/10 text-green-700 dark:text-green-400 border-green-500/20" },
    { label: "Trimmed", value: Array.isArray(result.trimmed) ? result.trimmed.length : 0, tone: "bg-amber-500/10 text-amber-600 dark:text-amber-400 border-amber-500/20" },
    { label: "Duplicates dropped", value: result.duplicates_dropped, tone: "bg-black/5 dark:bg-white/5 text-foreground/70 border-black/10" },
    { label: "Grounded", value: `${result.grounded_concepts ?? 0} / ${result.concepts_extracted ?? 0}`, tone: "bg-black/5 dark:bg-white/5 text-foreground/70 border-black/10" },
    { label: "Mean confidence", value: result.extraction_confidence != null ? Number(result.extraction_confidence).toFixed(2) : "-", tone: "bg-blue-500/10 text-blue-600 dark:text-blue-400 border-blue-500/20" },
    { label: "Flagged", value: result.flagged_concepts, tone: "bg-amber-500/10 text-amber-600 dark:text-amber-400 border-amber-500/20" },
    { label: "Curriculum outcomes", value: curriculum.usable ? `${curriculum.learning_outcomes ?? 0} LO / ${curriculum.competencies ?? 0} C` : "none loaded", tone: "bg-purple-500/10 text-purple-600 dark:text-purple-400 border-purple-500/20" },
    { label: "CG/C mappings", value: result.curriculum_mappings, tone: "bg-purple-500/10 text-purple-600 dark:text-purple-400 border-purple-500/20" },
    { label: "Audit", value: audit.verdict ? `${audit.verdict} (${audit.errors ?? 0}E / ${audit.warnings ?? 0}W)` : "-", tone: audit.verdict === "fail" ? "bg-red-500/10 text-red-600 border-red-500/20" : "bg-black/5 dark:bg-white/5 text-foreground/70 border-black/10" },
    { label: "Tokens in / out", value: `${result.input_tokens ?? 0} / ${result.output_tokens ?? 0}`, tone: "bg-purple-500/10 text-purple-600 dark:text-purple-400 border-purple-500/20" },
  ]
  return (
    <div className="flex flex-wrap gap-2">
      {stats.map((stat) => (
        <div key={stat.label} className={`rounded-full border px-3 py-1 text-xs font-medium ${stat.tone}`}>
          {stat.label}: <span className="font-bold">{stat.value ?? 0}</span>
        </div>
      ))}
    </div>
  )
}

/**
 * The eight deterministic checks, on demand.
 *
 * GET /api/validate/{id} has existed since it was written with no caller at
 * all: grounding, attribution, relevance, coverage, granularity, hierarchy and
 * semantic scope, measured against the chapter's own markdown with no LLM. It
 * costs nothing to run, and it is what makes the confidence number explicable
 * rather than magic -- every issue here is a deduction applied to a real row.
 */
function AuditPanel({ extractionId, inlineAudit }: { extractionId: number; inlineAudit?: any }) {
  const [open, setOpen] = useState(false)
  const [report, setReport] = useState<any>(null)
  const [loading, setLoading] = useState(false)

  const load = async () => {
    if (open) { setOpen(false); return }
    setOpen(true)
    if (report) return
    setLoading(true)
    try {
      const res = await fetch(apiUrl(`/validate/${extractionId}`), { cache: "no-store" })
      if (res.ok) setReport(await res.json())
      else setReport({ error: (await res.json()).detail })
    } catch (err) {
      setReport({ error: String(err) })
    } finally {
      setLoading(false)
    }
  }

  const verdict = report?.verdict ?? inlineAudit?.verdict
  const issues: any[] = report?.issues || []

  return (
    <div className="rounded-xl border border-black/10 bg-white/60 dark:bg-black/60 overflow-hidden backdrop-blur-md">
      <button
        onClick={load}
        className="w-full bg-black/5 px-4 py-3 border-b border-black/10 flex items-center justify-between gap-3 text-left hover:bg-black/[0.07] transition-colors"
      >
        <span className="font-semibold text-sm">
          Audit
          <span className="ml-2 text-xs font-normal text-muted-foreground/70">
            eight deterministic checks against the chapter text &mdash; no tokens
          </span>
        </span>
        <span className="flex items-center gap-2">
          {verdict && (
            <span className={`text-xs font-bold px-2 py-0.5 rounded-full ${verdict === "pass"
              ? "bg-green-500/10 text-green-700 dark:text-green-400"
              : "bg-red-500/10 text-red-600 dark:text-red-400"}`}>
              {verdict}
            </span>
          )}
          <span className="text-xs text-muted-foreground/60">{open ? "Hide" : "Show"}</span>
        </span>
      </button>

      {open && (
        <div className="p-4 bg-white/40 dark:bg-black/40 text-sm">
          {loading && <div className="text-muted-foreground/60 italic">Running checks...</div>}
          {report?.error && <div className="text-red-600">{report.error}</div>}
          {report && !report.error && (
            <>
              <div className="flex flex-wrap gap-2 mb-3">
                {Object.entries(report.by_check || {}).map(([check, count]: any) => (
                  <div
                    key={check}
                    className={`rounded-full border px-3 py-1 text-xs font-medium ${count
                      ? "bg-amber-500/10 text-amber-700 dark:text-amber-400 border-amber-500/20"
                      : "bg-black/5 dark:bg-white/5 text-foreground/50 border-black/10"}`}
                  >
                    {check}: <span className="font-bold">{count as number}</span>
                  </div>
                ))}
              </div>
              {issues.length > 0 ? (
                <ul className="space-y-1.5 max-h-72 overflow-y-auto">
                  {issues.map((issue: any, i: number) => (
                    <li key={i} className="flex gap-2 items-start">
                      <span className={`mt-1.5 h-1.5 w-1.5 rounded-full shrink-0 ${issue.severity === "error" ? "bg-red-500" : "bg-amber-500"}`} />
                      <span className="text-xs text-foreground/80 leading-relaxed">
                        <span className="font-medium">{issue.check}</span> &mdash; {issue.message}
                      </span>
                    </li>
                  ))}
                </ul>
              ) : (
                <div className="text-muted-foreground/60 italic">No issues found.</div>
              )}
            </>
          )}
        </div>
      )}
    </div>
  )
}

export function ChapterTableFill() {
  const [records, setRecords] = useState<CurriculumRecord[]>([])
  const [loading, setLoading] = useState(false)
  const [processingId, setProcessingId] = useState<number | null>(null)
  const [processingMessage, setProcessingMessage] = useState<string | null>(null)
  const [result, setResult] = useState<any>(null)
  const [manualExtractionId, setManualExtractionId] = useState("")
  const [expandedRowId, setExpandedRowId] = useState<number | null>(null)

  const [filterSubject, setFilterSubject] = useState<string>("All")
  const [filterStandard, setFilterStandard] = useState<string>("All")

  const subjects = ["All", ...Array.from(new Set(records.map(r => r.subject_name).filter(Boolean)))]
  const standards = ["All", ...Array.from(new Set(records.map(r => r.standard).filter(Boolean)))]

  const filteredRecords = records.filter(r => {
    if (filterSubject !== "All" && r.subject_name !== filterSubject) return false;
    if (filterStandard !== "All" && String(r.standard) !== String(filterStandard)) return false;
    return true;
  }).sort((a, b) => {
    const numA = parseInt(a.chapter_number as any) || 0;
    const numB = parseInt(b.chapter_number as any) || 0;
    return numA - numB;
  });

  const fetchRecords = async () => {
    setLoading(true)
    try {
      const res = await fetch(apiUrl("/chapters"))
      if (res.ok) {
        const data = await res.json()
        setRecords(data)
      }
    } catch (err) {
      console.error(err)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchRecords()
  }, [])

  const handleProcess = async (extractionId: number) => {
    const record = records.find(r => r.id === extractionId)
    let forceQuery = ""
    if (record?.is_processed) {
      if (!window.confirm("This chapter is already processed. Reprocessing will consume LLM tokens and rebuild its topics and concepts. Existing concept rows are updated in place, not deleted, so question-bank and lesson-plan links are preserved. Continue?")) {
        return;
      }
      forceQuery = "?force=true"
    }

    setExpandedRowId(extractionId)
    setProcessingId(extractionId)
    setResult(null)
    try {
      const data = await runJob<any>(
        `${apiUrl(`/jobs/chapters/${extractionId}/process`)}${forceQuery}`,
        undefined,
        (status) => setProcessingMessage(status.message)
      )
      setResult(data)
      fetchRecords() // Refresh table status
    } catch (err) {
      console.error(err)
      alert("Error processing: " + (err as Error).message)
    } finally {
      setProcessingId(null)
      setProcessingMessage(null)
    }
  }

  const handleViewData = async (extractionId: number) => {
    if (expandedRowId === extractionId) {
      // Toggle off if already viewing
      setExpandedRowId(null)
      setResult(null)
      return
    }

    setExpandedRowId(extractionId)
    setProcessingId(extractionId)
    setResult(null)
    try {
      // Two reads, because this queue now produces the whole hierarchy: the
      // chapter row carries the unit and the budget, the concept endpoint
      // carries the topics with their concepts. A chapter that predates the
      // merge simply has no concepts, and the panel falls back to key_concepts.
      const [chapterRes, conceptRes] = await Promise.all([
        fetch(apiUrl(`/chapters/${extractionId}/result`), { cache: 'no-store' }),
        fetch(apiUrl(`/concepts/${extractionId}/result`), { cache: 'no-store' }),
      ])
      if (chapterRes.ok) {
        const data = await chapterRes.json()
        const concepts = conceptRes.ok ? await conceptRes.json() : null
        setResult({
          status: "view_only",
          chapter_master_id: data.chapter_master_id,
          chapter_data: data,
          concept_budget: data.concept_budget,
          topics: concepts?.topics || [],
          concepts_extracted: concepts?.total_concepts ?? 0,
        })
      } else {
        const data = await chapterRes.json()
        alert("Error fetching data: " + data.detail)
      }
    } catch (err) {
      console.error(err)
      alert("Failed to fetch chapter data")
    } finally {
      setProcessingId(null)
      setProcessingMessage(null)
    }
  }

  const renderExpandedRow = (r: CurriculumRecord) => {
    if (expandedRowId !== r.id || !result) return null;

    if (result.status === "already_processed") {
      return (
        <tr className="bg-yellow-50/50 dark:bg-yellow-900/10">
          <td colSpan={8} className="p-6 border-b border-black/5 dark:border-white/5">
            <div className="p-4 bg-yellow-50 text-yellow-800 rounded-md border border-yellow-200">
              This chapter was already processed and exists in chapter_master (ID: {result.chapter_master_id}).
            </div>
          </td>
        </tr>
      )
    }

    const { chapter_master_id, chapter_data, status } = result
    const topics: any[] = result.topics || []
    return (
      <tr className="bg-black/[0.02] dark:bg-white/[0.02] shadow-inner">
        <td colSpan={8} className="p-6 border-b border-black/5 dark:border-white/5">
          <div className="space-y-6 animate-in fade-in slide-in-from-top-4 duration-500">
            {status === "view_only" ? (
              <div className="p-4 bg-blue-50/80 text-blue-800 rounded-md border border-blue-200 font-medium flex items-center gap-2">
                <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="10" /><path d="M12 16v-4" /><path d="M12 8h.01" /></svg>
                Viewing Extracted Chapter Data (ID: {chapter_master_id})
              </div>
            ) : (
              <div className="p-4 bg-green-50/80 text-green-800 rounded-md border border-green-200 flex items-center gap-2">
                <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14" /><polyline points="22 4 12 14.01 9 11.01" /></svg>
                Built the whole hierarchy for chapter {result.chapter_master_id}: {result.topics_extracted ?? 0} topics
                and {result.concepts_extracted ?? 0} concepts, mapped to its unit and curriculum.
              </div>
            )}

            <div className="grid grid-cols-1 gap-6 pb-4">
              <div className="rounded-xl border border-black/10 bg-white/60 dark:bg-black/60 overflow-hidden backdrop-blur-md">
                <div className="bg-black/5 px-4 py-3 font-semibold text-sm border-b border-black/10">Chapter Summary</div>
                <table className="min-w-full text-sm">
                  <thead className="bg-black/5">
                    <tr>
                      <th className="border-b border-black/5 p-3 text-left font-medium">Mapped Unit</th>
                      <th className="border-b border-black/5 p-3 text-left font-medium">Chapter Name</th>
                      <th className="border-b border-black/5 p-3 text-left font-medium">No. of Periods</th>
                      <th className="border-b border-black/5 p-3 text-left font-medium">Academic Year</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr>
                      <td className="p-3 font-medium min-w-[120px]">
                        {chapter_data?.unit_name ? `${chapter_data.unit_name} (ID: ${chapter_data.unit_id})` : <span className="text-amber-600">Unmapped (No Match in Units)</span>}
                      </td>
                      <td className="p-3 min-w-[100px] font-semibold">{chapter_data?.chapter_name || "-"}</td>
                      <td className="p-3 min-w-[100px]">
                        {chapter_data?.no_of_periods == null ? (
                          <span className="text-muted-foreground/50 text-xs italic">Not allocated in curriculum</span>
                        ) : (
                          <span className="inline-flex items-center px-2 py-0.5 rounded-md bg-emerald-500/10 text-emerald-700 dark:text-emerald-400 border border-emerald-500/20 font-semibold">
                            {chapter_data.no_of_periods}
                          </span>
                        )}
                      </td>
                      <td className="p-3 min-w-[100px]">{chapter_data?.syear || "-"}</td>
                    </tr>
                  </tbody>
                </table>
              </div>

              {status !== "view_only" && <RunStats result={result} />}

              {/* The topics and their concepts, produced by the same job. A
                  flat list of "key concepts" used to sit here; it came from a
                  separate call that never saw the concepts actually stored. */}
              <div className="rounded-xl border border-black/10 bg-white/60 dark:bg-black/60 overflow-hidden backdrop-blur-md">
                <div className="bg-black/5 px-4 py-3 font-semibold text-sm border-b border-black/10 flex items-center justify-between">
                  <span>Topics and Concepts</span>
                  {result.concept_budget && (
                    <span className="text-xs font-normal text-muted-foreground/70">
                      target {result.concept_budget.target} concepts
                      {" "}({result.concept_budget.low}&ndash;{result.concept_budget.high}),
                      {" "}anchored on {String(result.concept_budget.source).replace(/_/g, " ")}
                    </span>
                  )}
                </div>
                <div className="p-4 bg-white/40 dark:bg-black/40 space-y-4">
                  {topics.length > 0 ? topics.map((topic: any) => (
                    <div key={topic.topic_id ?? topic.topic_name} className="rounded-lg border border-black/5 dark:border-white/5 overflow-hidden">
                      <div className="bg-black/[0.03] dark:bg-white/[0.03] px-3 py-2 text-sm font-semibold">
                        {topic.sort_order ? `#${topic.sort_order} ` : ""}{topic.topic_name}
                        <span className="ml-2 text-xs font-normal text-muted-foreground/70">
                          {topic.concepts.length} concepts
                          {topic.topic_minutes ? ` · ${topic.topic_minutes} min` : ""}
                        </span>
                      </div>
                      <div className="p-3 grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
                        {topic.concepts.map((concept: any) => (
                          <div key={concept.concept_id} className="p-3 rounded-lg border border-black/5 dark:border-white/5 bg-white dark:bg-black/50 shadow-sm relative">
                            <div className="absolute top-3 right-3">
                              <ConfidenceDot value={concept.confidence} status={concept.review_status} />
                            </div>
                            <div className="font-semibold text-sm text-foreground/90 mb-1 pr-5">{concept.name}</div>
                            <div className="text-xs text-foreground/70 leading-relaxed">{concept.description}</div>
                          </div>
                        ))}
                      </div>
                    </div>
                  )) : chapter_data?.key_concepts?.length ? (
                    // A chapter processed before the queues merged: key_concepts
                    // is all it has, and it has no topic structure to show.
                    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                      {chapter_data.key_concepts.map((concept: any, idx: number) => (
                        <div key={idx} className="p-4 rounded-xl border border-black/5 dark:border-white/5 bg-white dark:bg-black/50 shadow-sm">
                          <div className="font-semibold text-foreground/90 mb-1.5">{concept.name}</div>
                          <div className="text-xs text-foreground/70 leading-relaxed">{concept.description}</div>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <div className="text-center text-muted-foreground/50 py-4 italic">No concepts extracted.</div>
                  )}
                </div>
              </div>

              <AuditPanel extractionId={r.id} inlineAudit={result.audit} />

              {Array.isArray(result.trimmed) && result.trimmed.length > 0 && (
                <div className="rounded-xl border border-amber-200 bg-amber-50/70 p-4 text-sm text-amber-900">
                  <div className="font-semibold mb-2">
                    {result.trimmed.length} concept(s) were trimmed to stay within the chapter&apos;s budget
                  </div>
                  <ul className="space-y-1 text-xs">
                    {result.trimmed.slice(0, 12).map((t: any, i: number) => (
                      <li key={i} className="truncate">
                        <span className="font-medium">{t.name}</span>
                        <span className="opacity-70"> — {t.reason} (score {t.keep_score}{t.evidence_verified ? ", quote verified" : ", no verified quote"})</span>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          </div>
        </td>
      </tr>
    )
  }

  return (
    <div className="w-full max-w-6xl mx-auto rounded-[2rem] border-[0.5px] border-black/10 dark:border-white/20 bg-white/40 dark:bg-black/40 backdrop-blur-[40px] saturate-200 shadow-[0_8px_32px_0_rgba(0,0,0,0.1)] p-6 md:p-10 relative overflow-hidden before:absolute before:inset-0 before:-z-10 before:rounded-[2rem] before:bg-gradient-to-br before:from-white/40 before:to-transparent before:opacity-50 dark:before:from-white/10 dark:before:to-transparent">

      <div className="mb-8">
        <h2 className="text-3xl font-bold tracking-tight text-foreground/90">Chapter Data Filler Module</h2>
        <p className="text-muted-foreground/70 mt-2 text-sm max-w-2xl">
          Reads the chapter markdown together with its subject&apos;s curriculum, then builds the
          whole hierarchy in one pass: the unit it belongs to, its topics, and the concepts under
          each topic &mdash; mapped to the curricular goals and competencies they serve. How many
          concepts a chapter gets is set by its syllabus and its period allocation, not by how long
          the text is. Definitions and mastery thresholds are written afterwards, in the Concepts
          queue.
        </p>
      </div>

      <div className="w-full">
        <div className="mt-0">
          <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center mb-6 gap-4">
            <div className="flex flex-col sm:flex-row items-start sm:items-center gap-4">


              <div className="flex gap-3 z-[60]">
                <div className="w-[160px]">
                  <CustomSelect
                    value={filterSubject}
                    onChange={setFilterSubject}
                    options={subjects.map(s => ({ value: String(s), label: s === "All" ? "All Subjects" : String(s) }))}
                  />
                </div>
                <div className="w-[160px]">
                  <CustomSelect
                    value={filterStandard}
                    onChange={setFilterStandard}
                    options={standards.map(s => ({ value: String(s), label: s === "All" ? "All Standards" : `Std ${s}` }))}
                  />
                </div>
              </div>
            </div>

            <Button
              onClick={fetchRecords}
              disabled={loading}
              variant="outline"
              size="sm"
              className="rounded-full bg-white/50 dark:bg-black/50 backdrop-blur-md border-black/10 hover:bg-white/80 transition-all"
            >
              {loading ? "Refreshing..." : "Refresh Data"}
            </Button>
          </div>

          <div className="rounded-2xl border-[0.5px] border-black/10 dark:border-white/10 bg-white/50 dark:bg-black/50 backdrop-blur-xl overflow-hidden shadow-inner">
            <div className="w-full overflow-x-auto pb-8">
              <table className="w-full text-sm text-left">
                <thead className="bg-black/5 dark:bg-white/5 text-foreground/70 sticky top-0 z-10 backdrop-blur-xl">
                  <tr>
                    <th className="px-5 py-4 font-medium border-b border-black/5 dark:border-white/5">Ext ID</th>
                    <th className="px-5 py-4 font-medium border-b border-black/5 dark:border-white/5">Document Title</th>
                    <th className="px-5 py-4 font-medium border-b border-black/5 dark:border-white/5">Subject</th>
                    <th className="px-5 py-4 font-medium border-b border-black/5 dark:border-white/5">Standard</th>
                    <th className="px-5 py-4 font-medium border-b border-black/5 dark:border-white/5">Ch. No.</th>
                    <th className="px-5 py-4 font-medium border-b border-black/5 dark:border-white/5">Topics / Concepts</th>
                    <th className="px-5 py-4 font-medium border-b border-black/5 dark:border-white/5">Status</th>
                    <th className="px-5 py-4 font-medium border-b border-black/5 dark:border-white/5 text-right">Action</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-black/5 dark:divide-white/5">
                  {filteredRecords.map((r) => (
                    <React.Fragment key={r.id}>
                      <tr className={`hover:bg-white/40 dark:hover:bg-black/40 transition-colors ${expandedRowId === r.id ? "bg-black/5 dark:bg-white/5" : ""}`}>
                        <td className="px-5 py-3 font-medium text-foreground/80">{r.id}</td>
                        <td className="px-5 py-3 text-foreground/70">{r.document_tittle || "-"}</td>
                        <td className="px-5 py-3 text-foreground/70">{r.subject_name || "-"}</td>
                        <td className="px-5 py-3 text-foreground/70">
                          <span className="inline-flex items-center justify-center h-6 w-6 rounded-full bg-black/5 text-xs font-semibold">
                            {r.standard || "-"}
                          </span>
                        </td>
                        <td className="px-5 py-3 text-foreground/70 font-semibold">{r.chapter_number || "-"}</td>
                        <td className="px-5 py-3 text-foreground/70 text-xs">
                          {r.is_processed ? (
                            <>
                              <span className={r.topic_count ? "" : "text-amber-600 font-semibold"}>
                                {r.topic_count || 0}
                              </span>
                              {" / "}
                              <span className={r.concept_count ? "" : "text-amber-600 font-semibold"}>
                                {r.concept_count || 0}
                              </span>
                              {r.mean_confidence != null && (
                                <span className="text-muted-foreground/60"> · conf {r.mean_confidence.toFixed(2)}</span>
                              )}
                            </>
                          ) : "-"}
                        </td>
                        <td className="px-5 py-3">
                          {r.is_processed ? (
                            <Badge variant="secondary" className="bg-green-500/10 text-green-700 dark:text-green-400 border border-green-500/20 hover:bg-green-500/20 rounded-full px-2.5">
                              Processed
                            </Badge>
                          ) : (
                            <Badge variant="outline" className="text-foreground/50 border-black/10 rounded-full px-2.5">
                              Pending
                            </Badge>
                          )}
                        </td>
                        <td className="px-5 py-3 text-right">
                          <div className="flex justify-end gap-2">
                            {!!r.is_processed && (
                              <Button
                                size="sm"
                                disabled={processingId === r.id && result === null}
                                onClick={() => handleViewData(r.id)}
                                className={`rounded-full transition-all duration-300 border-[0.5px] ${expandedRowId === r.id && result?.status === "view_only"
                                  ? "bg-blue-600 text-white border-blue-600 shadow-md"
                                  : "bg-blue-500/10 hover:bg-blue-500/20 text-blue-600 border-blue-500/20"
                                  }`}
                              >
                                {expandedRowId === r.id && result?.status === "view_only" ? "Close Output" : "View Output"}
                              </Button>
                            )}
                            <Button
                              size="sm"
                              disabled={processingId === r.id && result === null}
                              onClick={() => handleProcess(r.id)}
                              className={`rounded-full transition-all duration-300 ${r.is_processed
                                ? "bg-black/5 hover:bg-black/10 text-foreground/70 shadow-none border-[0.5px] border-black/10 dark:bg-white/5 dark:hover:bg-white/10 dark:border-white/10"
                                : "bg-foreground hover:bg-foreground/90 text-background shadow-md shadow-black/10 dark:shadow-white/10"
                                }`}
                            >
                              {processingId === r.id && result === null ? (
                                <span className="flex items-center gap-2">
                                  <span className="h-3 w-3 border-2 border-current border-t-transparent rounded-full animate-spin"></span>
                                  {processingMessage || (r.is_processed ? "Working..." : "Processing")}
                                </span>
                              ) : (r.is_processed ? "Reprocess" : "Process & Fill")}
                            </Button>
                          </div>
                        </td>
                      </tr>
                      {renderExpandedRow(r)}
                    </React.Fragment>
                  ))}
                  {filteredRecords.length === 0 && !loading && (
                    <tr>
                      <td colSpan={8} className="text-center py-12 text-muted-foreground/50">
                        No chapter extractions found matching the criteria.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}


