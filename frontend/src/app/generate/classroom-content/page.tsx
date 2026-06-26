"use client";

import React, { useEffect, useState } from "react";
import { ArrowLeft, Sparkles, ExternalLink, Presentation, Loader2 } from "lucide-react";
import Link from "next/link";
import { CustomSelect } from "@/components/ui/custom-select";

export default function ClassroomContentGenerator() {
  const [chapters, setChapters] = useState<any[]>([]);
  const [loadingChapters, setLoadingChapters] = useState(true);
  
  const [selectedExtractionId, setSelectedExtractionId] = useState<string>("");
  const [semanticData, setSemanticData] = useState<any>(null);
  const [loadingData, setLoadingData] = useState(false);
  
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
    if (!semanticData) return null;
    
    const chapterObj = chapters.find(c => c.id.toString() === selectedExtractionId);
    const standard = chapterObj?.standard || "Standard";
    const subject = chapterObj?.subject_name || "Subject";
    const chapterName = chapterObj?.document_tittle || "Chapter";
    
    const itemsList = semanticData.concepts || semanticData.topics || semanticData.teaching_units || [];
    if (itemsList.length === 0) return null;

    let conceptsYaml = "";
    itemsList.forEach((conceptObj: any) => {
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

        conceptsYaml += `  - Concept: ${conceptName}
    Knowledge: ${knowledge}
    Ability: ${ability}
    Skill: ${skill}
    Competency: ${competency}
    BloomLevel: ${blooms}
    DOKLevel: ${dok}
    SuggestedPedagogy: ${pedagogy}
    RealTimeApplications: ${rwa}
    CommonMisconceptions: ${misconceptions}
    LearningObjectives: ${objectives}
    LearningOutcomes: ${outcomes}
    Prerequisites: ${prerequisites}

`;
    });

    return `You are an expert instructional designer, curriculum architect, competency-based education specialist, and classroom presentation generator aligned with NCERT, NEP 2020, NCF, NCTE, and NPST principles.
Objective
Generate a complete classroom presentation for an entire chapter using the intelligence of all concepts within that chapter.
The presentation must be chapter-driven through concept mastery rather than chapter summarization.
Instead of treating the chapter as a block of content, treat it as a structured collection of interconnected concepts that learners must progressively understand, apply, and master.
The presentation should help learners progressively develop:
Knowledge
Ability
Skill
Competency
Concept Mastery
Chapter Mastery
while achieving the specified Learning Objectives and Learning Outcomes.
Do not enforce any predefined instructional framework, lesson structure, pedagogy model, or slide sequence.
Use the supplied Chapter Concept Intelligence dynamically to determine the most effective presentation structure.

Inputs
Standard: ${standard}
Subject: ${subject}
Chapter: ${chapterName}
ChapterConcepts:
${conceptsYaml}

Chapter Intelligence Synthesis
Before generating slides, synthesize all concepts and determine:
Chapter Big Idea
Identify the central understanding that connects all concepts.
Concept Dependency Map
Determine:
prerequisite concepts
supporting concepts
dependent concepts
concept progression
Concept Clusters
Group related concepts into logical learning clusters.
Chapter Competencies
Aggregate all competencies and identify:
foundational competencies
intermediate competencies
mastery competencies
Chapter Learning Objectives
Generate consolidated chapter-level objectives from all concept objectives.
Chapter Learning Outcomes
Generate measurable chapter-level outcomes from all concept outcomes.
Bloom Progression
Determine the overall Bloom progression across the chapter.
DOK Progression
Determine the overall Depth of Knowledge progression across the chapter.

Presentation Generation Rules
Concept-Driven Chapter Design
The presentation must:
Cover all concepts
Show relationships between concepts
Build conceptual progression
Prevent fragmented learning
Avoid:
concept isolation
content dumping
textbook summarization
Every slide must contribute to at least one of:
Knowledge acquisition
Ability development
Skill development
Competency development
Concept integration
Chapter mastery

Dynamic Pedagogy Usage
Treat SuggestedPedagogy from each concept as guidance.
Use pedagogy dynamically to influence:
learning experiences
discussions
investigations
demonstrations
activities
assessments
If multiple concepts recommend different pedagogies, intelligently blend them where appropriate.
Never force a predefined instructional model.

Concept Progression Logic
Present concepts according to their learning dependencies rather than their textbook order whenever educationally beneficial.
Ensure learners move from:
prerequisite concepts
foundational concepts
connected concepts
advanced concepts
integrated understanding

Mandatory Coverage
Collectively ensure the presentation addresses:
Chapter Foundation
chapter overview
chapter significance
big idea
essential understanding
Concept Foundations
For every concept:
introduction
significance
key ideas
examples
non-examples
Knowledge Development
facts
concepts
principles
relationships
Ability Development
what learners can perform
Skill Development
observable skills
Competency Development
authentic demonstrations
Concept Integration
Show:
concept relationships
cause-effect links
systems thinking
interdisciplinary links
Real-Time Applications
Across concepts include:
daily life
society
technology
industry
current events
Misconception Resolution
Address misconceptions for every major concept.
Assessment
Assess:
individual concepts
concept connections
chapter mastery
competencies
learning outcomes

Slide Planning Logic
Before generating slides, internally determine:
What learners must know across the chapter.
What learners must understand across the chapter.
What learners must do.
What learners must demonstrate.
Which concepts require the greatest emphasis.
Which misconceptions require explicit correction.
Which concept relationships are critical.
Which real-world applications strengthen understanding.
How Bloom progression should occur.
How DOK progression should occur.
How chapter mastery can be validated.
Use these decisions to generate the most effective slide sequence.
The number, order, and purpose of slides should be determined dynamically based on:
number of concepts
concept complexity
competency complexity
Bloom levels
DOK levels
Recommended range:
5–10 slides per concept cluster
20–60 slides per chapter

Output Requirements
For every slide generate:
Slide Number
Slide Title
Concept Coverage
List concepts addressed on the slide.
Concept Intelligence Mapping
Knowledge:
Ability:
Skill:
Competency:
BloomLevel:
DOKLevel:

Purpose
Explain why this slide exists.
Content
Detailed, comprehensive, and perfectly explained classroom-ready content. Do not use short or superficial bullet points. You MUST provide deep, clear, and perfectly articulated explanations that thoroughly teach the concept using the exact Ground Truth text provided.
Speaker Notes
Teacher facilitation guidance.
Student Interaction
Questions, discussions, investigations, reflections, activities, or collaborative tasks.
Assessment Opportunity
Describe how learning can be observed and validated.
Image Prompt
Generate a highly detailed educational image prompt that:
visually represents the concepts being taught
supports conceptual understanding
matches learner age
contains no readable text
uses realistic classroom or contextual situations

Quality Requirements
The presentation must:
be chapter-focused through concept mastery
cover every major concept
show concept interconnections
be classroom-ready
be age-appropriate
be competency-oriented
align with Bloom and DOK progressions
use pedagogy dynamically
integrate real-world applications
explicitly address misconceptions
encourage critical thinking
promote active participation
support measurable learning outcomes
enable observable competency demonstrations
culminate in chapter-level mastery rather than isolated concept understanding
Generate the complete presentation in a professional classroom presentation format.

Ground Truth Chapter Content (No Hallucinations)
Below is the exact, raw textbook content for this chapter. 
CRITICAL INSTRUCTION: You MUST use the exact definitions, examples, and terminology found in this text when generating the slide content. Do not invent outside examples unless explicitly requested by the pedagogy. 

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
      // We pass the prompt but don't specify numCards because we want the AI to decide based on the chapter size.
      // Gamma API currently requires numCards in our endpoint, let's just send the prompt and let the backend handle it.
      // Wait, our backend endpoint `/api/gamma/generate` has hardcoded numCards = 10.
      // I will update the backend endpoint to accept numCards optionally. Let's just pass numCards = 30 for a full chapter.
      const res = await fetch("/api/gamma/generate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ prompt, numCards: 30 }),
      });

      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.error || "Failed to start generation");
      }

      const { generationId } = await res.json();
      setGenerationStatus("Designing Chapter Presentation (this will take longer)...");

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

  return (
    <div className="flex h-[100dvh] flex-col bg-background relative overflow-hidden text-foreground">
      {/* iOS Liquid Glass Background */}
      <div className="absolute top-[-15%] left-[-10%] w-[50%] h-[50%] rounded-[100%] bg-emerald-500/30 dark:bg-emerald-600/20 blur-[140px] mix-blend-normal opacity-80 pointer-events-none animate-pulse" />
      <div className="absolute bottom-[-10%] right-[-10%] w-[60%] h-[60%] rounded-[100%] bg-teal-500/30 dark:bg-teal-600/20 blur-[140px] mix-blend-normal opacity-80 pointer-events-none animate-pulse" style={{ animationDelay: '2s' }} />
      
      {/* Header */}
      <header className="fixed top-4 left-1/2 -translate-x-1/2 z-50 w-[96%] max-w-[1600px] rounded-full border-[0.5px] border-black/10 dark:border-white/20 bg-white/40 dark:bg-black/40 backdrop-blur-[40px] saturate-200 shadow-[0_8px_32px_0_rgba(0,0,0,0.1)] px-5 py-2.5 transition-all">
        <div className="flex h-10 items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="flex h-9 w-9 items-center justify-center rounded-full bg-emerald-500/10 shadow-inner border-[0.5px] border-emerald-500/20">
              <Sparkles className="h-5 w-5 text-emerald-600 dark:text-emerald-400" />
            </div>
            <span className="text-[17px] font-semibold tracking-tight text-foreground/90 uppercase">
              Classroom Content Generator
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
                <span className="w-6 h-6 rounded-full bg-emerald-500 text-white flex items-center justify-center text-xs">1</span> 
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

            {loadingData && (
              <div className="text-sm text-muted-foreground animate-pulse px-2">Loading chapter concepts...</div>
            )}

            <div className={`relative z-10 bg-white/50 dark:bg-black/40 backdrop-blur-3xl rounded-[2rem] border border-black/10 dark:border-white/10 p-6 shadow-xl transition-opacity duration-300 ${!semanticData ? 'opacity-50 pointer-events-none' : ''}`}>
              <button 
                onClick={generatePresentation}
                disabled={isGenerating || !!gammaUrl}
                className={`w-full py-4 rounded-full font-bold transition-all flex items-center justify-center gap-2 shadow-[0_0_20px_rgba(16,185,129,0.3)]
                  ${isGenerating 
                    ? "bg-emerald-600/50 text-white/80 cursor-not-allowed" 
                    : gammaUrl 
                      ? "bg-emerald-600 text-white shadow-[0_0_20px_rgba(16,185,129,0.3)]"
                      : "bg-emerald-600 hover:bg-emerald-700 text-white active:scale-95"
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
                    <Presentation className="w-5 h-5" /> Generate Chapter PPT
                  </>
                )}
              </button>
              
              {!isGenerating && !gammaUrl && semanticData && (
                <p className="text-xs text-muted-foreground text-center mt-4">
                  Will generate a ~30 slide presentation covering all {semanticData.concepts?.length || semanticData.topics?.length || 0} concepts.
                </p>
              )}
            </div>
          </div>

          {/* Presentation Output Area (Full Side / Right Side) */}
          <div className="flex-1 h-full bg-white/50 dark:bg-black/40 backdrop-blur-3xl rounded-[2rem] border border-black/10 dark:border-white/10 shadow-xl flex flex-col overflow-hidden min-h-0 relative z-20">
            <div className="p-4 border-b border-black/10 dark:border-white/10 bg-white/30 dark:bg-black/20 flex justify-between items-center shrink-0">
              <h3 className="font-bold text-foreground">Generated Classroom PPT</h3>
              <div className="flex gap-2">
                {gammaUrl && (
                  <a 
                    href={gammaUrl} 
                    target="_blank" 
                    rel="noreferrer"
                    className="flex items-center gap-2 px-4 py-2 rounded-lg bg-emerald-500/10 hover:bg-emerald-500/20 text-emerald-600 dark:text-emerald-400 text-sm font-semibold transition-colors"
                  >
                    <ExternalLink className="w-4 h-4" /> Open in Gamma
                  </a>
                )}
                {exportUrl && (
                  <a 
                    href={exportUrl} 
                    target="_blank" 
                    rel="noreferrer"
                    className="flex items-center gap-2 px-4 py-2 rounded-lg bg-teal-500/10 hover:bg-teal-500/20 text-teal-600 dark:text-teal-400 text-sm font-semibold transition-colors"
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
                    className="flex items-center gap-2 px-6 py-3 rounded-full bg-emerald-600 hover:bg-emerald-700 text-white font-bold transition-colors shadow-lg"
                  >
                    <ExternalLink className="w-5 h-5" /> Open in Gamma
                  </a>
                </div>
              ) : isGenerating ? (
                <div className="absolute inset-0 flex flex-col items-center justify-center">
                  <div className="w-24 h-24 mb-8 relative">
                    <div className="absolute inset-0 rounded-full border-4 border-emerald-500/20"></div>
                    <div className="absolute inset-0 rounded-full border-4 border-emerald-500 border-t-transparent animate-spin"></div>
                    <Presentation className="absolute inset-0 m-auto w-8 h-8 text-emerald-500 animate-pulse" />
                  </div>
                  <h3 className="text-2xl font-bold text-foreground mb-2">Crafting your Chapter Presentation</h3>
                  <p className="text-muted-foreground">{generationStatus}</p>
                </div>
              ) : (
                <div className="absolute inset-0 flex flex-col items-center justify-center text-muted-foreground opacity-60">
                  <Presentation className="w-16 h-16 mb-4 opacity-50" />
                  <p>Select a chapter to generate the full presentation.</p>
                </div>
              )}
            </div>
          </div>

        </div>
      </main>
    </div>
  );
}
