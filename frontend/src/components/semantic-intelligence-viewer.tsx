import React, { useState } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { Brain, Target, Zap, Award, Layers, BarChart, Link as LinkIcon, AlertTriangle, Globe, Lightbulb, Flag, CheckCircle, FileText } from "lucide-react";

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

export function SemanticIntelligenceViewer({ data }: SemanticIntelligenceViewerProps) {
  // Support both new `topics` structure and existing `teaching_units` structure
  const topicsList = data?.teaching_units || data?.topics;

  if (!data || !topicsList) {
    return <div className="p-4 text-center text-muted-foreground">No Semantic Intelligence data available yet.</div>;
  }

  const [activeTopic, setActiveTopic] = useState(0);
  const [openConceptIndex, setOpenConceptIndex] = useState<number | null>(0);

  return (
    <TooltipProvider delayDuration={100}>
      <div className="w-full flex flex-col gap-6 animate-in fade-in slide-in-from-bottom-4 duration-700">

      {/* Chapter Header */}
      <div className="p-6 rounded-2xl border-[0.5px] border-black/10 dark:border-white/10 bg-white/40 dark:bg-black/40 backdrop-blur-xl shadow-sm">
        <h2 className="text-2xl font-bold tracking-tight text-foreground/90">{data.chapter_title || data.chapter_name || "Chapter Intelligence"}</h2>
        <p className="text-muted-foreground mt-2">{data.short_summary || data.chapter_summary}</p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-4 gap-6">

        {/* Left Sidebar: Topics/Teaching Units */}
        <div className="col-span-1 flex flex-col gap-2">
          <h3 className="text-sm font-semibold text-foreground/50 uppercase tracking-wider pl-2 mb-2">Teaching Topics</h3>
          {topicsList.map((topic: any, idx: number) => (
            <button
              key={idx}
              onClick={() => {
                setActiveTopic(idx);
                setOpenConceptIndex(0); // Reset accordion on topic change
              }}
              className={`text-left p-4 rounded-xl transition-all duration-300 border-[0.5px] ${activeTopic === idx
                ? "bg-white/80 dark:bg-white/10 border-black/20 dark:border-white/20 shadow-sm"
                : "bg-transparent border-transparent hover:bg-white/30 dark:hover:bg-white/5"
                }`}
            >
              <div className="font-semibold text-foreground/80 line-clamp-2">{topic.topic_title || topic.topic_name}</div>
              <div className="text-xs text-muted-foreground mt-1 line-clamp-1">{topic.topic_summary}</div>
            </button>
          ))}
        </div>

        {/* Right Content: Subtopics / 13 Dimensions */}
        <div className="col-span-1 lg:col-span-3">
          {topicsList[activeTopic] && (
            <div className="flex flex-col gap-6">

              <div className="p-6 rounded-2xl border-[0.5px] border-black/10 dark:border-white/10 bg-white/60 dark:bg-black/60 backdrop-blur-2xl shadow-sm">
                <h3 className="text-xl font-bold">{topicsList[activeTopic].topic_title || topicsList[activeTopic].topic_name}</h3>
                <p className="text-sm text-muted-foreground mt-2">{topicsList[activeTopic].topic_summary || topicsList[activeTopic].topic_description}</p>
              </div>

              <div className="w-full flex flex-col">
                {/* FALLBACK: OLD SCHEMA (with subtopics) */}
                {topicsList[activeTopic].subtopics && (
                  <div className="mb-6 p-4 rounded-xl border border-yellow-500/30 bg-yellow-500/10 text-yellow-800 dark:text-yellow-200 flex items-start gap-3">
                    <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="mt-0.5"><path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z" /><path d="M12 9v4" /><path d="M12 17h.01" /></svg>
                    <div>
                      <p className="font-semibold">Legacy Extraction Detected</p>
                      <p className="text-sm opacity-90 mt-1">This chapter was processed using the older 6-dimension schema. To see all 13 intelligence dimensions, please go back to the table and click <b>Reprocess</b> on this chapter.</p>
                    </div>
                  </div>
                )}
                {topicsList[activeTopic].subtopics && topicsList[activeTopic].subtopics.map((sub: any, cIdx: number) => (
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

                {/* NEW SCHEMA: CONCEPT LAYER WITH 15 DIMENSIONS */}
                {topicsList[activeTopic].concepts && topicsList[activeTopic].concepts.map((conceptObj: any, cIdx: number) => (
                  <CustomAccordionItem
                    key={`new-${cIdx}`}
                    isOpen={openConceptIndex === `new-${cIdx}`}
                    onClick={() => setOpenConceptIndex(openConceptIndex === `new-${cIdx}` ? null : `new-${cIdx}`)}
                    title={conceptObj.concept?.concept_name || "Concept"}
                    badge={conceptObj.concept?.concept_type || "Type"}
                    subtitle={conceptObj.concept?.definition || ""}
                  >
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
                      </TabsList>

                      {/* 1. KNOWLEDGE */}
                      <TabsContent value="knowledge" className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4 mt-4">
                        {conceptObj.knowledge_items?.map((k: any, i: number) => (
                          <div key={i} className="p-4 rounded-xl border border-black/5 dark:border-white/5 bg-white/50 dark:bg-black/50">
                            <div className="flex justify-between items-start mb-2">
                              <span className="font-bold text-lg">{k.name}</span>
                              <Badge variant="outline">{k.knowledge_type}</Badge>
                            </div>
                            <p className="text-sm text-muted-foreground mb-3">{k.description}</p>
                            <div className="flex gap-2 text-xs mt-3">
                              <InfoTooltip content="Importance: Indicates if this knowledge is core to passing exams or just supporting context."><span className="bg-black/5 px-2 py-1 rounded hover:bg-black/10 transition-colors">Importance: {formatValue(k.importance)}</span></InfoTooltip>
                              <InfoTooltip content="Difficulty: Defines how hard this concept is for students to grasp initially."><span className="bg-black/5 px-2 py-1 rounded hover:bg-black/10 transition-colors">Difficulty: {formatValue(k.difficulty)}</span></InfoTooltip>
                              <InfoTooltip content="Retention: Measures how critical it is for the student to remember this long-term."><span className="bg-black/5 px-2 py-1 rounded hover:bg-black/10 transition-colors">Retention: {formatValue(k.retention_priority)}</span></InfoTooltip>
                            </div>
                          </div>
                        ))}
                      </TabsContent>

                      {/* 2. ABILITY */}
                      <TabsContent value="ability" className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4 mt-4">
                        {conceptObj.abilities?.map((a: any, i: number) => (
                          <div key={i} className="p-4 rounded-xl border border-blue-500/20 bg-blue-50/30 dark:bg-blue-900/10">
                            <div className="flex items-center gap-2 mb-3">
                              <InfoTooltip content="Ability Type: The specific cognitive action the student must perform."><Badge className="bg-blue-500 text-white hover:bg-blue-600">{formatValue(a.ability_type)}</Badge></InfoTooltip>
                              <InfoTooltip content="Complexity: Defines the cognitive load required to perform this ability, helping teachers pace lessons."><span className="text-sm font-medium bg-blue-500/10 px-2 py-0.5 rounded text-blue-800 dark:text-blue-200">Complexity: {formatValue(a.complexity)}</span></InfoTooltip>
                              {a.measurable && <InfoTooltip content="Measurable: Indicates if a teacher can easily test this ability."><span className="text-xs bg-emerald-500/10 text-emerald-700 px-2 py-0.5 rounded">Measurable</span></InfoTooltip>}
                            </div>
                            <p className="text-foreground/90">{a.statement}</p>
                          </div>
                        ))}
                      </TabsContent>

                      {/* 3. SKILL */}
                      <TabsContent value="skill" className="space-y-4">
                        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                          {conceptObj.skills?.map((s: any, i: number) => (
                            <div key={i} className="p-4 rounded-xl border border-teal-500/20 bg-teal-50/30 dark:bg-teal-900/10">
                              <div className="font-bold mb-1">{s.skill_name}</div>
                              <InfoTooltip content="Skill Type: Categorizes the skill (e.g., Analytical, Practical)."><Badge variant="outline" className="mb-2 border-teal-500/30 text-teal-700">{formatValue(s.skill_type)}</Badge></InfoTooltip>
                              <div className="flex gap-2 text-xs text-muted-foreground mt-2">
                                <InfoTooltip content="Development Level: Indicates whether this is an introductory, intermediate, or advanced skill."><span className="bg-black/5 dark:bg-white/5 px-2 py-1 rounded hover:bg-black/10 transition-colors">Development: {formatValue(s.development_level)}</span></InfoTooltip>
                                <InfoTooltip content="Transferability: Measures how easily this skill can be applied to other subjects or real-world scenarios."><span className="bg-black/5 dark:bg-white/5 px-2 py-1 rounded hover:bg-black/10 transition-colors">Transferability: {formatValue(s.transferability)}</span></InfoTooltip>
                              </div>
                            </div>
                          ))}
                        </div>
                      </TabsContent>

                      {/* 4. COMPETENCY */}
                      <TabsContent value="competency" className="space-y-4">
                        {conceptObj.competencies?.map((c: any, i: number) => (
                          <div key={i} className="p-4 rounded-xl border border-indigo-500/20 bg-indigo-50/30 dark:bg-indigo-900/10">
                            <div className="font-bold text-indigo-800 dark:text-indigo-300 mb-2">{c.competency_name}</div>
                            {c.evidence && <p className="text-sm text-foreground/80 italic">"{c.evidence}"</p>}
                            <div className="mt-2 w-full bg-black/10 rounded-full h-1.5">
                              <div className="bg-indigo-500 h-1.5 rounded-full" style={{ width: `${c.strength * 100}%` }}></div>
                            </div>
                          </div>
                        ))}
                      </TabsContent>

                      {/* 5. BLOOMS */}
                      <TabsContent value="blooms" className="space-y-4">
                        <div className="flex flex-wrap gap-3">
                          {conceptObj.blooms?.map((b: any, i: number) => (
                            <div key={i} className="px-4 py-2 rounded-xl border border-purple-500/20 bg-purple-50/30 dark:bg-purple-900/10 flex items-center gap-2">
                              <span className="font-bold text-purple-700 dark:text-purple-300">{b.level}</span>
                              <span className="text-xs text-muted-foreground">{Math.round(b.coverage_score * 100)}%</span>
                            </div>
                          ))}
                        </div>
                      </TabsContent>

                      {/* 6. DOK */}
                      <TabsContent value="dok" className="space-y-4">
                        {conceptObj.dok?.map((d: any, i: number) => (
                          <div key={i} className="p-4 rounded-xl border border-amber-500/20 bg-amber-50/30 dark:bg-amber-900/10 flex items-center gap-4">
                            <div className="w-10 h-10 rounded-full bg-amber-500 text-white flex items-center justify-center font-bold text-xl">{d.level}</div>
                            <div className="font-medium text-amber-900 dark:text-amber-200">{d.description}</div>
                          </div>
                        ))}
                      </TabsContent>

                      {/* 7. PREREQUISITES */}
                      <TabsContent value="prerequisite" className="space-y-4">
                        {conceptObj.prerequisites?.map((p: any, i: number) => (
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
                        {conceptObj.misconceptions?.map((m: any, i: number) => (
                          <div key={i} className="p-4 rounded-xl border border-red-500/20 bg-red-50/30 dark:bg-red-900/10">
                            <div className="font-bold text-red-800 dark:text-red-300 mb-2">⚠ {m.misconception}</div>
                            <p className="text-sm text-red-700/80 mb-3"><span className="font-semibold">Fix:</span> {m.correction_strategy}</p>
                            <div className="flex gap-2 mt-3">
                              <InfoTooltip content="Frequency: How often students typically make this mistake."><Badge variant="outline" className="border-red-500/30 text-red-700 hover:bg-red-500/10">Frequency: {formatValue(m.frequency)}</Badge></InfoTooltip>
                              <InfoTooltip content="Severity: How badly this misconception damages future learning if not corrected."><Badge variant="outline" className="border-red-500/30 text-red-700 hover:bg-red-500/10">Severity: {formatValue(m.severity)}</Badge></InfoTooltip>
                            </div>
                          </div>
                        ))}
                      </TabsContent>

                      {/* 9. REAL WORLD */}
                      <TabsContent value="realworld" className="space-y-4">
                        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                          {conceptObj.real_world_applications?.map((r: any, i: number) => (
                            <div key={i} className="p-4 rounded-xl border border-emerald-500/20 bg-emerald-50/30 dark:bg-emerald-900/10">
                              <Badge className="bg-emerald-500/20 text-emerald-800 border-none mb-2 hover:bg-emerald-500/30">{r.application_type}</Badge>
                              <p className="text-sm text-foreground/80">{r.example}</p>
                            </div>
                          ))}
                        </div>
                      </TabsContent>

                      {/* 10. PEDAGOGY */}
                      <TabsContent value="pedagogy" className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4 mt-4">
                        {conceptObj.pedagogy_recommendations?.map((p: any, i: number) => (
                          <div key={i} className="p-4 rounded-xl border border-black/5 dark:border-white/5 bg-white/50 dark:bg-black/50">
                            <div className="flex justify-between items-start mb-2">
                              <span className="font-bold text-lg">{p.pedagogy_type}</span>
                              <InfoTooltip content="Effectiveness: Rating of how well this teaching method works for this concept."><Badge variant="outline" className="hover:bg-black/5">{p.effectiveness} Effectiveness</Badge></InfoTooltip>
                            </div>
                            <p className="text-sm text-muted-foreground">{p.rationale}</p>
                          </div>
                        ))}
                      </TabsContent>

                      {/* 11. OBJECTIVES */}
                      <TabsContent value="objectives" className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4 mt-4">
                        {conceptObj.learning_objectives?.map((lo: any, i: number) => (
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
                        {conceptObj.learning_outcomes?.map((lo: any, i: number) => (
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
                        {conceptObj.assessment_blueprint?.map((ab: any, i: number) => (
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
                    </Tabs>
                  </CustomAccordionItem>
                ))}
              </div>

            </div>
          )}
        </div>

      </div>
      </div>
    </TooltipProvider>
  );
}
