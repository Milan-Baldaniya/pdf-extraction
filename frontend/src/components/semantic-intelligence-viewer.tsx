import React, { useState } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { Brain, Target, Zap, Award, Layers, BarChart, Link as LinkIcon, AlertTriangle, Globe, Lightbulb, Flag, CheckCircle, FileText, ClipboardCheck, Network, Quote, Sparkles } from "lucide-react";

interface SemanticIntelligenceViewerProps {
  data: any; // The full JSON from the database
}

// Custom simple accordion to avoid missing shadcn component error
function CustomAccordionItem({ title, badge, subtitle, children, isOpen, onClick }: any) {
  return (
    <div className="border-[0.5px] border-black/10 dark:border-white/10 bg-white/40 dark:bg-black/40 backdrop-blur-xl rounded-2xl overflow-hidden shadow-sm mb-4">
      <button
        onClick={onClick}
        className="w-full px-6 py-4 hover:bg-black/[0.02] dark:hover:bg-white/[0.02] transition-all flex flex-col items-start text-left gap-1 cursor-pointer"
      >
        <div className="flex items-center gap-2">
          {badge && (
            <Badge variant="secondary" className="bg-blue-500/10 text-blue-700 dark:text-blue-400 border border-blue-500/20">
              {badge}
            </Badge>
          )}
          <span className="font-bold text-lg">{title || "Unknown Subtopic"}</span>
        </div>
        <span className="text-sm text-muted-foreground line-clamp-1 font-normal">{subtitle}</span>
      </button>
      {isOpen && (
        <div className="px-6 pb-6 pt-2 border-t border-black/5 dark:border-white/5 animate-in slide-in-from-top-2 duration-300">
          {children}
        </div>
      )}
    </div>
  );
}

const formatValue = (val: string) => {
  if (!val) return val;
  const v = val.toLowerCase();
  const map: Record<string, string> = {
    imp: "Important",
    diff: "Difficult",
    med: "Medium",
    beg: "Beginner",
    adv: "Advanced",
    req: "Required",
    opt: "Optional",
    high: "High",
    low: "Low"
  };
  if (map[v]) return map[v];
  return val.charAt(0).toUpperCase() + val.slice(1);
}

function InfoTooltip({ children, content, className }: any) {
  return (
    <Tooltip>
      <TooltipTrigger className={`cursor-pointer inline-flex items-center gap-1.5 ${className || ""}`}>
        {children}
        <div className="w-4 h-4 rounded-full bg-black/10 dark:bg-white/20 flex items-center justify-center text-[10px] text-foreground font-bold hover:bg-black/20 dark:hover:bg-white/30 transition-colors shadow-sm cursor-help">?</div>
      </TooltipTrigger>
      <TooltipContent 
        sideOffset={8}
        className="max-w-[450px] p-5 text-base leading-relaxed bg-white/95 dark:bg-black/95 backdrop-blur-xl border border-black/20 dark:border-white/20 shadow-2xl rounded-2xl text-foreground font-medium z-[100]"
      >
        {content}
      </TooltipContent>
    </Tooltip>
  );
}

// Renders a CBSE levels-of-response band table. For the Foundational and
// Preparatory stages (Classes 1-5) the rubric carries no marks, so the Marks
// column is dropped rather than showing a column of zeroes.
function LevelBandTable({ levels }: { levels: any[] }) {
  if (!levels || levels.length === 0) return null;
  const hasMarks = levels.some((l: any) => (l.mark_high ?? 0) > 0);

  const tone: Record<string, string> = {
    "Excellent": "text-emerald-600 bg-emerald-500/10 border-emerald-500/30",
    "Proficient": "text-emerald-600 bg-emerald-500/10 border-emerald-500/30",
    "Good": "text-sky-600 bg-sky-500/10 border-sky-500/30",
    "Progressing": "text-sky-600 bg-sky-500/10 border-sky-500/30",
    "Fair": "text-amber-600 bg-amber-500/10 border-amber-500/30",
    "Needs Improvement": "text-orange-600 bg-orange-500/10 border-orange-500/30",
    "Beginning": "text-rose-600 bg-rose-500/10 border-rose-500/30",
    "Beginner": "text-rose-600 bg-rose-500/10 border-rose-500/30",
    "No Credit": "text-muted-foreground bg-black/5 dark:bg-white/5 border-black/10 dark:border-white/10",
  };

  return (
    <div className="overflow-x-auto rounded-xl border border-black/10 dark:border-white/10">
      <table className="w-full text-sm border-collapse min-w-[520px]">
        <thead>
          <tr className="bg-black/[0.03] dark:bg-white/[0.03] text-left">
            <th className="px-3 py-2 font-semibold w-16">Level</th>
            <th className="px-3 py-2 font-semibold w-40">Performance</th>
            <th className="px-3 py-2 font-semibold">What the answer looks like</th>
            {hasMarks && <th className="px-3 py-2 font-semibold w-20 text-right">Marks</th>}
          </tr>
        </thead>
        <tbody>
          {levels.map((l: any, i: number) => (
            <tr key={i} className="border-t border-black/5 dark:border-white/5 align-top">
              <td className="px-3 py-2 font-bold text-foreground/70">{l.level}</td>
              <td className="px-3 py-2">
                <Badge variant="outline" className={`text-[10px] ${tone[l.display_label] || ""}`}>
                  {l.display_label}
                </Badge>
              </td>
              <td className="px-3 py-2">
                <ul className="space-y-1">
                  {l.descriptors?.map((d: string, j: number) => (
                    <li key={j} className="text-foreground/80 leading-snug">· {d}</li>
                  ))}
                </ul>
              </td>
              {hasMarks && (
                <td className="px-3 py-2 text-right font-semibold whitespace-nowrap">
                  {l.mark_low === l.mark_high ? l.mark_low : `${l.mark_low}–${l.mark_high}`}
                </td>
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function RubricItemCard({ item }: { item: any }) {
  const rubricLabel: Record<string, string> = {
    answer_key: "Answer Key",
    point_based: "Point-Based Mark Scheme",
    levels_of_response: "Levels of Response",
    analytical: "Analytical Rubric",
  };

  return (
    <div className="p-5 rounded-2xl border border-violet-500/20 bg-violet-50/30 dark:bg-violet-900/10">
      {/* Question header */}
      <div className="flex justify-between items-start gap-4 mb-3">
        <div>
          <div className="text-[10px] font-mono text-muted-foreground mb-1">{item.item_id}</div>
          <div className="font-medium text-foreground/90">{item.question}</div>
        </div>
        {item.marks > 0 && (
          <div className="font-bold text-violet-700 dark:text-violet-300 bg-violet-100 dark:bg-violet-900/50 px-2.5 py-1 rounded text-sm whitespace-nowrap">
            {item.marks} Marks
          </div>
        )}
      </div>

      {item.skill_phrase && (
        <div className="text-xs text-muted-foreground mb-3">
          <b>Assesses:</b> {item.skill_phrase}
        </div>
      )}

      {/* Metadata badges */}
      <div className="flex flex-wrap gap-2 mb-4">
        <Badge variant="outline" className="bg-white/50 dark:bg-black/50">{item.assessment_type}</Badge>
        <InfoTooltip content="Which CBSE mark-scheme shape applies to this item type.">
          <Badge variant="outline" className="bg-violet-500/10 border-violet-500/30 text-violet-700 dark:text-violet-300">
            {rubricLabel[item.rubric_type] || item.rubric_type}
          </Badge>
        </InfoTooltip>
        <Badge variant="outline" className="bg-white/50 dark:bg-black/50">Difficulty: {item.difficulty}</Badge>
        <Badge variant="outline" className="bg-white/50 dark:bg-black/50">Bloom: {item.bloom_level}</Badge>
        <Badge variant="outline" className="bg-white/50 dark:bg-black/50">DOK {item.dok_level}</Badge>
        {item.assessment_objectives?.map((ao: string, i: number) => (
          <InfoTooltip key={i} content="CBSE Assessment Objective: the kind of thinking this item tests.">
            <Badge className="bg-indigo-500 text-white hover:bg-indigo-600">{ao}</Badge>
          </InfoTooltip>
        ))}
        <InfoTooltip content={item.evidence_verified
          ? "Every supporting quote was found verbatim in the chapter text."
          : "WARNING: the supporting quotes could not be matched in the chapter text. This item may be unreliable."}>
          <Badge variant="outline" className={item.evidence_verified
            ? "border-emerald-500/40 text-emerald-600"
            : "border-amber-500/50 text-amber-600"}>
            {item.evidence_verified ? "✓ Grounded in text" : "⚠ Unverified quote"}
          </Badge>
        </InfoTooltip>
      </div>

      {/* ANSWER KEY (MCQ / Assertion Reason) */}
      {item.rubric_type === "answer_key" && item.answer_key?.length > 0 && (
        <div className="space-y-2">
          {item.answer_key.map((o: any, i: number) => (
            <div key={i} className={`p-3 rounded-xl border ${o.is_correct
              ? "border-emerald-500/40 bg-emerald-50/50 dark:bg-emerald-900/20"
              : "border-black/10 dark:border-white/10 bg-white/40 dark:bg-black/40"}`}>
              <div className="flex items-start gap-2">
                <span className={`font-bold ${o.is_correct ? "text-emerald-600" : "text-foreground/60"}`}>
                  {o.option_label}.
                </span>
                <div className="flex-1">
                  <div className="font-medium text-sm">{o.option_text}</div>
                  <div className="text-xs text-muted-foreground mt-1">{o.rationale}</div>
                  {o.misconception_tested && (
                    <div className="text-xs mt-2 text-rose-600/90 dark:text-rose-400/90">
                      <b>Detects misconception:</b> {o.misconception_tested}
                    </div>
                  )}
                </div>
                {o.is_correct && <Badge className="bg-emerald-500 text-white text-[10px]">Correct</Badge>}
              </div>
            </div>
          ))}
        </div>
      )}

      {/* POINT-BASED (Short Answer / Numerical) */}
      {item.rubric_type === "point_based" && item.acceptable_points?.length > 0 && (
        <div className="rounded-xl border border-black/10 dark:border-white/10 overflow-hidden">
          <div className="px-3 py-2 bg-black/[0.03] dark:bg-white/[0.03] text-xs font-semibold">
            Award marks for each point, up to a maximum of {item.marks}.
          </div>
          {item.acceptable_points.map((p: any, i: number) => (
            <div key={i} className="px-3 py-2 border-t border-black/5 dark:border-white/5 flex justify-between gap-4">
              <div>
                <div className="text-sm">{p.point}</div>
                {p.alternatives?.length > 0 && (
                  <div className="text-xs text-muted-foreground mt-1">Also accept: {p.alternatives.join(" / ")}</div>
                )}
              </div>
              <div className="text-sm font-semibold whitespace-nowrap">{p.marks} {p.marks === 1 ? "mark" : "marks"}</div>
            </div>
          ))}
        </div>
      )}

      {/* LEVELS OF RESPONSE (extended answers) */}
      {item.rubric_type === "levels_of_response" && (
        <div className="space-y-3">
          {item.indicative_content?.length > 0 && (
            <div className="p-3 rounded-xl bg-white/50 dark:bg-black/40 border border-black/5 dark:border-white/5">
              <div className="text-xs font-semibold mb-2 flex items-center gap-2">
                Indicative Content
                <InfoTooltip content="CBSE rule: this list is indicative and NOT exhaustive. All valid and supported points earn credit.">
                  <Badge variant="outline" className="text-[10px] font-normal">not exhaustive</Badge>
                </InfoTooltip>
              </div>
              <ul className="space-y-1">
                {item.indicative_content.map((c: string, i: number) => (
                  <li key={i} className="text-sm text-foreground/80">· {c}</li>
                ))}
              </ul>
            </div>
          )}
          <LevelBandTable levels={item.level_descriptors} />
        </div>
      )}

      {/* ANALYTICAL (Project / Practical / Viva) */}
      {item.rubric_type === "analytical" && item.criteria?.length > 0 && (
        <div className="space-y-4">
          {item.criteria.map((c: any, i: number) => (
            <div key={i}>
              <div className="flex items-center gap-2 mb-2">
                <span className="font-semibold text-sm">{c.criterion}</span>
                {c.weight_marks > 0 && (
                  <Badge variant="outline" className="text-[10px]">{c.weight_marks} marks</Badge>
                )}
              </div>
              <LevelBandTable levels={c.level_descriptors} />
            </div>
          ))}
        </div>
      )}

      {/* Threshold conditions, common errors, source evidence */}
      {item.threshold_conditions?.length > 0 && (
        <div className="mt-4 p-3 rounded-xl bg-sky-50/50 dark:bg-sky-900/20 border border-sky-500/20">
          <div className="text-xs font-semibold text-sky-700 dark:text-sky-300 mb-1">Threshold Conditions</div>
          {item.threshold_conditions.map((t: string, i: number) => (
            <div key={i} className="text-xs text-foreground/80">· {t}</div>
          ))}
        </div>
      )}

      {item.common_errors?.length > 0 && (
        <div className="mt-3 p-3 rounded-xl bg-rose-50/40 dark:bg-rose-900/15 border border-rose-500/20">
          <div className="text-xs font-semibold text-rose-700 dark:text-rose-300 mb-1">Common Errors to Watch For</div>
          {item.common_errors.map((e: string, i: number) => (
            <div key={i} className="text-xs text-foreground/80">· {e}</div>
          ))}
        </div>
      )}

      {item.source_evidence?.length > 0 && (
        <details className="mt-3">
          <summary className="text-xs text-muted-foreground cursor-pointer hover:text-foreground/70">
            Source evidence from the chapter ({item.source_evidence.length})
          </summary>
          <div className="mt-2 space-y-1">
            {item.source_evidence.map((q: string, i: number) => (
              <div key={i} className="text-xs italic text-muted-foreground border-l-2 border-black/10 dark:border-white/10 pl-2">
                "{q}"
              </div>
            ))}
          </div>
        </details>
      )}
    </div>
  );
}

export function SemanticIntelligenceViewer({ data }: SemanticIntelligenceViewerProps) {
  // Support new `concepts` structure, fallback to `topics` or `teaching_units`
  const isLegacy = !data?.concepts;
  const itemsList = data?.concepts || data?.topics || data?.teaching_units;

  if (!data || !itemsList || itemsList.length === 0) {
    return <div className="p-4 text-center text-muted-foreground">No Semantic Intelligence data available yet.</div>;
  }

  const [activeIndex, setActiveIndex] = useState(0);
  const [openConceptIndex, setOpenConceptIndex] = useState<number | null>(0);
  
  const activeItem = itemsList[activeIndex];

  return (
    <TooltipProvider>
      <div className="w-full flex flex-col gap-6 animate-in fade-in slide-in-from-bottom-4 duration-700">

      {/* Chapter Header */}
      <div className="p-6 rounded-2xl border-[0.5px] border-black/10 dark:border-white/10 bg-white/40 dark:bg-black/40 backdrop-blur-xl shadow-sm">
        <h2 className="text-2xl font-bold tracking-tight text-foreground/90">{data.chapter_title || data.chapter_name || "Chapter Intelligence"}</h2>
        <p className="text-muted-foreground mt-2">{data.short_summary || data.chapter_summary}</p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-4 gap-6">

        {/* Left Sidebar: Concepts/Topics */}
        <div className="col-span-1 flex flex-col gap-2">
          <h3 className="text-sm font-semibold text-foreground/50 uppercase tracking-wider pl-2 mb-2">{isLegacy ? "Teaching Topics" : "Concepts"}</h3>
          {itemsList.map((item: any, idx: number) => {
            const title = item.concept?.concept_name || item.topic_title || item.topic_name;
            const summary = item.concept?.definition || item.topic_summary;
            return (
              <button
                key={idx}
                onClick={() => {
                  setActiveIndex(idx);
                  setOpenConceptIndex(0); // Reset accordion on change (for legacy)
                }}
                className={`text-left p-4 rounded-xl transition-all duration-300 border-[0.5px] ${activeIndex === idx
                  ? "bg-white/80 dark:bg-white/10 border-black/20 dark:border-white/20 shadow-sm"
                  : "bg-transparent border-transparent hover:bg-white/30 dark:hover:bg-white/5"
                  }`}
              >
                <div className="font-semibold text-foreground/80 line-clamp-2">{title}</div>
                <div className="text-xs text-muted-foreground mt-1 line-clamp-1">{summary}</div>
              </button>
            );
          })}
        </div>

        {/* Right Content: Dimensions */}
        <div className="col-span-1 lg:col-span-3">
          {activeItem && (
            <div className="flex flex-col gap-6">

              <div className="p-6 rounded-2xl border-[0.5px] border-black/10 dark:border-white/10 bg-white/60 dark:bg-black/60 backdrop-blur-2xl shadow-sm">
                <h3 className="text-xl font-bold">{activeItem.concept?.concept_name || activeItem.topic_title || activeItem.topic_name}</h3>
                <p className="text-sm text-muted-foreground mt-2">{activeItem.concept?.definition || activeItem.topic_summary || activeItem.topic_description}</p>
                {activeItem.concept && (
                  <div className="flex flex-wrap gap-2 mt-4">
                    {activeItem.concept.concept_type && (
                      <InfoTooltip content="Concept Type: what kind of knowledge this is (Definition, Law, Process, ...).">
                        <Badge variant="outline" className="bg-white/50 dark:bg-black/50">{activeItem.concept.concept_type}</Badge>
                      </InfoTooltip>
                    )}
                    {activeItem.concept.importance && (
                      <InfoTooltip content="Importance: how central this concept is to the chapter.">
                        <Badge variant="outline" className="bg-white/50 dark:bg-black/50">Importance: {activeItem.concept.importance}</Badge>
                      </InfoTooltip>
                    )}
                    {activeItem.concept.difficulty && (
                      <InfoTooltip content="Difficulty: expected challenge level for the student.">
                        <Badge variant="outline" className="bg-white/50 dark:bg-black/50">Difficulty: {activeItem.concept.difficulty}</Badge>
                      </InfoTooltip>
                    )}
                    {activeItem.concept.confidence != null && (
                      <InfoTooltip content="Confidence: how certain the model is about this extraction.">
                        <Badge variant="outline" className="bg-white/50 dark:bg-black/50">Confidence: {activeItem.concept.confidence}</Badge>
                      </InfoTooltip>
                    )}
                    {activeItem.concept.concept_id && (
                      <Badge variant="outline" className="bg-white/50 dark:bg-black/50 font-mono text-[10px]">{activeItem.concept.concept_id}</Badge>
                    )}
                  </div>
                )}
              </div>

              <div className="w-full flex flex-col">
                {/* FALLBACK: OLD SCHEMA (with subtopics) */}
                {isLegacy && activeItem.subtopics && (
                  <div className="mb-6 p-4 rounded-xl border border-yellow-500/30 bg-yellow-500/10 text-yellow-800 dark:text-yellow-200 flex items-start gap-3">
                    <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="mt-0.5"><path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z" /><path d="M12 9v4" /><path d="M12 17h.01" /></svg>
                    <div>
                      <p className="font-semibold">Legacy Extraction Detected</p>
                      <p className="text-sm opacity-90 mt-1">This chapter was processed using the older 6-dimension schema. To see all 13 intelligence dimensions, please go back to the table and click <b>Reprocess</b> on this chapter.</p>
                    </div>
                  </div>
                )}
                {isLegacy && activeItem.subtopics && activeItem.subtopics.map((sub: any, cIdx: number) => (
                  <CustomAccordionItem
                    key={cIdx}
                    isOpen={openConceptIndex === cIdx}
                    onClick={() => setOpenConceptIndex(openConceptIndex === cIdx ? null : cIdx)}
                    title={sub.subtopic_title}
                    badge={sub.bloom_level}
                    subtitle={sub.subtopic_summary}
                  >
                    <Tabs defaultValue="knowledge" className="w-full mt-2">
                      <TabsList className="mb-6 bg-black/5 dark:bg-white/5 border border-black/5 dark:border-white/10 rounded-xl p-1 inline-flex w-full overflow-x-auto justify-start h-auto flex-wrap gap-1">
                        <TabsTrigger value="knowledge" className="rounded-lg px-3 py-1.5 text-xs cursor-pointer flex items-center gap-1.5"><Brain className="w-3.5 h-3.5"/> Knowledge</TabsTrigger>
                        <TabsTrigger value="pedagogy" className="rounded-lg px-3 py-1.5 text-xs cursor-pointer flex items-center gap-1.5"><Lightbulb className="w-3.5 h-3.5"/> Pedagogy</TabsTrigger>
                        <TabsTrigger value="misconception" className="rounded-lg px-3 py-1.5 text-xs cursor-pointer flex items-center gap-1.5"><AlertTriangle className="w-3.5 h-3.5"/> Misconceptions</TabsTrigger>
                        <TabsTrigger value="realworld" className="rounded-lg px-3 py-1.5 text-xs cursor-pointer flex items-center gap-1.5"><Globe className="w-3.5 h-3.5"/> Real World</TabsTrigger>
                        <TabsTrigger value="activities" className="rounded-lg px-3 py-1.5 text-xs">Activities</TabsTrigger>
                        <TabsTrigger value="outcomes" className="rounded-lg px-3 py-1.5 text-xs cursor-pointer flex items-center gap-1.5"><CheckCircle className="w-3.5 h-3.5"/> Outcomes</TabsTrigger>
                      </TabsList>

                      <TabsContent value="knowledge" className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4 mt-4">
                        {sub.detailed_explanation && (
                          <div className="p-4 rounded-xl border border-black/5 dark:border-white/5 bg-white/50 dark:bg-black/50">
                            <h4 className="font-semibold text-sm uppercase tracking-wider text-muted-foreground mb-2">Detailed Explanation</h4>
                            <p className="text-sm text-foreground/80">{sub.detailed_explanation}</p>
                          </div>
                        )}
                        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                          {sub.important_lines && sub.important_lines.length > 0 && (
                            <div className="p-4 rounded-xl border border-indigo-500/20 bg-indigo-50/30 dark:bg-indigo-900/10">
                              <h4 className="font-semibold text-sm uppercase tracking-wider text-muted-foreground mb-3 text-indigo-700 dark:text-indigo-400">Important Lines</h4>
                              <ul className="list-disc pl-5 space-y-1 text-sm text-foreground/80">
                                {sub.important_lines.map((line: string, i: number) => <li key={i}>{line}</li>)}
                              </ul>
                            </div>
                          )}
                          {sub.formulas && sub.formulas.length > 0 && (
                            <div className="p-4 rounded-xl border border-amber-500/20 bg-amber-50/30 dark:bg-amber-900/10">
                              <h4 className="font-semibold text-sm uppercase tracking-wider text-muted-foreground mb-3 text-amber-700 dark:text-amber-400">Formulas</h4>
                              <ul className="space-y-2">
                                {sub.formulas.map((form: string, i: number) => <li key={i} className="font-mono text-sm bg-black/5 px-3 py-2 rounded-md">{form}</li>)}
                              </ul>
                            </div>
                          )}
                        </div>
                      </TabsContent>

                      <TabsContent value="pedagogy" className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4 mt-4">
                        {sub.teacher_teaching_notes && (
                          <div className="p-4 rounded-xl border border-blue-500/20 bg-blue-50/30 dark:bg-blue-900/10">
                            <h4 className="font-semibold text-sm uppercase tracking-wider text-muted-foreground mb-2">Teacher's Notes</h4>
                            <p className="text-sm text-foreground/80">{sub.teacher_teaching_notes}</p>
                          </div>
                        )}
                        {sub.diagram_explanations && sub.diagram_explanations.length > 0 && (
                          <div className="p-4 rounded-xl border border-emerald-500/20 bg-emerald-50/30 dark:bg-emerald-900/10">
                            <h4 className="font-semibold text-sm uppercase tracking-wider text-muted-foreground mb-2">Diagram Explanations</h4>
                            <ul className="list-disc pl-5 space-y-1 text-sm text-foreground/80">
                              {sub.diagram_explanations.map((diag: string, i: number) => <li key={i}>{diag}</li>)}
                            </ul>
                          </div>
                        )}
                      </TabsContent>

                      <TabsContent value="misconception" className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4 mt-4">
                        {sub.common_student_confusion && (
                          <div className="p-4 rounded-xl border border-red-500/20 bg-red-50/30 dark:bg-red-900/10">
                            <h4 className="font-semibold text-sm uppercase tracking-wider text-muted-foreground mb-2 text-red-700">Common Confusion</h4>
                            <p className="text-sm text-foreground/80">{sub.common_student_confusion}</p>
                          </div>
                        )}
                      </TabsContent>

                      <TabsContent value="realworld" className="space-y-4">
                        {sub.real_life_connection && (
                          <div className="p-4 rounded-xl border border-emerald-500/20 bg-emerald-50/30 dark:bg-emerald-900/10">
                            <h4 className="font-semibold text-sm uppercase tracking-wider text-muted-foreground mb-2">Real Life Connection</h4>
                            <p className="text-sm text-foreground/80">{sub.real_life_connection}</p>
                          </div>
                        )}
                        {sub.examples && sub.examples.length > 0 && (
                          <div className="p-4 rounded-xl border border-black/5 dark:border-white/5 bg-white/50 dark:bg-black/50">
                            <h4 className="font-semibold text-sm uppercase tracking-wider text-muted-foreground mb-2">Examples</h4>
                            <ul className="list-disc pl-5 space-y-1 text-sm text-foreground/80">
                              {sub.examples.map((ex: string, i: number) => <li key={i}>{ex}</li>)}
                            </ul>
                          </div>
                        )}
                      </TabsContent>

                      <TabsContent value="activities" className="space-y-4">
                        {sub.activities && sub.activities.length > 0 && (
                          <div className="p-4 rounded-xl border border-teal-500/20 bg-teal-50/30 dark:bg-teal-900/10">
                            <h4 className="font-semibold text-sm uppercase tracking-wider text-muted-foreground mb-2">Activities</h4>
                            <ul className="space-y-2">
                              {sub.activities.map((act: string, i: number) => <li key={i} className="text-sm flex gap-2"><div className="mt-1 w-1.5 h-1.5 rounded-full bg-teal-500"></div>{act}</li>)}
                            </ul>
                          </div>
                        )}
                      </TabsContent>

                      <TabsContent value="outcomes" className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4 mt-4">
                        {sub.learning_outcomes && sub.learning_outcomes.length > 0 && (
                          <div className="p-4 rounded-xl border border-violet-500/20 bg-violet-50/30 dark:bg-violet-900/10">
                            <h4 className="font-semibold text-sm uppercase tracking-wider text-muted-foreground mb-2">Learning Outcomes</h4>
                            <ul className="space-y-2">
                              {sub.learning_outcomes.map((lo: string, i: number) => <li key={i} className="text-sm flex gap-2"><div className="w-5 h-5 rounded-full bg-violet-500/20 flex items-center justify-center text-violet-700 text-xs">✓</div>{lo}</li>)}
                            </ul>
                          </div>
                        )}
                      </TabsContent>
                    </Tabs>
                  </CustomAccordionItem>
                ))}

                {/* NEW SCHEMA: FLAT CONCEPT LAYER WITH 13 DIMENSIONS */}
                {!isLegacy && (
                  <div className="animate-in fade-in slide-in-from-top-2 duration-300">
                    <Tabs defaultValue="knowledge" className="w-full mt-2">
                      <TabsList className="mb-6 bg-black/5 dark:bg-white/5 border border-black/5 dark:border-white/10 rounded-xl p-1 inline-flex w-full overflow-x-auto justify-start h-auto flex-wrap gap-1">
                        <TabsTrigger value="knowledge" className="rounded-lg px-3 py-1.5 text-xs cursor-pointer flex items-center gap-1.5"><Brain className="w-3.5 h-3.5"/> Knowledge</TabsTrigger>
                        <TabsTrigger value="ability" className="rounded-lg px-3 py-1.5 text-xs cursor-pointer flex items-center gap-1.5"><Target className="w-3.5 h-3.5"/> Ability</TabsTrigger>
                        <TabsTrigger value="skill" className="rounded-lg px-3 py-1.5 text-xs cursor-pointer flex items-center gap-1.5"><Zap className="w-3.5 h-3.5"/> Skill</TabsTrigger>
                        <TabsTrigger value="competency" className="rounded-lg px-3 py-1.5 text-xs cursor-pointer flex items-center gap-1.5"><Award className="w-3.5 h-3.5"/> Competency</TabsTrigger>
                        <TabsTrigger value="blooms" className="rounded-lg px-3 py-1.5 text-xs cursor-pointer flex items-center gap-1.5"><Layers className="w-3.5 h-3.5"/> Bloom's</TabsTrigger>
                        <TabsTrigger value="dok" className="rounded-lg px-3 py-1.5 text-xs cursor-pointer flex items-center gap-1.5"><BarChart className="w-3.5 h-3.5"/> DOK</TabsTrigger>
                        <TabsTrigger value="prerequisite" className="rounded-lg px-3 py-1.5 text-xs cursor-pointer flex items-center gap-1.5"><LinkIcon className="w-3.5 h-3.5"/> Prerequisites</TabsTrigger>
                        <TabsTrigger value="misconception" className="rounded-lg px-3 py-1.5 text-xs cursor-pointer flex items-center gap-1.5"><AlertTriangle className="w-3.5 h-3.5"/> Misconceptions</TabsTrigger>
                        <TabsTrigger value="realworld" className="rounded-lg px-3 py-1.5 text-xs cursor-pointer flex items-center gap-1.5"><Globe className="w-3.5 h-3.5"/> Real World</TabsTrigger>
                        <TabsTrigger value="pedagogy" className="rounded-lg px-3 py-1.5 text-xs cursor-pointer flex items-center gap-1.5"><Lightbulb className="w-3.5 h-3.5"/> Pedagogy</TabsTrigger>
                        <TabsTrigger value="objectives" className="rounded-lg px-3 py-1.5 text-xs cursor-pointer flex items-center gap-1.5"><Flag className="w-3.5 h-3.5"/> Objectives</TabsTrigger>
                        <TabsTrigger value="outcomes" className="rounded-lg px-3 py-1.5 text-xs cursor-pointer flex items-center gap-1.5"><CheckCircle className="w-3.5 h-3.5"/> Outcomes</TabsTrigger>
                        <TabsTrigger value="blueprint" className="rounded-lg px-3 py-1.5 text-xs cursor-pointer flex items-center gap-1.5"><FileText className="w-3.5 h-3.5"/> Blueprint</TabsTrigger>
                        <TabsTrigger value="rubrics" className="rounded-lg px-3 py-1.5 text-xs cursor-pointer flex items-center gap-1.5"><ClipboardCheck className="w-3.5 h-3.5"/> Rubrics</TabsTrigger>
                        <TabsTrigger value="relationships" className="rounded-lg px-3 py-1.5 text-xs cursor-pointer flex items-center gap-1.5"><Network className="w-3.5 h-3.5"/> Relationships</TabsTrigger>
                        <TabsTrigger value="evidence" className="rounded-lg px-3 py-1.5 text-xs cursor-pointer flex items-center gap-1.5"><Quote className="w-3.5 h-3.5"/> Evidence</TabsTrigger>
                        <TabsTrigger value="reasoning" className="rounded-lg px-3 py-1.5 text-xs cursor-pointer flex items-center gap-1.5"><Sparkles className="w-3.5 h-3.5"/> AI Reasoning</TabsTrigger>
                      </TabsList>

                      {/* 1. KNOWLEDGE */}
                      <TabsContent value="knowledge" className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4 mt-4">
                        {activeItem.knowledge_items?.map((k: any, i: number) => (
                          <div key={i} className="p-4 rounded-xl border border-black/5 dark:border-white/5 bg-white/50 dark:bg-black/50">
                            <div className="flex justify-between items-start mb-2">
                              <span className="font-bold text-lg">{k.knowledge}</span>
                              <Badge variant="outline">{k.knowledge_type}</Badge>
                            </div>
                            <p className="text-sm text-muted-foreground mb-3">{k.statement}</p>
                            <div className="flex gap-2 text-xs mt-3">
                              <InfoTooltip content="Confidence score of extraction"><span className="bg-black/5 px-2 py-1 rounded hover:bg-black/10 transition-colors">Confidence: {k.confidence}</span></InfoTooltip>
                            </div>
                          </div>
                        ))}
                      </TabsContent>

                      {/* 2. ABILITY */}
                      <TabsContent value="ability" className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4 mt-4">
                        {activeItem.abilities?.map((a: any, i: number) => (
                          <div key={i} className="p-4 rounded-xl border border-blue-500/20 bg-blue-50/30 dark:bg-blue-900/10">
                            <div className="flex items-center gap-2 mb-3">
                              <InfoTooltip content="Action Verb"><Badge className="bg-blue-500 text-white hover:bg-blue-600">{formatValue(a.verb)}</Badge></InfoTooltip>
                            </div>
                            <div className="font-bold text-blue-900 dark:text-blue-200 mb-2">{a.ability}</div>
                            <p className="text-foreground/90 text-sm mb-3">{a.description}</p>
                            {a.knowledge_refs && a.knowledge_refs.length > 0 && (
                              <div className="text-xs text-blue-700/70 dark:text-blue-300/70">
                                <b>Refs:</b> {a.knowledge_refs.join(", ")}
                              </div>
                            )}
                          </div>
                        ))}
                      </TabsContent>

                      {/* 3. SKILL */}
                      <TabsContent value="skill" className="space-y-4 mt-4">
                        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                          {activeItem.skills?.map((s: any, i: number) => (
                            <div key={i} className="p-4 rounded-xl border border-teal-500/20 bg-teal-50/30 dark:bg-teal-900/10">
                              <div className="font-bold text-teal-800 dark:text-teal-200 mb-2">{s.skill}</div>
                              {s.ability_refs && s.ability_refs.length > 0 && (
                                <div className="text-xs text-teal-700/70 dark:text-teal-300/70 mt-2">
                                  <b>Ability Refs:</b> {s.ability_refs.join(", ")}
                                </div>
                              )}
                            </div>
                          ))}
                        </div>
                      </TabsContent>

                      {/* 4. COMPETENCY */}
                      <TabsContent value="competency" className="space-y-4 mt-4">
                        {activeItem.competencies?.map((c: any, i: number) => (
                          <div key={i} className="p-4 rounded-xl border border-indigo-500/20 bg-indigo-50/30 dark:bg-indigo-900/10">
                            <div className="font-bold text-indigo-800 dark:text-indigo-300 mb-2">{c.competency}</div>
                            <p className="text-sm text-foreground/90 italic mb-3">"{c.statement}"</p>
                            <div className="flex flex-wrap gap-2 text-[10px] opacity-70">
                              {c.knowledge_refs && c.knowledge_refs.length > 0 && <span className="bg-indigo-500/10 px-2 py-1 rounded"><b>Knowledge:</b> {c.knowledge_refs.join(", ")}</span>}
                              {c.ability_refs && c.ability_refs.length > 0 && <span className="bg-indigo-500/10 px-2 py-1 rounded"><b>Ability:</b> {c.ability_refs.join(", ")}</span>}
                              {c.skill_refs && c.skill_refs.length > 0 && <span className="bg-indigo-500/10 px-2 py-1 rounded"><b>Skill:</b> {c.skill_refs.join(", ")}</span>}
                            </div>
                          </div>
                        ))}
                      </TabsContent>

                      {/* 5. BLOOMS */}
                      <TabsContent value="blooms" className="space-y-4 mt-4">
                        <div className="flex flex-wrap gap-3">
                          {activeItem.blooms?.map((b: any, i: number) => (
                            <div key={i} className="px-4 py-2 rounded-xl border border-purple-500/20 bg-purple-50/30 dark:bg-purple-900/10 flex items-center gap-2">
                              <span className="font-bold text-purple-700 dark:text-purple-300">{b.level}</span>
                              <span className="text-xs text-muted-foreground">{Math.round(b.coverage_score * 100)}%</span>
                            </div>
                          ))}
                        </div>
                      </TabsContent>

                      {/* 6. DOK */}
                      <TabsContent value="dok" className="space-y-4 mt-4">
                        {activeItem.dok?.map((d: any, i: number) => (
                          <div key={i} className="p-4 rounded-xl border border-amber-500/20 bg-amber-50/30 dark:bg-amber-900/10 flex items-center gap-4">
                            <div className="w-10 h-10 rounded-full bg-amber-500 text-white flex items-center justify-center font-bold text-xl">{d.level}</div>
                            <div className="font-medium text-amber-900 dark:text-amber-200">{d.description}</div>
                          </div>
                        ))}
                      </TabsContent>

                      {/* 7. PREREQUISITES */}
                      <TabsContent value="prerequisite" className="space-y-4 mt-4">
                        {activeItem.prerequisites?.map((p: any, i: number) => (
                          <div key={i} className="p-3 rounded-xl border border-black/5 dark:border-white/5 bg-white/50 dark:bg-black/50 flex justify-between items-center">
                            <div className="flex flex-col">
                              <span className="font-bold">{p.concept_name}</span>
                              <span className="text-xs text-muted-foreground">{p.prerequisite_type}</span>
                            </div>
                            <InfoTooltip content="Necessity: Whether this prerequisite is absolutely required or just helpful."><Badge variant="secondary">{formatValue(p.necessity)}</Badge></InfoTooltip>
                          </div>
                        ))}
                      </TabsContent>

                      {/* 8. MISCONCEPTIONS */}
                      <TabsContent value="misconception" className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4 mt-4">
                        {activeItem.misconceptions?.map((m: any, i: number) => (
                          <div key={i} className="p-4 rounded-xl border border-red-500/20 bg-red-50/30 dark:bg-red-900/10 flex flex-col">
                            <div className="font-bold text-red-800 dark:text-red-300 mb-2 flex gap-1.5 items-start">
                              <AlertTriangle className="w-4 h-4 mt-0.5" />
                              <span>{m.misconception}</span>
                            </div>
                            <p className="text-sm text-red-700/90 mb-3">{m.statement}</p>
                            <div className="mt-auto space-y-2 text-xs">
                              <div className="bg-red-500/10 p-2 rounded-lg">
                                <span className="font-bold block mb-0.5 text-red-800/80 dark:text-red-300/80">Root Cause</span>
                                <span className="text-red-900 dark:text-red-100 opacity-90">{m.root_cause}</span>
                              </div>
                              <div className="bg-green-500/10 p-2 rounded-lg border border-green-500/20">
                                <span className="font-bold block mb-0.5 text-green-800 dark:text-green-300">Correction</span>
                                <span className="text-green-900 dark:text-green-100 opacity-90">{m.correction}</span>
                              </div>
                            </div>
                          </div>
                        ))}
                      </TabsContent>

                      {/* 9. REAL WORLD */}
                      <TabsContent value="realworld" className="space-y-4 mt-4">
                        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                          {activeItem.real_world_applications?.map((r: any, i: number) => (
                            <div key={i} className="p-4 rounded-xl border border-emerald-500/20 bg-emerald-50/30 dark:bg-emerald-900/10">
                              <Badge className="bg-emerald-500/20 text-emerald-800 border-none mb-2 hover:bg-emerald-500/30">{r.application_type}</Badge>
                              <p className="text-sm text-foreground/80">{r.example}</p>
                            </div>
                          ))}
                        </div>
                      </TabsContent>

                      {/* 10. PEDAGOGY */}
                      <TabsContent value="pedagogy" className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4 mt-4">
                        {activeItem.pedagogy_recommendations?.map((p: any, i: number) => (
                          <div key={i} className="p-4 rounded-xl border border-black/5 dark:border-white/5 bg-white/50 dark:bg-black/50">
                            <div className="flex justify-between items-start mb-2">
                              <span className="font-bold text-lg">{p.strategy}</span>
                            </div>
                            <p className="text-sm text-muted-foreground mb-3">{p.why_effective}</p>
                            {p.concept_characteristics && p.concept_characteristics.length > 0 && (
                              <div className="flex flex-wrap gap-1 mt-2">
                                {p.concept_characteristics.map((char: string, idx: number) => (
                                  <Badge key={idx} variant="outline" className="text-[10px] bg-black/5 border-none">{char}</Badge>
                                ))}
                              </div>
                            )}
                          </div>
                        ))}
                      </TabsContent>

                      {/* 11. OBJECTIVES */}
                      <TabsContent value="objectives" className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4 mt-4">
                        {activeItem.learning_objectives?.map((lo: any, i: number) => (
                          <div key={i} className="p-3 rounded-xl border border-black/5 dark:border-white/5 bg-white/50 dark:bg-black/50 flex items-start gap-3">
                            <div className="mt-1 w-2 h-2 rounded-full bg-blue-500 flex-shrink-0"></div>
                            <div>
                              <p className="font-medium text-sm">{lo.objective}</p>
                              <div className="flex gap-2 mt-2">
                                <Badge variant="secondary" className="text-[10px]">{lo.objective_type}</Badge>
                                <Badge variant="outline" className="text-[10px]">{lo.priority} Priority</Badge>
                              </div>
                            </div>
                          </div>
                        ))}
                      </TabsContent>

                      {/* 12. OUTCOMES */}
                      <TabsContent value="outcomes" className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4 mt-4">
                        {activeItem.learning_outcomes?.map((lo: any, i: number) => (
                          <div key={i} className="p-3 rounded-xl border border-emerald-500/20 bg-emerald-50/10 dark:bg-emerald-900/10 flex items-start gap-3">
                            <div className="mt-0.5 w-5 h-5 rounded-full bg-emerald-500/20 flex items-center justify-center text-emerald-600 flex-shrink-0">✓</div>
                            <div>
                              <p className="font-medium text-sm">{lo.outcome}</p>
                              <div className="flex gap-2 mt-2">
                                <Badge variant="secondary" className="text-[10px]">{lo.outcome_type}</Badge>
                                {lo.measurable && <Badge variant="outline" className="text-[10px] border-emerald-500/30 text-emerald-600">Measurable</Badge>}
                              </div>
                            </div>
                          </div>
                        ))}
                      </TabsContent>

                      {/* 13. BLUEPRINT */}
                      <TabsContent value="blueprint" className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4 mt-4">
                        {activeItem.assessment_blueprint?.map((ab: any, i: number) => (
                          <div key={i} className="p-4 rounded-xl border border-amber-500/20 bg-amber-50/30 dark:bg-amber-900/10">
                            <div className="flex justify-between items-start mb-3 gap-4">
                              <div className="font-medium italic text-foreground/90 text-sm">"{ab.recommended_question}"</div>
                              <div className="font-bold text-amber-600 bg-amber-100 dark:bg-amber-900/50 px-2 py-1 rounded text-sm whitespace-nowrap">{ab.marks} Marks</div>
                            </div>
                            <div className="flex flex-wrap gap-2 mt-3">
                              <InfoTooltip content="Assessment Type: The format of the question (e.g., MCQ, Short Answer)."><Badge variant="outline" className="bg-white/50 dark:bg-black/50 hover:bg-black/5">{ab.assessment_type}</Badge></InfoTooltip>
                              <InfoTooltip content="Difficulty: The expected challenge level for the student."><Badge variant="outline" className="bg-white/50 dark:bg-black/50 hover:bg-black/5">Difficulty: {ab.difficulty}</Badge></InfoTooltip>
                              <InfoTooltip content="Bloom's Level: The cognitive skill targeted by this question."><Badge variant="outline" className="bg-white/50 dark:bg-black/50 hover:bg-black/5">Bloom: {ab.bloom_level}</Badge></InfoTooltip>
                              <InfoTooltip content="Depth of Knowledge (DOK): The complexity of reasoning required."><Badge variant="outline" className="bg-white/50 dark:bg-black/50 hover:bg-black/5">DOK {ab.dok_level}</Badge></InfoTooltip>
                            </div>
                          </div>
                        ))}
                      </TabsContent>

                      {/* 14. ASSESSMENT RUBRICS */}
                      <TabsContent value="rubrics" className="space-y-4 mt-4">
                        {!activeItem.assessment_rubrics?.items?.length ? (
                          <div className="p-6 rounded-2xl border border-dashed border-black/15 dark:border-white/15 text-center text-sm text-muted-foreground">
                            No assessment rubrics for this concept yet. Reprocess this chapter to generate them.
                          </div>
                        ) : (
                          <>
                            {/* Teacher guidance */}
                            {activeItem.assessment_rubrics.teaching_notes && (() => {
                              const tn = activeItem.assessment_rubrics.teaching_notes;
                              const tipGroups = [
                                ["Written evidence", tn.written_evidence_tips],
                                ["Oral evidence", tn.oral_evidence_tips],
                                ["Experimental evidence", tn.experimental_evidence_tips],
                              ].filter(([, v]: any) => v?.length > 0);
                              return (
                                <div className="p-5 rounded-2xl border border-teal-500/20 bg-teal-50/30 dark:bg-teal-900/10">
                                  <div className="font-semibold text-sm text-teal-800 dark:text-teal-200 mb-3">Notes for Teachers</div>
                                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                                    {tn.key_vocabulary?.length > 0 && (
                                      <div>
                                        <div className="text-xs font-semibold text-muted-foreground mb-1.5">Key Vocabulary</div>
                                        <div className="flex flex-wrap gap-1.5">
                                          {tn.key_vocabulary.map((v: string, i: number) => (
                                            <Badge key={i} variant="secondary" className="text-[10px]">{v}</Badge>
                                          ))}
                                        </div>
                                      </div>
                                    )}
                                    {tn.blooms_verbs_used?.length > 0 && (
                                      <div>
                                        <div className="text-xs font-semibold text-muted-foreground mb-1.5">Bloom's Verbs Used</div>
                                        <div className="flex flex-wrap gap-1.5">
                                          {tn.blooms_verbs_used.map((v: string, i: number) => (
                                            <Badge key={i} variant="outline" className="text-[10px]">{v}</Badge>
                                          ))}
                                        </div>
                                      </div>
                                    )}
                                    {tn.practical_activities?.length > 0 && (
                                      <div className="md:col-span-2">
                                        <div className="text-xs font-semibold text-muted-foreground mb-1.5">Suggested Activities</div>
                                        {tn.practical_activities.map((a: string, i: number) => (
                                          <div key={i} className="text-sm text-foreground/80">· {a}</div>
                                        ))}
                                      </div>
                                    )}
                                    {tipGroups.map(([label, tips]: any, i: number) => (
                                      <div key={i}>
                                        <div className="text-xs font-semibold text-muted-foreground mb-1.5">{label}</div>
                                        {tips.map((t: string, j: number) => (
                                          <div key={j} className="text-xs text-foreground/80">· {t}</div>
                                        ))}
                                      </div>
                                    ))}
                                  </div>
                                </div>
                              );
                            })()}

                            {activeItem.assessment_rubrics.items.map((item: any, i: number) => (
                              <RubricItemCard key={i} item={item} />
                            ))}
                          </>
                        )}
                      </TabsContent>

                      {/* 15. CONCEPT RELATIONSHIPS */}
                      <TabsContent value="relationships" className="grid grid-cols-1 md:grid-cols-2 gap-4 mt-4">
                        {!activeItem.concept_relationships?.length ? (
                          <div className="md:col-span-2 p-6 rounded-2xl border border-dashed border-black/15 dark:border-white/15 text-center text-sm text-muted-foreground">
                            No concept relationships extracted for this concept.
                          </div>
                        ) : activeItem.concept_relationships.map((r: any, i: number) => (
                          <div key={i} className="p-4 rounded-xl border border-cyan-500/20 bg-cyan-50/30 dark:bg-cyan-900/10">
                            <div className="flex items-center gap-2 flex-wrap">
                              <span className="font-semibold text-sm">{r.source_concept}</span>
                              <Badge className="bg-cyan-600 text-white hover:bg-cyan-700 text-[10px] font-mono">
                                {formatValue(r.relation_type)}
                              </Badge>
                              <span className="font-semibold text-sm">{r.target_concept}</span>
                            </div>
                          </div>
                        ))}
                      </TabsContent>

                      {/* 16. EVIDENCE */}
                      <TabsContent value="evidence" className="space-y-3 mt-4">
                        {!activeItem.evidence?.length ? (
                          <div className="p-6 rounded-2xl border border-dashed border-black/15 dark:border-white/15 text-center text-sm text-muted-foreground">
                            No evidence captured for this concept.
                          </div>
                        ) : (
                          <>
                            <p className="text-xs text-muted-foreground">
                              Source traceability for this concept's extractions. "Textbook" and "Curriculum" are quoted from the material; "Inferred" was reasoned by the model and is not a direct quote.
                            </p>
                            {activeItem.evidence.map((e: any, i: number) => {
                              const inferred = e.source_type === "Inferred";
                              return (
                                <div key={i} className={`p-4 rounded-xl border ${inferred
                                  ? "border-amber-500/25 bg-amber-50/30 dark:bg-amber-900/10"
                                  : "border-black/10 dark:border-white/10 bg-white/50 dark:bg-black/40"}`}>
                                  <Badge variant="outline" className={`text-[10px] mb-2 ${inferred ? "border-amber-500/40 text-amber-600" : ""}`}>
                                    {e.source_type}
                                  </Badge>
                                  <p className="text-sm text-foreground/80 italic">"{e.source_text}"</p>
                                </div>
                              );
                            })}
                          </>
                        )}
                      </TabsContent>

                      {/* 17. AI REASONING */}
                      <TabsContent value="reasoning" className="space-y-4 mt-4">
                        {(() => {
                          const ar = activeItem.agent_reasoning;
                          const agents = [
                            ["Agent 1 — Cognitive Intelligence", "Knowledge, abilities, skills, competencies, Bloom's and DOK", ar?.cognitive],
                            ["Agent 2 — Pedagogy Intelligence", "Prerequisites, misconceptions, real-world applications, teaching strategies", ar?.pedagogy],
                            ["Agent 3 — Assessment Intelligence", "Learning objectives, outcomes and the assessment blueprint", ar?.assessment],
                            ["Agent 4 — Assessment Rubrics", "Question items, mark schemes and CBSE band alignment", ar?.rubrics],
                          ].filter(([, , text]: any) => text);

                          if (agents.length === 0) {
                            return (
                              <div className="p-6 rounded-2xl border border-dashed border-black/15 dark:border-white/15 text-center text-sm text-muted-foreground">
                                No reasoning stored for this concept. Chapters processed before this feature was added will not have it — reprocess to capture it.
                              </div>
                            );
                          }
                          return (
                            <>
                              <p className="text-xs text-muted-foreground">
                                Each agent writes its reasoning before extracting, so the reasoning shapes the output that follows. Use this to audit <i>why</i> the model extracted what it did.
                              </p>
                              {agents.map(([title, subtitle, text]: any, i: number) => (
                                <div key={i} className="p-5 rounded-2xl border border-fuchsia-500/20 bg-fuchsia-50/25 dark:bg-fuchsia-900/10">
                                  <div className="font-semibold text-sm text-fuchsia-800 dark:text-fuchsia-200">{title}</div>
                                  <div className="text-xs text-muted-foreground mb-3">{subtitle}</div>
                                  <p className="text-sm text-foreground/80 whitespace-pre-wrap leading-relaxed">{text}</p>
                                </div>
                              ))}
                            </>
                          );
                        })()}
                      </TabsContent>
                    </Tabs>
                  </div>
                )}
              </div>

            </div>
          )}
        </div>

      </div>
      </div>
    </TooltipProvider>
  );
}
