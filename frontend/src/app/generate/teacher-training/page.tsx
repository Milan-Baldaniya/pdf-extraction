"use client";

import React, { useEffect, useState } from "react";
import { ArrowLeft, Sparkles, ExternalLink, Presentation, Loader2 } from "lucide-react";
import Link from "next/link";
import { CustomSelect } from "@/components/ui/custom-select";

export default function TeacherTrainingPromptGenerator() {
  const [chapters, setChapters] = useState<any[]>([]);
  const [loadingChapters, setLoadingChapters] = useState(true);
  
  const [selectedExtractionId, setSelectedExtractionId] = useState<string>("");
  const [semanticData, setSemanticData] = useState<any>(null);
  const [loadingData, setLoadingData] = useState(false);
  
  const [selectedConceptIndex, setSelectedConceptIndex] = useState<string>("");
  
  // Gamma Generation States
  const [isGenerating, setIsGenerating] = useState(false);
  const [generationStatus, setGenerationStatus] = useState<string>("");
  const [gammaUrl, setGammaUrl] = useState<string | null>(null);
  const [exportUrl, setExportUrl] = useState<string | null>(null);

  useEffect(() => {
    fetchChapters();
  }, []);

  useEffect(() => {
    if (selectedExtractionId) {
      fetchSemanticData(selectedExtractionId);
    } else {
      setSemanticData(null);
      setSelectedConceptIndex("");
      resetGeneration();
    }
  }, [selectedExtractionId]);

  const resetGeneration = () => {
    setIsGenerating(false);
    setGenerationStatus("");
    setGammaUrl(null);
    setExportUrl(null);
  }

  const fetchChapters = async () => {
    try {
      const res = await fetch("http://localhost:8000/api/semantic-intelligence");
      if (res.ok) {
        const data = await res.json();
        // Only show chapters that are processed
        setChapters(data.filter((c: any) => c.is_processed));
      }
    } catch (err) {
      console.error(err);
    } finally {
      setLoadingChapters(false);
    }
  };

  const fetchSemanticData = async (id: string) => {
    setLoadingData(true);
    setSelectedConceptIndex("");
    resetGeneration();
    try {
      const res = await fetch(`http://localhost:8000/api/semantic-intelligence/${id}/result`);
      if (res.ok) {
        const json = await res.json();
        const intelligence = json?.full_intelligence_json?.intelligence || 
                             json?.full_intelegance_json?.intelligence || 
                             json?.full_intelligence_json || 
                             json?.full_intelegance_json;
        setSemanticData(intelligence);
      }
    } catch (err) {
      console.error(err);
    } finally {
      setLoadingData(false);
    }
  };

  const constructPrompt = () => {
    if (!semanticData || selectedConceptIndex === "") return null;
    
    const chapterObj = chapters.find(c => c.id.toString() === selectedExtractionId);
    const standard = chapterObj?.standard || "Standard";
    const subject = chapterObj?.subject_name || "Subject";
    const chapterName = chapterObj?.document_tittle || "Chapter";
    
    const itemsList = semanticData.concepts || semanticData.topics || semanticData.teaching_units;
    if (!itemsList) return null;
    
    const conceptObj = itemsList[parseInt(selectedConceptIndex)];
    const conceptName = conceptObj.concept?.concept_name || conceptObj.topic_title || conceptObj.topic_name || "Concept";
    
    const extractStr = (arr: any[], key: string) => arr && arr.length > 0 ? arr.map(a => a[key]).join("; ") : "Not specified";
    
    const knowledge = extractStr(conceptObj.knowledge_items, "knowledge");
    const ability = extractStr(conceptObj.abilities, "ability");
    const skill = extractStr(conceptObj.skills, "skill");
    const competency = extractStr(conceptObj.competencies, "competency");
    const blooms = extractStr(conceptObj.blooms, "level");
    const dok = extractStr(conceptObj.dok, "level");
    const pedagogy = extractStr(conceptObj.pedagogy_recommendations, "strategy");
    const rwa = extractStr(conceptObj.real_world_applications, "example");
    const misconceptions = extractStr(conceptObj.misconceptions, "misconception");
    const objectives = extractStr(conceptObj.learning_objectives, "objective");
    const outcomes = extractStr(conceptObj.learning_outcomes, "outcome");
    const prerequisites = extractStr(conceptObj.prerequisites, "concept_name");

    return `Teacher Training PPT — Master Prompt Template (Single-Concept, Suggested-Pedagogy Oriented + Differentiated Instruction)

Concept Data Block (fill once)
Concept: ${conceptName}
Knowledge: ${knowledge}
Ability: ${ability}
Skill: ${skill}
Competency: ${competency}
Bloom's Level: ${blooms}
Depth of Knowledge (DOK): ${dok}
Suggested Pedagogy: ${pedagogy}
Real-Time Application: ${rwa}
Common Misconceptions: ${misconceptions}
Learning Objectives: ${objectives}
Learning Outcomes: ${outcomes}
Prerequisites: ${prerequisites}

Slide-by-Slide Prompt
Slide 1: Title Slide
 Title: Teacher Training through ${pedagogy} Pedagogy-Oriented Learning Design for ${conceptName} (${standard}, ${subject}, ${chapterName})
 Sub-title: Aligned with NCERT, NEP 2020, NCTE, NPST | Concept-Specific Pedagogy & Differentiated Instruction
 Image Prompt: A diverse group of students engaged in an activity matching ${pedagogy}. Warm natural lighting, modern classroom. Minimalist, no text.
Slide 2: Objectives of the Session
 Content: Understand ${conceptName} and why ${pedagogy} fits it; apply the pedagogy in practice; differentiate by readiness & cognitive demand
 Image Prompt: 3D wooden clipboard with three icons — puzzle piece (pedagogy-fit), gears (application), checklist (differentiation). Pastel background, no text.
Slide 3: Why Pedagogy Must Match This Concept
 Content: One-size-fits-all teaching vs. ${pedagogy} matched specifically to ${conceptName}'s nature and cognitive demand
 Image Prompt: Split-screen: a classroom with identical worksheets vs. a classroom set up for ${pedagogy}. No labels, muted colors.
Slide 4: NEP 2020 & NPST Emphasis
 Content: Active, Inquiry, Competency-aligned pedagogy choice — as reflected in the choice of ${pedagogy} for ${conceptName}
 Image Prompt: Minimalist desk, open NEP 2020 document, magnifying glass over "Active Learning," "Competency." Soft blue background.
Slide 5: Concept Snapshot — ${conceptName}
 Content: Definition/scope of ${conceptName} within ${chapterName}; its ${blooms} and ${dok} placement; why ${pedagogy} was selected
 Image Prompt: A single concept node with branching labels for Bloom's Level, DOK, and pedagogy icon. Clean, no text.
Slide 6: Prerequisites Check — ${conceptName}
 Content: ${prerequisites} — diagnostic entry point before beginning the pedagogy-based activity
 Image Prompt: Teacher with a checklist beside a foundation/building-blocks metaphor. No text.
Slide 7: ${conceptName} — ${pedagogy} in Practice
 Content: Step-by-step on how to run ${pedagogy} for this concept; Bloom's Level: ${blooms}, DOK: ${dok}; targets ${knowledge}/${ability}/${skill}/${competency}
 Image Prompt: Visual matched specifically to ${pedagogy} Warm, no text.
Slide 8: ${conceptName} — Application & Misconceptions
 Content: Real-Time Application: ${rwa}; Common Misconceptions: ${misconceptions} and how ${pedagogy} surfaces/corrects them
 Image Prompt: A magnifying glass over a tangled-to-untangled thread (misconception correction), paired with a real-world scene matching ${rwa}. No text.
Slide 9: Differentiating Within ${pedagogy}


 Content: How ${pedagogy} for ${conceptName} can be tiered by readiness (Content), grouped by role (Process), and assessed at different levels (Product) — using Knowledge/Ability/Skill/Competency layers
Image Prompt: One pedagogy icon shown with three branching tiers of varying complexity. Abstract, no text.
Slide 10: Role of the Teacher in ${pedagogy}


Content: The facilitator role for this specific pedagogy: ${pedagogy}
 Image Prompt: Teacher shown in a vignette taking on the relevant supporting role. Natural light, no text.
Slide 11: Differentiated Assessment Design — ${conceptName}
 
Content: Assessment format matched to ${pedagogy} and ${competency} layer; tiered by ${dok}
 Image Prompt: A rubric checklist with multiple tiered rating columns, pedagogy icon beside each row. Pastel background, no text.
Slide 12: Sample Lesson Plan — ${conceptName}


 Content: Full lesson plan for ${conceptName}, built from ${objectives} and ${outcomes}, structured around ${pedagogy}
 Image Prompt: A lesson-plan page with pedagogy-specific icons along the margin. Monochrome with one accent color.
Slide 13: Digital Tools for ${pedagogy}


 Content: Canva, Padlet, Google Docs, Jamboard — which tool(s) best support ${pedagogy} specifically, and how
 Image Prompt: Students collaborating on laptops/tablets with generic UI, small pedagogy-icon label. Tech-abstract style.
Slide 14: Overcoming Challenges


Content: Time, materials/prep needed for ${pedagogy}, mixed-readiness classroom considerations for ${conceptName}
 Image Prompt: Teacher's hands over a complex timetable, clock in background. Muted tones.
Slide 15: Teacher Reflection Framework


Content: What worked, what didn't — specific to using ${pedagogy} for ${conceptName}
 Image Prompt: Teacher at desk with checklist, thought bubbles. No text.
Slide 16: Action Plan


Content: Steps to implement ${pedagogy} for ${conceptName} in the classroom, reflect, and refine before next use
 Image Prompt: Wooden staircase with abstract steps, each bearing a faint pedagogy icon. No text.
Slide 17: Activity — Design a Lesson for ${conceptName}


Content: Teachers draft a lesson for ${conceptName} using ${pedagogy}, differentiated by readiness
 Image Prompt: Blank lesson plan template with colorful pens, sticky notes, a small pedagogy icon in the corner. Inviting, empty.
Slide 18: Feedback, Q&A, Thank You


Content: Collect participant responses on how ${pedagogy} worked for ${conceptName}
 Image Prompt: Bright empty classroom, "Thank You" on chalkboard, sunlight streaming in.
 
Ground Truth Chapter Content (No Hallucinations)
Below is the exact, raw textbook content for this chapter. 
CRITICAL INSTRUCTION: You MUST use the exact definitions, examples, and terminology found in this text when generating the slide content. Do not invent outside examples unless explicitly requested by the pedagogy. 
CRITICAL INSTRUCTION 2: Ensure all generated slide content is highly detailed, comprehensive, and perfectly explained. Do not use short or superficial bullet points. Provide deep, clear, and perfectly articulated explanations suitable for a professional presentation.

${semanticData.md_content || "Content not available."}`;
  };

  const generatePresentation = async () => {
    const prompt = constructPrompt();
    if (!prompt) return;

    resetGeneration();
    setIsGenerating(true);
    setGenerationStatus("Initializing Gamma Agent...");

    try {
      // 1. Start generation
      const res = await fetch("/api/gamma/generate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ prompt }),
      });

      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.error || "Failed to start generation");
      }

      const { generationId } = await res.json();
      setGenerationStatus("Designing Presentation (this may take a minute)...");

      // 2. Poll for status
      const pollInterval = setInterval(async () => {
        try {
          const statusRes = await fetch(`/api/gamma/status/${generationId}`);
          if (statusRes.ok) {
            const statusData = await statusRes.json();
            
            if (statusData.status === "completed") {
              clearInterval(pollInterval);
              setGammaUrl(statusData.gammaUrl);
              if (statusData.exportUrl) {
                setExportUrl(statusData.exportUrl);
              }
              setGenerationStatus("Completed");
              setIsGenerating(false);
            } else if (statusData.status === "failed") {
              clearInterval(pollInterval);
              setGenerationStatus("Generation failed.");
              setIsGenerating(false);
            }
          }
        } catch (pollErr) {
          console.error("Polling error", pollErr);
        }
      }, 5000);

    } catch (err: any) {
      console.error(err);
      setGenerationStatus(`Error: ${err.message}`);
      setIsGenerating(false);
    }
  };

  const itemsList = semanticData?.concepts || semanticData?.topics || semanticData?.teaching_units || [];

  return (
    <div className="flex h-[100dvh] flex-col bg-background relative overflow-hidden text-foreground">
      {/* iOS Liquid Glass Background */}
      <div className="absolute top-[-15%] left-[-10%] w-[50%] h-[50%] rounded-[100%] bg-blue-500/30 dark:bg-blue-600/20 blur-[140px] mix-blend-normal opacity-80 pointer-events-none animate-pulse" />
      <div className="absolute bottom-[-10%] right-[-10%] w-[60%] h-[60%] rounded-[100%] bg-purple-500/30 dark:bg-purple-600/20 blur-[140px] mix-blend-normal opacity-80 pointer-events-none animate-pulse" style={{ animationDelay: '2s' }} />
      
      {/* Header */}
      <header className="fixed top-4 left-1/2 -translate-x-1/2 z-50 w-[96%] max-w-[1600px] rounded-full border-[0.5px] border-black/10 dark:border-white/20 bg-white/40 dark:bg-black/40 backdrop-blur-[40px] saturate-200 shadow-[0_8px_32px_0_rgba(0,0,0,0.1)] px-5 py-2.5 transition-all">
        <div className="flex h-10 items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="flex h-9 w-9 items-center justify-center rounded-full bg-indigo-500/10 shadow-inner border-[0.5px] border-indigo-500/20">
              <Sparkles className="h-5 w-5 text-indigo-600 dark:text-indigo-400" />
            </div>
            <span className="text-[17px] font-semibold tracking-tight text-foreground/90 uppercase">
              Teacher Training PPT Generator
            </span>
          </div>
          <div className="flex items-center gap-3">
            <Link href="/" className="flex items-center gap-1.5 rounded-full px-4 py-1.5 text-sm font-medium text-foreground/70 bg-black/5 dark:bg-white/5 hover:bg-black/10 dark:hover:bg-white/10 hover:text-foreground transition-all border-[0.5px] border-transparent hover:border-black/10 dark:hover:border-white/10">
              <ArrowLeft className="h-3.5 w-3.5" /> Back
            </Link>
          </div>
        </div>
      </header>

      {/* Main Content */}
      <main className="relative z-10 w-full max-w-[1800px] mx-auto px-6 pt-24 pb-6 flex-1 flex flex-col min-h-0 h-full">
        <div className="flex flex-col md:flex-row gap-6 flex-1 h-full min-h-0">
          
          {/* Controls Sidebar (Left Side) */}
          <div className="w-full md:w-80 shrink-0 flex flex-col gap-6 overflow-y-auto custom-scrollbar pr-2 pb-2">
            <div className="relative z-30 bg-white/50 dark:bg-black/40 backdrop-blur-3xl rounded-[2rem] border border-black/10 dark:border-white/10 p-6 shadow-xl">
              <h2 className="text-lg font-bold mb-4 flex items-center gap-2">
                <span className="w-6 h-6 rounded-full bg-indigo-500 text-white flex items-center justify-center text-xs">1</span> 
                Select Chapter
              </h2>
              {loadingChapters ? (
                <div className="text-sm text-muted-foreground animate-pulse">Loading semantic chapters...</div>
              ) : (
                <div className={isGenerating ? "pointer-events-none opacity-50" : ""}>
                  <CustomSelect 
                    value={selectedExtractionId}
                    onChange={(val) => setSelectedExtractionId(val)}
                    placeholder="-- Choose Chapter --"
                    options={chapters.map(c => ({
                      value: c.id.toString(),
                      label: `Std ${c.standard} - ${c.subject_name}: ${c.document_tittle}`
                    }))}
                  />
                </div>
              )}
            </div>

            <div className={`relative z-20 bg-white/50 dark:bg-black/40 backdrop-blur-3xl rounded-[2rem] border border-black/10 dark:border-white/10 p-6 shadow-xl transition-opacity duration-300 ${!semanticData ? 'opacity-50 pointer-events-none' : ''}`}>
              <h2 className="text-lg font-bold mb-4 flex items-center gap-2">
                <span className="w-6 h-6 rounded-full bg-indigo-500 text-white flex items-center justify-center text-xs">2</span> 
                Select Concept
              </h2>
              {loadingData ? (
                <div className="text-sm text-muted-foreground animate-pulse">Loading concepts...</div>
              ) : (
                <div className={isGenerating ? "pointer-events-none opacity-50" : ""}>
                  <CustomSelect 
                    value={selectedConceptIndex}
                    onChange={(val) => {
                      setSelectedConceptIndex(val);
                      resetGeneration();
                    }}
                    placeholder="-- Choose Concept --"
                    options={itemsList.map((c: any, i: number) => ({
                      value: i.toString(),
                      label: c.concept?.concept_name || c.topic_title || c.topic_name || `Concept ${i+1}`
                    }))}
                  />
                </div>
              )}
            </div>

            <div className={`relative z-10 bg-white/50 dark:bg-black/40 backdrop-blur-3xl rounded-[2rem] border border-black/10 dark:border-white/10 p-6 shadow-xl transition-opacity duration-300 ${!selectedConceptIndex ? 'opacity-50 pointer-events-none' : ''}`}>
              <button 
                onClick={generatePresentation}
                disabled={isGenerating || !!gammaUrl}
                className={`w-full py-4 rounded-full font-bold transition-all flex items-center justify-center gap-2 shadow-[0_0_20px_rgba(79,70,229,0.3)]
                  ${isGenerating 
                    ? "bg-indigo-600/50 text-white/80 cursor-not-allowed" 
                    : gammaUrl 
                      ? "bg-emerald-600 text-white shadow-[0_0_20px_rgba(16,185,129,0.3)]"
                      : "bg-indigo-600 hover:bg-indigo-700 text-white active:scale-95"
                  }
                `}
              >
                {isGenerating ? (
                  <>
                    <Loader2 className="w-5 h-5 animate-spin" /> {generationStatus}
                  </>
                ) : gammaUrl ? (
                  <>
                    <Sparkles className="w-5 h-5" /> PPT Generated
                  </>
                ) : (
                  <>
                    <Presentation className="w-5 h-5" /> Generate PPT
                  </>
                )}
              </button>
            </div>
          </div>

          {/* Presentation Output Area (Full Side / Right Side) */}
          <div className="flex-1 h-full bg-white/50 dark:bg-black/40 backdrop-blur-3xl rounded-[2rem] border border-black/10 dark:border-white/10 shadow-xl flex flex-col overflow-hidden min-h-0 relative">
            <div className="p-4 border-b border-black/10 dark:border-white/10 bg-white/30 dark:bg-black/20 flex justify-between items-center shrink-0">
              <h3 className="font-bold text-foreground">Generated PPT</h3>
              <div className="flex gap-2">
                {gammaUrl && (
                  <a 
                    href={gammaUrl} 
                    target="_blank" 
                    rel="noreferrer"
                    className="flex items-center gap-2 px-4 py-2 rounded-lg bg-indigo-500/10 hover:bg-indigo-500/20 text-indigo-600 dark:text-indigo-400 text-sm font-semibold transition-colors"
                  >
                    <ExternalLink className="w-4 h-4" /> Open in Gamma
                  </a>
                )}
                {exportUrl && (
                  <a 
                    href={exportUrl} 
                    target="_blank" 
                    rel="noreferrer"
                    className="flex items-center gap-2 px-4 py-2 rounded-lg bg-emerald-500/10 hover:bg-emerald-500/20 text-emerald-600 dark:text-emerald-400 text-sm font-semibold transition-colors"
                  >
                    Download PDF
                  </a>
                )}
              </div>
            </div>
            
            <div className="flex-1 overflow-hidden relative bg-black/5 dark:bg-white/5">
              {exportUrl ? (
                <iframe 
                  src={`/api/gamma/pdf?url=${encodeURIComponent(exportUrl)}#view=FitH`} 
                  className="w-full h-full border-none"
                  allowFullScreen
                />
              ) : gammaUrl ? (
                <div className="absolute inset-0 flex flex-col items-center justify-center bg-white/50 dark:bg-black/40">
                  <Presentation className="w-16 h-16 mb-4 text-emerald-500 opacity-80" />
                  <h3 className="text-xl font-bold text-foreground mb-2">Presentation Ready!</h3>
                  <p className="text-muted-foreground mb-6">Gamma.app does not allow embedding their web viewer directly.</p>
                  <a 
                    href={gammaUrl} 
                    target="_blank" 
                    rel="noreferrer"
                    className="flex items-center gap-2 px-6 py-3 rounded-full bg-indigo-600 hover:bg-indigo-700 text-white font-bold transition-colors shadow-lg"
                  >
                    <ExternalLink className="w-5 h-5" /> Open in Gamma
                  </a>
                </div>
              ) : isGenerating ? (
                <div className="absolute inset-0 flex flex-col items-center justify-center">
                  <div className="w-24 h-24 mb-8 relative">
                    <div className="absolute inset-0 rounded-full border-4 border-indigo-500/20"></div>
                    <div className="absolute inset-0 rounded-full border-4 border-indigo-500 border-t-transparent animate-spin"></div>
                    <Presentation className="absolute inset-0 m-auto w-8 h-8 text-indigo-500 animate-pulse" />
                  </div>
                  <h3 className="text-2xl font-bold text-foreground mb-2">Crafting your Presentation</h3>
                  <p className="text-muted-foreground">{generationStatus}</p>
                </div>
              ) : (
                <div className="absolute inset-0 flex flex-col items-center justify-center text-muted-foreground opacity-60">
                  <Presentation className="w-16 h-16 mb-4 opacity-50" />
                  <p>Select a chapter and concept, then generate.</p>
                </div>
              )}
            </div>
          </div>

        </div>
      </main>
    </div>
  );
}
