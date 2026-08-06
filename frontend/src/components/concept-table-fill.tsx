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
  has_chapter: boolean
}

export function ConceptTableFill() {
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
      if (!window.confirm("This is already processed. Forcing a reprocess will consume LLM tokens and overwrite existing data. Are you sure?")) {
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
      const res = await fetch(apiUrl(`/concepts/${extractionId}/result`), { cache: 'no-store' })
      if (res.ok) {
        const data = await res.json()
        setResult({
          status: "view_only",
          chapter_id: data.chapter_id,
          concepts: data.concepts
        })
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

  const renderExpandedRow = (r: CurriculumRecord) => {
    if (expandedRowId !== r.id || !result) return null;

    if (result.status === "already_processed") {
      return (
        <tr className="bg-yellow-50/50 dark:bg-yellow-900/10">
          <td colSpan={7} className="p-6 border-b border-black/5 dark:border-white/5">
            <div className="p-4 bg-yellow-50 text-yellow-800 rounded-md border border-yellow-200">
              This chapter's concepts were already processed.
            </div>
          </td>
        </tr>
      )
    }

    const { concepts, status } = result
    return (
      <tr className="bg-black/[0.02] dark:bg-white/[0.02] shadow-inner">
        <td colSpan={7} className="p-6 border-b border-black/5 dark:border-white/5">
          <div className="space-y-6 animate-in fade-in slide-in-from-top-4 duration-500">
            {status === "view_only" ? (
              <div className="p-4 bg-blue-50/80 text-blue-800 rounded-md border border-blue-200 font-medium flex items-center gap-2">
                <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="10" /><path d="M12 16v-4" /><path d="M12 8h.01" /></svg>
                Viewing Extracted Concepts Data
              </div>
            ) : (
              <div className="p-4 bg-green-50/80 text-green-800 rounded-md border border-green-200 flex items-center gap-2">
                <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14" /><polyline points="22 4 12 14.01 9 11.01" /></svg>
                Successfully filled lms_concept!
              </div>
            )}

            <div className="grid grid-cols-1 gap-6 pb-4">
              <div className="rounded-xl border border-black/10 bg-white/60 dark:bg-black/60 overflow-hidden backdrop-blur-md">
                <div className="bg-black/5 px-4 py-3 font-semibold text-sm border-b border-black/10">Extracted Concepts ({concepts?.length || 0})</div>
                <div className="p-4 bg-white/40 dark:bg-black/40">
                  {concepts && concepts.length > 0 ? (
                    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                      {concepts.map((concept: any, idx: number) => (
                        <div key={idx} className="p-4 rounded-xl border border-black/5 dark:border-white/5 bg-white dark:bg-black/50 shadow-sm hover:shadow-md transition-shadow relative">
                          <div className="absolute top-3 right-3 bg-blue-500/10 text-blue-600 dark:text-blue-400 text-[10px] font-bold px-2 py-0.5 rounded-full">
                            {concept.mastery_threshold}% Mastery
                          </div>
                          <div className="font-semibold text-foreground/90 mb-1.5 pr-16">{concept.name}</div>
                          <div className="text-xs text-foreground/70 leading-relaxed mb-3">{concept.description}</div>
                          <div className="flex items-center text-xs text-muted-foreground/80 bg-black/5 dark:bg-white/5 rounded-md px-2 py-1 w-fit">
                            <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="mr-1.5"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>
                            {concept.estimated_mastery_minutes} min est.
                          </div>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <div className="text-center text-muted-foreground/50 py-4 italic">No concepts extracted.</div>
                  )}
                </div>
              </div>
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
          Process extracted chapter markdown and key concepts to automatically populate the lms_concept table with deep mastery details.
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
                              disabled={(processingId === r.id && result === null) || !r.has_chapter}
                              onClick={() => handleProcess(r.id)}
                              className={`rounded-full transition-all duration-300 ${!r.has_chapter ? "opacity-50 cursor-not-allowed" : ""} ${r.is_processed
                                ? "bg-black/5 hover:bg-black/10 text-foreground/70 shadow-none border-[0.5px] border-black/10 dark:bg-white/5 dark:hover:bg-white/10 dark:border-white/10"
                                : "bg-foreground hover:bg-foreground/90 text-background shadow-md shadow-black/10 dark:shadow-white/10"
                                }`}
                              title={!r.has_chapter ? "Must process Chapter first" : ""}
                            >
                              {processingId === r.id && result === null ? (
                                <span className="flex items-center gap-2">
                                  <span className="h-3 w-3 border-2 border-current border-t-transparent rounded-full animate-spin"></span>
                                  {processingMessage || (r.is_processed ? "Working..." : "Processing")}
                                </span>
                              ) : (r.is_processed ? "Reprocess" : (!r.has_chapter ? "Need Chapter" : "Process & Fill"))}
                            </Button>
                          </div>
                        </td>
                      </tr>
                      {renderExpandedRow(r)}
                    </React.Fragment>
                  ))}
                  {filteredRecords.length === 0 && !loading && (
                    <tr>
                      <td colSpan={7} className="text-center py-12 text-muted-foreground/50">
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


