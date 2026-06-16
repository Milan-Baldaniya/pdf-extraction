"use client"

import React, { useState, useEffect, Fragment } from "react"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Badge } from "@/components/ui/badge"
import { ScrollArea } from "@/components/ui/scroll-area"
import { CustomSelect } from "@/components/ui/custom-select"

interface CurriculumRecord {
  id: number
  document_tittle: string
  subject_name: string
  standard: number
  syear: string
  board: string
  created_at: string
  is_processed: boolean
}

export function CurriculumTableFill() {
  const [records, setRecords] = useState<CurriculumRecord[]>([])
  const [loading, setLoading] = useState(false)
  const [processingId, setProcessingId] = useState<number | null>(null)
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
  });

  const fetchRecords = async () => {
    setLoading(true)
    try {
      const res = await fetch("http://localhost:8000/api/curriculums")
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
      const res = await fetch(`http://localhost:8000/api/curriculums/${extractionId}/process${forceQuery}`, {
        method: 'POST'
      })
      const data = await res.json()
      if (res.ok) {
        setResult(data)
        fetchRecords() // Refresh table status
      } else {
        alert("Error processing: " + data.detail)
      }
    } catch (err) {
      console.error(err)
      alert("Failed to process curriculum")
    } finally {
      setProcessingId(null)
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
      const res = await fetch(`http://localhost:8000/api/curriculums/${extractionId}/result`, { cache: 'no-store' })
      if (res.ok) {
        const data = await res.json()
        setResult({
          status: "view_only",
          curriculum_id: data.curriculum_id,
          extracted_data: data.extracted_data
        })
      } else {
        const data = await res.json()
        alert("Error fetching data: " + data.detail)
      }
    } catch (err) {
      console.error(err)
      alert("Failed to fetch curriculum data")
    } finally {
      setProcessingId(null)
    }
  }

  const renderExpandedRow = (r: CurriculumRecord) => {
    if (expandedRowId !== r.id || !result) return null;

    if (result.status === "already_processed") {
      return (
        <tr className="bg-yellow-50/50 dark:bg-yellow-900/10">
          <td colSpan={7} className="p-6 border-b border-black/5 dark:border-white/5">
            <div className="p-4 bg-yellow-50 text-yellow-800 rounded-md border border-yellow-200">
              This curriculum was already processed and exists in lms_curriculum (ID: {result.curriculum_id}).
            </div>
          </td>
        </tr>
      )
    }

    const { curriculum_id, extracted_data, status } = result
    return (
      <tr className="bg-black/[0.02] dark:bg-white/[0.02] shadow-inner">
        <td colSpan={7} className="p-6 border-b border-black/5 dark:border-white/5">
          <div className="space-y-6 animate-in fade-in slide-in-from-top-4 duration-500">
            {status === "view_only" ? (
              <div className="p-4 bg-blue-50/80 text-blue-800 rounded-md border border-blue-200 font-medium flex items-center gap-2">
                <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="10" /><path d="M12 16v-4" /><path d="M12 8h.01" /></svg>
                Viewing Extracted LMS Data for Curriculum ID: {curriculum_id}
              </div>
            ) : (
              <div className="p-4 bg-green-50/80 text-green-800 rounded-md border border-green-200 flex items-center gap-2">
                <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14" /><polyline points="22 4 12 14.01 9 11.01" /></svg>
                Successfully filled lms_curriculum (ID: {curriculum_id}) and lms_units!
              </div>
            )}

            <div className="grid grid-cols-1 gap-6 pb-4">
              <div className="rounded-xl border border-black/10 bg-white/60 dark:bg-black/60 overflow-hidden backdrop-blur-md">
                <div className="bg-black/5 px-4 py-3 font-semibold text-sm border-b border-black/10">LMS Curriculum Overview</div>
                <table className="min-w-full text-sm">
                  <thead className="bg-black/5">
                    <tr>
                      <th className="border-b border-black/5 p-3 text-left font-medium">Framework</th>
                      <th className="border-b border-black/5 p-3 text-left font-medium">Total Marks</th>
                      <th className="border-b border-black/5 p-3 text-left font-medium">Internal Marks</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr>
                      <td className="p-3 font-medium min-w-[120px]">{extracted_data?.framework || "-"}</td>
                      <td className="p-3 min-w-[100px]">{extracted_data?.total_marks || "-"}</td>
                      <td className="p-3 min-w-[100px]">{extracted_data?.internal_marks || "-"}</td>
                    </tr>
                  </tbody>
                </table>
              </div>

              <div className="rounded-xl border border-black/10 bg-white/60 dark:bg-black/60 overflow-hidden backdrop-blur-md">
                <div className="bg-black/5 px-4 py-3 font-semibold text-sm border-b border-black/10">LMS Units Breakup</div>
                <table className="min-w-full text-sm">
                  <thead className="bg-black/5">
                    <tr>
                      <th className="border-b border-black/5 p-3 text-left font-medium w-16">Unit No.</th>
                      <th className="border-b border-black/5 p-3 text-left font-medium w-48">Name / Title</th>
                      <th className="border-b border-black/5 p-3 text-left font-medium">Chapters Included</th>
                      <th className="border-b border-black/5 p-3 text-left font-medium w-24">Periods</th>
                      <th className="border-b border-black/5 p-3 text-left font-medium w-20">Marks</th>
                    </tr>
                  </thead>
                  <tbody>
                    {extracted_data?.units?.map((u: any, idx: number) => {
                      // Handle parsing unit_chapters if it's a string from the DB
                      let chapters: string[] = []
                      if (Array.isArray(u.unit_chapters)) {
                        chapters = u.unit_chapters
                      } else if (typeof u.unit_chapters === 'string') {
                        try {
                          chapters = JSON.parse(u.unit_chapters)
                        } catch (e) {
                          chapters = []
                        }
                      }

                      return (
                        <tr key={idx} className="hover:bg-white/40 border-b border-black/5 last:border-0 transition-colors">
                          <td className="p-3 font-medium text-foreground/80">{u.unit_number}</td>
                          <td className="p-3 font-medium">{u.name}</td>
                          <td className="p-3">
                            {chapters.length > 0 ? (
                              <div className="flex flex-wrap gap-1.5">
                                {chapters.map((chapter, cIdx) => (
                                  <span key={cIdx} className="inline-flex items-center px-2 py-0.5 rounded-md bg-black/5 dark:bg-white/5 border border-black/5 dark:border-white/5 text-xs text-foreground/70">
                                    {chapter}
                                  </span>
                                ))}
                              </div>
                            ) : (
                              <span className="text-muted-foreground/50 text-xs italic">No chapters listed</span>
                            )}
                          </td>
                          <td className="p-3">{u.planned_periods ?? u.planned_period ?? "-"}</td>
                          <td className="p-3 font-semibold text-foreground/80">{u.total_marks ?? "-"}</td>
                        </tr>
                      )
                    })}
                    {(!extracted_data?.units || extracted_data.units.length === 0) && (
                      <tr>
                        <td colSpan={5} className="p-4 text-center text-muted-foreground/50">No units extracted</td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>

              <div className="rounded-xl border border-black/10 bg-white/60 dark:bg-black/60 overflow-hidden backdrop-blur-md">
                <div className="bg-black/5 px-4 py-3 font-semibold text-sm border-b border-black/10">LMS Learning Outcomes Breakup</div>
                <div className="max-h-[400px] overflow-y-auto">
                  <table className="min-w-full text-sm">
                    <thead className="bg-black/5 sticky top-0 backdrop-blur-md">
                      <tr>
                        <th className="border-b border-black/5 p-3 text-left font-medium w-24">Code</th>
                        <th className="border-b border-black/5 p-3 text-left font-medium w-32">Type</th>
                        <th className="border-b border-black/5 p-3 text-left font-medium">Description</th>
                      </tr>
                    </thead>
                    <tbody>
                      {extracted_data?.learning_outcomes?.map((o: any, idx: number) => (
                        <tr key={idx} className="hover:bg-white/40 border-b border-black/5 last:border-0 transition-colors">
                          <td className="p-3 font-medium text-foreground/80">
                            {o.type && o.type.toLowerCase() === 'competency' ? <span className="ml-4 pl-2 border-l-2 border-black/10">{o.code}</span> : o.code}
                          </td>
                          <td className="p-3">
                            {(!o.type || o.type.trim() === '' || o.type.toLowerCase() === 'curricular goal') ? (
                              <span className="text-muted-foreground/60 text-xs font-medium italic">Goal</span>
                            ) : (
                              <Badge variant="outline" className="text-[10px] lowercase">
                                {o.type}
                              </Badge>
                            )}
                          </td>
                          <td className="p-3 text-foreground/80">{o.description}</td>
                        </tr>
                      ))}
                      {(!extracted_data?.learning_outcomes || extracted_data.learning_outcomes.length === 0) && (
                        <tr>
                          <td colSpan={3} className="p-4 text-center text-muted-foreground/50">No learning outcomes extracted</td>
                        </tr>
                      )}
                    </tbody>
                  </table>
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
        <h2 className="text-3xl font-bold tracking-tight text-foreground/90">LMS Data Filler Module</h2>
        <p className="text-muted-foreground/70 mt-2 text-sm max-w-2xl">
          Process extracted curriculum markdown using Gemini to automatically populate the lms_curriculum and lms_units tables with AI-driven intelligence.
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
                    <th className="px-5 py-4 font-medium border-b border-black/5 dark:border-white/5">Board</th>
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
                        <td className="px-5 py-3 text-foreground/70">{r.board || "-"}</td>
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
                                  {r.is_processed ? "Working..." : "Processing"}
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
                      <td colSpan={7} className="text-center py-12 text-muted-foreground/50">
                        No curriculum extractions found matching the criteria.
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
