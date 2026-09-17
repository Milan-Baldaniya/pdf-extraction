"use client"

import React, { useState, useEffect } from "react"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { CustomSelect } from "@/components/ui/custom-select"
import { apiUrl } from "@/lib/api-url"
import { runJob } from "@/lib/api"

interface ConceptRecord {
  id: number
  document_tittle: string
  subject_name: string
  standard: number
  syear: string
  chapter_number: string
  created_at: string
  // "processed" means enriched now, not "has concepts": this queue writes the
  // definition and the mastery values onto concepts the Chapters queue created.
  is_processed: boolean
  has_chapter: boolean
  has_topic: boolean
  has_concept: boolean
  topic_count: number
  concept_count: number
  enriched_count: number
  unenriched_count: number
  mean_confidence: number | null
}

interface Concept {
  concept_id: number
  name: string
  description: string
  definition: string | null
  mastery_threshold: number
  estimated_mastery_minutes: number
  // null means the row was written before confidence existed. It is rendered
  // grey, never as 0.00 -- an unscored concept is not a bad one.
  confidence: number | null
  review_status: string
  is_enriched: boolean
}

interface TopicGroup {
  topic_id: number | null
  topic_name: string
  topic_minutes: number | null
  sort_order: number | null
  concepts: Concept[]
}

/**
 * How much evidence stands behind a concept: the chapter quote was found, it
 * sits in its own topic's text, the name matches that text, it is not a repeat
 * of a sibling, and it serves the curriculum.
 *
 * Grey means the row predates confidence entirely -- most of the 2,571 concepts
 * already in this database. That is not the same as a low score, and it must
 * never render as 0.00.
 */
function ConfidenceDot({ value, status }: { value: number | null; status?: string }) {
  if (value == null) {
    return (
      <span
        className="h-2 w-2 rounded-full bg-black/20 dark:bg-white/20 shrink-0"
        title="Written before confidence was recorded. Reprocess the chapter to score it."
      />
    )
  }
  const tone =
    value >= 0.8 ? "bg-green-500"
      : value >= 0.55 ? "bg-amber-500"
        : "bg-red-500"
  return (
    <span
      className={`h-2 w-2 rounded-full shrink-0 ${tone}`}
      title={`Confidence ${value.toFixed(2)}${status ? ` (${status.replace(/_/g, " ")})` : ""}`}
    />
  )
}

export function ConceptTableFill() {
  const [records, setRecords] = useState<ConceptRecord[]>([])
  const [loading, setLoading] = useState(false)
  const [processingId, setProcessingId] = useState<number | null>(null)
  const [retryingTopicId, setRetryingTopicId] = useState<number | null>(null)
  const [processingMessage, setProcessingMessage] = useState<string | null>(null)
  const [result, setResult] = useState<any>(null)
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
      const res = await fetch(apiUrl("/concepts"))
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
      // The old wording promised to "replace the existing rows in lms_concept",
      // which is exactly what this stage no longer does.
      if (!window.confirm("These concepts are already enriched. Re-enriching will consume LLM tokens and overwrite their definitions and mastery values. The concepts themselves are never created or deleted. Continue?")) {
        return;
      }
      forceQuery = "?force=true"
    }

    setExpandedRowId(extractionId)
    setProcessingId(extractionId)
    setResult(null)
    try {
      const data = await runJob<any>(
        `${apiUrl(`/jobs/concepts/${extractionId}/process`)}${forceQuery}`,
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

  // One topic coming back thin should not force a full-chapter re-enrichment.
  // Like the whole-chapter form, this only ever UPDATEs existing rows.
  const handleRetryTopic = async (extractionId: number, topicId: number) => {
    setRetryingTopicId(topicId)
    try {
      const res = await fetch(apiUrl(`/concepts/${extractionId}/topic/${topicId}/process`), {
        method: 'POST'
      })
      const data = await res.json()
      if (res.ok) {
        setResult(data)
        fetchRecords()
      } else {
        alert("Error retrying topic: " + data.detail)
      }
    } catch (err) {
      console.error(err)
      alert("Failed to retry topic")
    } finally {
      setRetryingTopicId(null)
    }
  }

  const handleViewData = async (extractionId: number) => {
    if (expandedRowId === extractionId) {
      setExpandedRowId(null)
      setResult(null)
      return
    }

    setExpandedRowId(extractionId)
    setProcessingId(extractionId)
    setResult(null)
    try {
      const res = await fetch(apiUrl(`/concepts/${extractionId}/result`), { cache: 'no-store' })
      if (res.ok) {
        const data = await res.json()
        setResult({ ...data, status: "view_only" })
      } else {
        const data = await res.json()
        alert("Error fetching data: " + data.detail)
      }
    } catch (err) {
      console.error(err)
      alert("Failed to fetch concept data")
    } finally {
      setProcessingId(null)
      setProcessingMessage(null)
    }
  }

  const renderExpandedRow = (r: ConceptRecord) => {
    if (expandedRowId !== r.id || !result) return null;

    if (result.status === "already_processed") {
      return (
        <tr className="bg-yellow-50/50 dark:bg-yellow-900/10">
          <td colSpan={8} className="p-6 border-b border-black/5 dark:border-white/5">
            <div className="p-4 bg-yellow-50 text-yellow-800 rounded-md border border-yellow-200">
              This chapter&apos;s concepts were already processed.
            </div>
          </td>
        </tr>
      )
    }

    const topics: TopicGroup[] = result.topics || []
    const status = result.status

    return (
      <tr className="bg-black/[0.02] dark:bg-white/[0.02] shadow-inner">
        <td colSpan={8} className="p-6 border-b border-black/5 dark:border-white/5">
          <div className="space-y-6 animate-in fade-in slide-in-from-top-4 duration-500">
            {status === "view_only" ? (
              <div className="p-4 bg-blue-50/80 text-blue-800 rounded-md border border-blue-200 font-medium flex items-center gap-2">
                <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="10" /><path d="M12 16v-4" /><path d="M12 8h.01" /></svg>
                Viewing Extracted Concepts ({result.total_concepts || 0} across {topics.length} topics)
              </div>
            ) : (
              <div className="p-4 bg-green-50/80 text-green-800 rounded-md border border-green-200 flex items-center gap-2">
                <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14" /><polyline points="22 4 12 14.01 9 11.01" /></svg>
                Enriched {result.concepts_enriched ?? 0} of {result.concepts_seen ?? 0} concepts with a definition, mastery threshold and mastery time.
              </div>
            )}

            {status !== "view_only" && (
              <div className="flex flex-wrap gap-2">
                {[
                  { label: "Enriched", value: result.concepts_enriched, tone: "bg-green-500/10 text-green-700 dark:text-green-400 border-green-500/20" },
                  { label: "Concepts seen", value: result.concepts_seen, tone: "bg-black/5 dark:bg-white/5 text-foreground/70 border-black/10" },
                  { label: "Still missing a definition", value: result.concepts_missing, tone: "bg-red-500/10 text-red-600 dark:text-red-400 border-red-500/20" },
                  { label: "Mean confidence", value: result.mean_confidence != null ? result.mean_confidence.toFixed(2) : "-", tone: "bg-blue-500/10 text-blue-600 dark:text-blue-400 border-blue-500/20" },
                  { label: "Flagged", value: result.flagged_concepts, tone: "bg-amber-500/10 text-amber-600 dark:text-amber-400 border-amber-500/20" },
                  { label: "Tokens in / out", value: `${result.input_tokens ?? 0} / ${result.output_tokens ?? 0}`, tone: "bg-purple-500/10 text-purple-600 dark:text-purple-400 border-purple-500/20" },
                ].map((stat) => (
                  <div key={stat.label} className={`rounded-full border px-3 py-1 text-xs font-medium ${stat.tone}`}>
                    {stat.label}: <span className="font-bold">{stat.value ?? 0}</span>
                  </div>
                ))}
              </div>
            )}

            {Array.isArray(result.missing_concepts) && result.missing_concepts.length > 0 && (
              <div className="rounded-xl border border-red-200 bg-red-50/70 p-4 text-sm text-red-800">
                <div className="font-semibold mb-2">These concepts came back without a definition:</div>
                <ul className="space-y-1">
                  {result.missing_concepts.map((f: any) => (
                    <li key={f.concept_id} className="truncate">{f.name} — {f.error}</li>
                  ))}
                </ul>
                <div className="mt-2 text-xs opacity-80">
                  Re-enrich the topic they sit under to try again. The concepts themselves are unaffected.
                </div>
              </div>
            )}

            <div className="space-y-4 pb-4">
              {topics.length > 0 ? topics.map((topic) => {
                const topicMinutes = topic.concepts.reduce((sum, c) => sum + (c.estimated_mastery_minutes || 0), 0)
                return (
                  <div key={topic.topic_id ?? topic.topic_name} className="rounded-xl border border-black/10 bg-white/60 dark:bg-black/60 overflow-hidden backdrop-blur-md">
                    <div className="bg-black/5 px-4 py-3 border-b border-black/10 flex items-center justify-between gap-3">
                      <div className="font-semibold text-sm">
                        {topic.sort_order ? `#${topic.sort_order} ` : ""}{topic.topic_name}
                        <span className="ml-2 text-xs font-normal text-muted-foreground/70">
                          {topic.concepts.length} concepts · {topicMinutes} min
                          {topic.topic_minutes ? ` / ${topic.topic_minutes} min budget` : ""}
                        </span>
                      </div>
                      <Button
                        size="sm"
                        variant="outline"
                        disabled={retryingTopicId === topic.topic_id || !topic.topic_id}
                        onClick={() => topic.topic_id && handleRetryTopic(r.id, topic.topic_id)}
                        className="rounded-full shrink-0 h-7 text-xs bg-white/60 dark:bg-black/60"
                        title={!topic.topic_id ? "These rows predate the Chapter -> Topics -> Concepts hierarchy" : ""}
                      >
                        {retryingTopicId === topic.topic_id ? "Re-enriching..." : "Re-enrich topic"}
                      </Button>
                    </div>
                    <div className="p-4 bg-white/40 dark:bg-black/40">
                      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                        {topic.concepts.map((concept) => (
                          <div key={concept.concept_id} className="p-4 rounded-xl border border-black/5 dark:border-white/5 bg-white dark:bg-black/50 shadow-sm hover:shadow-md transition-shadow relative">
                            <div className="absolute top-3 right-3 flex items-center gap-1.5">
                              <ConfidenceDot value={concept.confidence} status={concept.review_status} />
                              {concept.is_enriched ? (
                                <div className="bg-blue-500/10 text-blue-600 dark:text-blue-400 text-[10px] font-bold px-2 py-0.5 rounded-full">
                                  {concept.mastery_threshold}% Mastery
                                </div>
                              ) : (
                                <div
                                  className="bg-black/5 dark:bg-white/10 text-muted-foreground/70 text-[10px] font-bold px-2 py-0.5 rounded-full"
                                  title="The Chapters queue created this concept; run Enrich to set its threshold."
                                >
                                  Not enriched
                                </div>
                              )}
                            </div>
                            <div className="font-semibold text-foreground/90 mb-1.5 pr-28">{concept.name}</div>
                            <div className="text-xs text-foreground/70 leading-relaxed mb-2">{concept.description}</div>
                            {concept.definition && (
                              <div className="text-xs text-foreground/80 leading-relaxed mb-3 border-l-2 border-blue-500/30 pl-2.5">
                                {concept.definition}
                              </div>
                            )}
                            <div className="flex items-center text-xs text-muted-foreground/80 bg-black/5 dark:bg-white/5 rounded-md px-2 py-1 w-fit">
                              <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="mr-1.5"><circle cx="12" cy="12" r="10" /><polyline points="12 6 12 12 16 14" /></svg>
                              {concept.estimated_mastery_minutes} min est.
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>
                  </div>
                )
              }) : (
                <div className="text-center text-muted-foreground/50 py-4 italic">No concepts extracted.</div>
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
        <h2 className="text-3xl font-bold tracking-tight text-foreground/90">Concepts Data Filler Module</h2>
        <p className="text-muted-foreground/70 mt-2 text-sm max-w-2xl">
          Break every extracted topic into its masterable concepts, topic by topic, and populate the lms_concept table with deep mastery details.
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
                    <th className="px-5 py-4 font-medium border-b border-black/5 dark:border-white/5">Topics</th>
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
                          {r.topic_count || 0}
                          {r.concept_count > 0 && (
                            <span className="text-muted-foreground/60"> · {r.concept_count} concepts</span>
                          )}
                          {r.mean_confidence != null && (
                            <span className="text-muted-foreground/60"> · conf {r.mean_confidence.toFixed(2)}</span>
                          )}
                        </td>
                        <td className="px-5 py-3">
                          {r.is_processed ? (
                            <Badge variant="secondary" className="bg-green-500/10 text-green-700 dark:text-green-400 border border-green-500/20 hover:bg-green-500/20 rounded-full px-2.5">
                              Enriched
                            </Badge>
                          ) : r.has_concept ? (
                            <Badge variant="outline" className="text-amber-600 border-amber-500/30 bg-amber-500/10 rounded-full px-2.5">
                              {r.unenriched_count} to enrich
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
                            {/* Gated on concepts, not topics: the Chapters queue
                                produces both, so a chapter that has been through
                                it is ready to enrich. */}
                            <Button
                              size="sm"
                              disabled={(processingId === r.id && result === null) || !r.has_concept}
                              onClick={() => handleProcess(r.id)}
                              className={`rounded-full transition-all duration-300 ${!r.has_concept ? "opacity-50 cursor-not-allowed" : ""} ${r.is_processed
                                ? "bg-black/5 hover:bg-black/10 text-foreground/70 shadow-none border-[0.5px] border-black/10 dark:bg-white/5 dark:hover:bg-white/10 dark:border-white/10"
                                : "bg-foreground hover:bg-foreground/90 text-background shadow-md shadow-black/10 dark:shadow-white/10"
                                }`}
                              title={!r.has_concept ? "Run the Chapters queue first — it creates the concepts this stage enriches" : ""}
                            >
                              {processingId === r.id && result === null ? (
                                <span className="flex items-center gap-2">
                                  <span className="h-3 w-3 border-2 border-current border-t-transparent rounded-full animate-spin"></span>
                                  {processingMessage || (r.is_processed ? "Working..." : "Enriching")}
                                </span>
                              ) : (r.is_processed ? "Re-enrich" : (!r.has_concept ? "Need Chapter" : "Enrich"))}
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
