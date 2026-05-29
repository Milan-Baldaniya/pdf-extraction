"use client";

import { useCallback, useMemo, useRef, useState } from "react";
import toast from "react-hot-toast";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { ExtractionResponse } from "@/lib/api";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";
import {
  BarChart3,
  BookOpen,
  Check,
  Code2,
  Copy,
  Cpu,
  Download,
  FileText,
  ImageIcon,
  LayoutPanelTop,
  BrainCircuit,
  Loader2,
  Sparkles,
  GraduationCap,
  Plus,
} from "lucide-react";

import { generateSemanticIntelligence, generateTeachingIntelligence } from "@/lib/api";

interface ExtractionViewerProps {
  data: ExtractionResponse;
  onReset: () => void;
}

interface LayoutBlock {
  id?: string;
  type?: string;
  role?: string;
  educational_role?: string;
  source_type?: string;
  text?: string;
  img_path?: string;
  caption?: string;
  footnote?: string;
  table_html?: string;
  inline_items?: Array<{ type: string; content: string }>;
  bbox?: [number, number, number, number];
  page_idx?: number;
  reading_order?: number;
  hierarchy_level?: number;
}

interface LayoutPage {
  pageIdx: number;
  width: number;
  height: number;
  blocks: LayoutBlock[];
}

interface OutlineItem {
  id?: string;
  role?: string;
  title?: string;
  page_idx?: number;
  level?: number;
}

interface EducationalAssets {
  figures: Array<Record<string, unknown>>;
  tables: Array<Record<string, unknown>>;
  formulas: Array<Record<string, unknown>>;
}

interface ExtractionPass {
  method?: string;
  quality_score?: number;
  markdown_characters?: number;
  images?: number;
  tables?: number;
  formulas?: number;
  blocks?: number;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function asArray(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function asString(value: unknown, fallback = ""): string {
  return typeof value === "string" ? value : fallback;
}

function metadataValue(
  metadata: Record<string, unknown>,
  key: string,
  fallback: string | number = "-"
) {
  const value = metadata[key];
  return value === undefined || value === null || value === "" ? fallback : value;
}

function toLayoutBlocks(value: unknown): LayoutBlock[] {
  const rawBlocks = isRecord(value) && Array.isArray(value.blocks)
    ? value.blocks
    : Array.isArray(value)
      ? value
      : [];

  return rawBlocks
    .filter(isRecord)
    .map((item) => {
      const bbox = Array.isArray(item.bbox) && item.bbox.length === 4
        ? item.bbox.map(Number)
        : undefined;

      return {
        id: asString(item.id, undefined as unknown as string),
        type: asString(item.type, undefined as unknown as string),
        role: asString(item.role, undefined as unknown as string),
        educational_role: asString(item.educational_role, undefined as unknown as string),
        source_type: asString(item.source_type, undefined as unknown as string),
        text: asString(item.text, undefined as unknown as string),
        img_path: asString(item.img_path, undefined as unknown as string),
        caption: asString(item.caption, undefined as unknown as string),
        footnote: asString(item.footnote, undefined as unknown as string),
        table_html: asString(item.table_html, undefined as unknown as string),
        inline_items: asArray(item.inline_items)
          .filter(isRecord)
          .map((inline) => ({
            type: asString(inline.type, "text"),
            content: asString(inline.content),
          }))
          .filter((inline) => inline.content),
        bbox: bbox?.every(Number.isFinite)
          ? (bbox as [number, number, number, number])
          : undefined,
        page_idx: typeof item.page_idx === "number" ? item.page_idx : undefined,
        reading_order: typeof item.reading_order === "number" ? item.reading_order : undefined,
        hierarchy_level: typeof item.hierarchy_level === "number" ? item.hierarchy_level : undefined,
      };
    })
    .filter((block) => block.bbox && typeof block.page_idx === "number");
}

function buildPages(blocks: LayoutBlock[], value: unknown): LayoutPage[] {
  if (isRecord(value) && Array.isArray(value.pages)) {
    const pages = value.pages.filter(isRecord).map((page) => ({
      pageIdx: typeof page.page_idx === "number" ? page.page_idx : 0,
      width: typeof page.width === "number" ? page.width : 1000,
      height: typeof page.height === "number" ? page.height : 1200,
      blocks: toLayoutBlocks({ blocks: page.blocks }),
    }));
    if (pages.length) {
      return pages;
    }
  }

  const pageMap = new Map<number, LayoutBlock[]>();
  for (const block of blocks) {
    const pageIdx = block.page_idx ?? 0;
    pageMap.set(pageIdx, [...(pageMap.get(pageIdx) ?? []), block]);
  }

  return [...pageMap.entries()]
    .sort(([a], [b]) => a - b)
    .map(([pageIdx, pageBlocks]) => {
      const width = Math.max(...pageBlocks.map((block) => block.bbox?.[2] ?? 0), 1000);
      const height = Math.max(...pageBlocks.map((block) => block.bbox?.[3] ?? 0), 1200);
      return {
        pageIdx,
        width,
        height,
        blocks: [...pageBlocks].sort((a, b) => {
          const aBox = a.bbox ?? [0, 0, 0, 0];
          const bBox = b.bbox ?? [0, 0, 0, 0];
          return (a.reading_order ?? 0) - (b.reading_order ?? 0) ||
            aBox[1] - bBox[1] ||
            aBox[0] - bBox[0];
        }),
      };
    });
}

function getOutline(value: unknown): OutlineItem[] {
  if (!isRecord(value)) {
    return [];
  }
  return asArray(value.educational_outline)
    .filter(isRecord)
    .map((item) => ({
      id: asString(item.id),
      role: asString(item.role),
      title: asString(item.title),
      page_idx: typeof item.page_idx === "number" ? item.page_idx : undefined,
      level: typeof item.level === "number" ? item.level : undefined,
    }))
    .filter((item) => item.title);
}

function getAssets(value: unknown): EducationalAssets {
  if (!isRecord(value) || !isRecord(value.educational_assets)) {
    return { figures: [], tables: [], formulas: [] };
  }
  return {
    figures: asArray(value.educational_assets.figures).filter(isRecord),
    tables: asArray(value.educational_assets.tables).filter(isRecord),
    formulas: asArray(value.educational_assets.formulas).filter(isRecord),
  };
}

function getSections(value: unknown): Array<Record<string, unknown>> {
  if (!isRecord(value)) {
    return [];
  }
  return asArray(value.educational_sections).filter(isRecord);
}

function getAssetManifest(value: unknown): Array<Record<string, unknown>> {
  if (!isRecord(value)) {
    return [];
  }
  return asArray(value.asset_manifest).filter(isRecord);
}

function getPasses(metadata: Record<string, unknown>): ExtractionPass[] {
  return asArray(metadata.extraction_passes)
    .filter(isRecord)
    .map((item) => ({
      method: asString(item.method),
      quality_score: typeof item.quality_score === "number" ? item.quality_score : undefined,
      markdown_characters:
        typeof item.markdown_characters === "number" ? item.markdown_characters : undefined,
      images: typeof item.images === "number" ? item.images : undefined,
      tables: typeof item.tables === "number" ? item.tables : undefined,
      formulas: typeof item.formulas === "number" ? item.formulas : undefined,
      blocks: typeof item.blocks === "number" ? item.blocks : undefined,
    }));
}

export function ExtractionViewer({ data, onReset }: ExtractionViewerProps) {
  const [copied, setCopied] = useState(false);
  const layoutBlocks = useMemo(
    () => toLayoutBlocks(data.json_content),
    [data.json_content]
  );
  const layoutPages = useMemo(
    () => buildPages(layoutBlocks, data.json_content),
    [data.json_content, layoutBlocks]
  );
  const hasLayout = layoutPages.length > 0;
  const outline = useMemo(() => getOutline(data.json_content), [data.json_content]);
  const assets = useMemo(() => getAssets(data.json_content), [data.json_content]);
  const sections = useMemo(() => getSections(data.json_content), [data.json_content]);
  const assetManifest = useMemo(() => getAssetManifest(data.json_content), [data.json_content]);
  const [activeTab, setActiveTab] = useState(hasLayout ? "layout" : "markdown");
  const viewerRef = useRef<HTMLDivElement>(null);
  const metadata = data.metadata as Record<string, unknown>;
  const passes = useMemo(() => getPasses(metadata), [metadata]);

  const [semanticData, setSemanticData] = useState<any>(null);
  const [isSemanticLoading, setIsSemanticLoading] = useState(false);
  const [selectedSubject, setSelectedSubject] = useState("Social Science");
  const [selectedClass, setSelectedClass] = useState("Class 10");

  // Phase 3 — Teaching Intelligence state
  const [teachingData, setTeachingData] = useState<any>(null);
  const [isTeachingLoading, setIsTeachingLoading] = useState(false);
  const [teachingStyle, setTeachingStyle] = useState("engaging");
  const [teachingLang, setTeachingLang] = useState("english");
  const [teachingDifficulty, setTeachingDifficulty] = useState("grade_level");

  const handleGenerateSemantic = async () => {
    try {
      setIsSemanticLoading(true);
      const res = await generateSemanticIntelligence({
        markdown_content: data.markdown_content,
        force_regenerate: true
      });
      setSemanticData(res);
      toast.success(`Semantic Intelligence generated!`);
    } catch (err: any) {
      toast.error(err.message || "Failed to generate Semantic Intelligence");
    } finally {
      setIsSemanticLoading(false);
    }
  };

  const handleGenerateTeaching = async () => {
    // Phase 3 needs Phase 2 data — extract chapter_id
    const chapterId = semanticData?.data?.chapter_id
      ?? semanticData?.chapter_id
      ?? (data.metadata as any)?.chapter_id
      ?? 1;
    const standardId = semanticData?.data?.standard_id ?? (data.metadata as any)?.standard_id ?? 8;
    const subjectId = semanticData?.data?.subject_id ?? (data.metadata as any)?.subject_id ?? 101;

    try {
      setIsTeachingLoading(true);
      const res = await generateTeachingIntelligence({
        standard_id: standardId,
        subject_id: subjectId,
        chapter_id: chapterId,
        teaching_style: teachingStyle,
        language: teachingLang,
        difficulty_level: teachingDifficulty,
        force_new: true,
      });
      setTeachingData(res);
      toast.success(`Teaching Intelligence generated (${teachingStyle})!`);
    } catch (err: any) {
      toast.error(err.message || "Failed to generate Teaching Intelligence");
    } finally {
      setIsTeachingLoading(false);
    }
  };

  const diagnosticPayload = useMemo(
    () => ({
      metadata: data.metadata,
      outline,
      sections,
      assets,
      assetManifest,
      passes,
    }),
    [assetManifest, assets, data.metadata, outline, passes, sections]
  );

  const handleCopy = useCallback(async () => {
    try {
      const content =
        activeTab === "markdown"
          ? data.markdown_content
          : activeTab === "raw"
            ? data.markdown_content
            : activeTab === "diagnostics"
              ? JSON.stringify(diagnosticPayload, null, 2)
              : JSON.stringify(data.json_content, null, 2);
      await navigator.clipboard.writeText(content);
      setCopied(true);
      toast.success("Copied to clipboard.");
      setTimeout(() => setCopied(false), 2000);
    } catch {
      toast.error("Failed to copy.");
    }
  }, [activeTab, data, diagnosticPayload]);

  const handleDownload = useCallback(() => {
    const content =
      activeTab === "markdown" || activeTab === "raw"
        ? data.markdown_content
        : activeTab === "diagnostics"
          ? JSON.stringify(diagnosticPayload, null, 2)
          : JSON.stringify(data.json_content, null, 2);
    const ext = activeTab === "markdown" || activeTab === "raw" ? "md" : "json";
    const blob = new Blob([content], { type: "text/plain;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `extraction-${activeTab}.${ext}`;
    a.click();
    URL.revokeObjectURL(url);
    toast.success(`Downloaded extraction-${activeTab}.${ext}`);
  }, [activeTab, data, diagnosticPayload]);

  const wordCount = data.markdown_content.split(/\s+/).filter(Boolean).length;
  const metricBadges: Array<[string, unknown]> = [
    ["Mode", data.processing_mode],
    ["Pages", metadataValue(metadata, "page_count", data.page_count ?? "-")],
    ["Blocks", metadataValue(metadata, "layout_blocks_detected", 0)],
    ["Tables", metadataValue(metadata, "tables_detected", 0)],
    ["Formulas", metadataValue(metadata, "formulas_detected", 0)],
    ["Images", metadataValue(metadata, "images_detected", data.images_extracted)],
    ["Score", metadataValue(metadata, "educational_structure_score", 0)],
  ];

  return (
    <div className="flex h-full flex-col animate-in fade-in slide-in-from-right-4 duration-500">
      <div className="flex items-start justify-between gap-4 pb-4">
        <div className="flex items-start gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-primary/10 shadow-lg shadow-primary/10">
            <FileText className="h-5 w-5 text-primary" />
          </div>
          <div>
            <h2 className="text-lg font-semibold">Extraction Result</h2>
            <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
              <Badge
                variant="outline"
                className="border-primary/30 py-0 text-xs text-primary bg-primary/5"
              >
                Success
              </Badge>
              <span>{wordCount.toLocaleString()} words</span>
              {data.images_extracted > 0 && (
                <span className="flex items-center gap-1">
                  <ImageIcon className="h-3 w-3" />
                  {data.images_extracted} images
                </span>
              )}
            </div>
            <div className="mt-2 flex flex-wrap gap-1.5">
              {metricBadges.map(([label, value]) => (
                <Badge
                  key={label}
                  variant="outline"
                  className="border-border/40 bg-background/40 text-[10px] text-muted-foreground"
                >
                  {label}: {String(value)}
                </Badge>
              ))}
            </div>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <Button
            id="copy-button"
            variant="outline"
            size="sm"
            onClick={handleCopy}
            className="gap-1.5 border-border/50"
          >
            {copied ? (
              <Check className="h-3.5 w-3.5 text-emerald-400" />
            ) : (
              <Copy className="h-3.5 w-3.5" />
            )}
            {copied ? "Copied" : "Copy"}
          </Button>
          <Button
            id="download-button"
            variant="outline"
            size="sm"
            onClick={handleDownload}
            className="gap-1.5 border-border/50"
          >
            <Download className="h-3.5 w-3.5" />
            Download
          </Button>
          <Button
            id="new-extraction-button"
            variant="outline"
            size="sm"
            onClick={onReset}
            className="gap-1.5 border-border/50 text-muted-foreground hover:text-foreground"
          >
            <Plus className="h-3.5 w-3.5" />
            New
          </Button>
        </div>
      </div>

      <Separator className="bg-border/30" />

      <Tabs
        value={activeTab}
        onValueChange={setActiveTab}
        className="mt-4 flex min-h-0 flex-1 flex-col"
      >
        <TabsList className="w-fit bg-muted/50">
          {hasLayout && (
            <TabsTrigger value="layout" className="gap-1.5 text-sm">
              <LayoutPanelTop className="h-3.5 w-3.5" />
              Layout
            </TabsTrigger>
          )}
          <TabsTrigger value="markdown" className="gap-1.5 text-sm">
            <FileText className="h-3.5 w-3.5" />
            Rendered
          </TabsTrigger>
          <TabsTrigger value="raw" className="gap-1.5 text-sm">
            <Code2 className="h-3.5 w-3.5" />
            Raw
          </TabsTrigger>
          {data.json_content && (
            <TabsTrigger value="json" className="gap-1.5 text-sm">
              <Code2 className="h-3.5 w-3.5" />
              JSON
            </TabsTrigger>
          )}
          <TabsTrigger value="diagnostics" className="gap-1.5 text-sm">
            <BarChart3 className="h-3.5 w-3.5" />
            Diagnostics
          </TabsTrigger>
          <TabsTrigger value="semantic" className="gap-1.5 text-sm">
            <BrainCircuit className="h-3.5 w-3.5" />
            Semantic AI
          </TabsTrigger>
          <TabsTrigger value="teaching" className="gap-1.5 text-sm">
            <GraduationCap className="h-3.5 w-3.5" />
            Teaching AI
          </TabsTrigger>
        </TabsList>

        {hasLayout && (
          <TabsContent value="layout" className="mt-4 min-h-0 flex-1">
            <Card className="h-full border-border/30 bg-card/50 backdrop-blur-sm">
              <ScrollArea className="h-[calc(100vh-22rem)]">
                <CardContent className="space-y-6 p-4 lg:p-6">
                  {layoutPages.map((page) => (
                    <div key={page.pageIdx} className="space-y-2">
                      <div className="text-xs text-muted-foreground">
                        Page {page.pageIdx + 1}
                      </div>
                      <div
                        className="relative mx-auto overflow-hidden rounded-md border border-border/30 bg-white text-black shadow-lg"
                        style={{
                          aspectRatio: `${page.width} / ${page.height}`,
                          maxWidth: "900px",
                        }}
                      >
                        {page.blocks.map((block, index) => (
                          <LayoutBlockView
                            key={`${page.pageIdx}-${block.id ?? index}`}
                            block={block}
                            page={page}
                          />
                        ))}
                      </div>
                    </div>
                  ))}
                </CardContent>
              </ScrollArea>
            </Card>
          </TabsContent>
        )}

        <TabsContent value="markdown" className="mt-4 min-h-0 flex-1">
          <Card className="h-full border-border/30 bg-card/50 backdrop-blur-sm">
            <ScrollArea className="h-[calc(100vh-22rem)]">
              <CardContent className="p-6 lg:p-8" ref={viewerRef}>
                <article className="prose prose-sm max-w-none prose-headings:text-slate-900 prose-p:text-slate-600 prose-p:leading-relaxed prose-a:text-cyan-600 prose-strong:text-slate-900 prose-code:text-amber-700 prose-code:bg-slate-100 prose-code:px-1.5 prose-code:py-0.5 prose-code:rounded-md prose-code:text-xs prose-pre:bg-slate-50 prose-pre:border prose-pre:border-slate-200 prose-pre:rounded-xl prose-pre:text-slate-800 prose-table:border-slate-200 prose-th:border-slate-200 prose-td:border-slate-200 prose-hr:border-slate-200 prose-blockquote:border-l-primary/50 prose-blockquote:text-slate-600 prose-li:text-slate-600 prose-img:rounded-lg prose-img:shadow-lg">
                  <ReactMarkdown remarkPlugins={[remarkGfm]}>
                    {data.markdown_content}
                  </ReactMarkdown>
                </article>
              </CardContent>
            </ScrollArea>
          </Card>
        </TabsContent>

        <TabsContent value="raw" className="mt-4 min-h-0 flex-1">
          <CodePanel content={data.markdown_content} />
        </TabsContent>

        {data.json_content && (
          <TabsContent value="json" className="mt-4 min-h-0 flex-1">
            <CodePanel content={JSON.stringify(data.json_content, null, 2)} small />
          </TabsContent>
        )}

        <TabsContent value="diagnostics" className="mt-4 min-h-0 flex-1">
          <DiagnosticsPanel
            metadata={metadata}
            outline={outline}
            sections={sections}
            assets={assets}
            assetManifest={assetManifest}
            passes={passes}
          />
        </TabsContent>

        <TabsContent value="semantic" className="mt-4 min-h-0 flex-1">
          <Card className="h-full border-border/30 bg-card/50 backdrop-blur-sm">
            <ScrollArea className="h-[calc(100vh-22rem)]">
              <CardContent className="space-y-6 p-6">
                {!semanticData && !isSemanticLoading && (
                  <div className="flex h-64 flex-col items-center justify-center gap-4 text-center">
                    <div className="flex h-16 w-16 items-center justify-center rounded-full bg-primary/10">
                      <BrainCircuit className="h-8 w-8 text-primary" />
                    </div>
                    <div>
                      <h3 className="text-lg font-semibold">Gemini Semantic Intelligence</h3>
                      <p className="max-w-md text-sm text-muted-foreground mt-2">
                        Pass the extracted MinerU markdown through the Gemini educational pipeline to extract deep semantic topics, Bloom's Taxonomy levels, and learning goals.
                      </p>
                    </div>
                    <div className="mt-4 flex items-center justify-center gap-3">
                      <Button onClick={handleGenerateSemantic} className="shadow-md">
                        <Sparkles className="mr-2 h-4 w-4" />
                        Generate Intelligence
                      </Button>
                    </div>
                  </div>
                )}
                {isSemanticLoading && (
                  <div className="flex h-64 flex-col items-center justify-center gap-4 text-center">
                    <Loader2 className="h-8 w-8 animate-spin text-primary" />
                    <p className="text-sm text-muted-foreground">Running Gemini model... (This may take a minute)</p>
                  </div>
                )}
                {semanticData && !isSemanticLoading && (
                  <div className="space-y-6">
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <Badge variant="outline" className="bg-emerald-50 text-emerald-700 border-emerald-200">
                          {semanticData.quality_flag} Quality
                        </Badge>
                        <span className="text-xs text-muted-foreground">
                          {semanticData.total_topics} Topics • {semanticData.total_subtopics} Subtopics
                        </span>
                      </div>
                      <Button variant="outline" size="sm" onClick={handleGenerateSemantic}>
                        Regenerate
                      </Button>
                    </div>
                    <div className="rounded-lg border bg-background/50 p-4 shadow-sm">
                      <h3 className="font-semibold text-lg">{semanticData.chapter_title}</h3>
                    </div>
                    <CodePanel content={JSON.stringify(semanticData.full_intelligence_json || semanticData, null, 2)} small />
                  </div>
                )}
              </CardContent>
            </ScrollArea>
          </Card>
        </TabsContent>

        <TabsContent value="teaching" className="mt-4 min-h-0 flex-1">
          <Card className="h-full border-border/30 bg-card/50 backdrop-blur-sm">
            <ScrollArea className="h-[calc(100vh-22rem)]">
              <CardContent className="space-y-6 p-6">
                {!teachingData && !isTeachingLoading && (
                  <div className="flex h-auto flex-col items-center justify-center gap-6 text-center py-8">
                    <div className="flex h-16 w-16 items-center justify-center rounded-full bg-amber-500/10">
                      <GraduationCap className="h-8 w-8 text-amber-400" />
                    </div>
                    <div>
                      <h3 className="text-lg font-semibold">AI Teaching Intelligence</h3>
                      <p className="max-w-md text-sm text-muted-foreground mt-2">
                        Transform Phase 2 educational content into slide-by-slide teaching plans with narration, hooks, classroom activities, and memory tricks.
                      </p>
                      {!semanticData && (
                        <p className="mt-2 text-xs text-amber-500/80">
                          Run Semantic AI (Phase 2) first to enable Teaching Intelligence.
                        </p>
                      )}
                    </div>

                    <div className="grid grid-cols-3 gap-4 w-full max-w-lg mt-2">
                      <div className="space-y-1">
                        <label className="text-xs font-medium text-muted-foreground">Teaching Style</label>
                        <select
                          value={teachingStyle}
                          onChange={(e) => setTeachingStyle(e.target.value)}
                          className="h-9 w-full rounded-md border border-border bg-background px-2 py-1 text-sm shadow-sm transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                        >
                          <option value="engaging">Engaging</option>
                          <option value="storytelling">Storytelling</option>
                          <option value="serious">Serious</option>
                          <option value="activity_based">Activity Based</option>
                          <option value="exam_focused">Exam Focused</option>
                        </select>
                      </div>
                      <div className="space-y-1">
                        <label className="text-xs font-medium text-muted-foreground">Language</label>
                        <select
                          value={teachingLang}
                          onChange={(e) => setTeachingLang(e.target.value)}
                          className="h-9 w-full rounded-md border border-border bg-background px-2 py-1 text-sm shadow-sm transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                        >
                          <option value="english">English</option>
                          <option value="hindi">Hindi</option>
                          <option value="bilingual">Bilingual</option>
                        </select>
                      </div>
                      <div className="space-y-1">
                        <label className="text-xs font-medium text-muted-foreground">Difficulty</label>
                        <select
                          value={teachingDifficulty}
                          onChange={(e) => setTeachingDifficulty(e.target.value)}
                          className="h-9 w-full rounded-md border border-border bg-background px-2 py-1 text-sm shadow-sm transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                        >
                          <option value="simplified">Simplified</option>
                          <option value="grade_level">Grade Level</option>
                          <option value="advanced">Advanced</option>
                        </select>
                      </div>
                    </div>

                    <Button
                      onClick={handleGenerateTeaching}
                      disabled={!semanticData}
                      className="shadow-md mt-2"
                    >
                      <Sparkles className="mr-2 h-4 w-4" />
                      Generate Teaching Plan
                    </Button>
                  </div>
                )}
                {isTeachingLoading && (
                  <div className="flex h-64 flex-col items-center justify-center gap-4 text-center">
                    <Loader2 className="h-8 w-8 animate-spin text-amber-400" />
                    <p className="text-sm text-muted-foreground">Generating teaching plans via Gemini... (This may take a minute)</p>
                  </div>
                )}
                {teachingData && !isTeachingLoading && (
                  <div className="space-y-6">
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-2 flex-wrap">
                        <Badge variant="outline" className="bg-amber-50 text-amber-700 border-amber-200">
                          {teachingData.quality_flag} Quality
                        </Badge>
                        <Badge variant="outline" className="bg-blue-50 text-blue-700 border-blue-200">
                          {teachingData.teaching_style}
                        </Badge>
                        <span className="text-xs text-muted-foreground">
                          {teachingData.total_slides_planned} Slides Planned
                        </span>
                      </div>
                      <div className="flex items-center gap-2">
                        <select
                          value={teachingStyle}
                          onChange={(e) => setTeachingStyle(e.target.value)}
                          className="h-8 rounded-md border border-border bg-background px-2 text-xs"
                        >
                          <option value="engaging">Engaging</option>
                          <option value="storytelling">Storytelling</option>
                          <option value="serious">Serious</option>
                          <option value="activity_based">Activity Based</option>
                          <option value="exam_focused">Exam Focused</option>
                        </select>
                        <Button variant="outline" size="sm" onClick={handleGenerateTeaching}>
                          Regenerate
                        </Button>
                      </div>
                    </div>
                    <div className="rounded-lg border bg-background/50 p-4 shadow-sm">
                      <h3 className="font-semibold text-lg">{teachingData.chapter_title}</h3>
                      <p className="text-xs text-muted-foreground mt-1">
                        Style: {teachingData.teaching_style} | Language: {teachingData.language} | Tokens: {teachingData.tokens_used?.input ?? 0} in / {teachingData.tokens_used?.output ?? 0} out
                      </p>
                    </div>
                    <CodePanel content={JSON.stringify(teachingData.full_teaching_json || teachingData, null, 2)} small />
                  </div>
                )}
              </CardContent>
            </ScrollArea>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  );
}

function LayoutBlockView({ block, page }: { block: LayoutBlock; page: LayoutPage }) {
  const [x1, y1, x2, y2] = block.bbox ?? [0, 0, 0, 0];
  const style = {
    left: `${(x1 / page.width) * 100}%`,
    top: `${(y1 / page.height) * 100}%`,
    width: `${((x2 - x1) / page.width) * 100}%`,
    height: `${((y2 - y1) / page.height) * 100}%`,
  };
  const educationalRole = block.educational_role ?? block.role ?? block.type;

  if (block.type === "image" && block.img_path) {
    return (
      <figure className="absolute overflow-visible" style={style}>
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          src={block.img_path}
          alt={block.caption || block.footnote || "Extracted figure"}
          className="absolute inset-0 h-full w-full object-fill"
        />
        {(block.caption || block.footnote) && (
          <figcaption className="absolute left-0 top-full mt-1 w-full text-center text-[7px] leading-tight text-neutral-700">
            {block.caption || block.footnote}
          </figcaption>
        )}
      </figure>
    );
  }

  if (block.type === "table") {
    return (
      <div
        className="absolute overflow-hidden rounded-sm border border-neutral-300 bg-white text-[7px] leading-tight text-neutral-900"
        style={style}
      >
        {block.table_html ? (
          <div
            className="[&_table]:h-full [&_table]:w-full [&_table]:border-collapse [&_td]:border [&_td]:border-neutral-300 [&_td]:p-0.5 [&_th]:border [&_th]:border-neutral-300 [&_th]:p-0.5"
            dangerouslySetInnerHTML={{ __html: block.table_html }}
          />
        ) : (
          <div className="whitespace-pre-wrap p-1">{block.text}</div>
        )}
      </div>
    );
  }

  if (block.type === "formula" || educationalRole === "formula") {
    return (
      <div
        className="absolute flex items-center justify-center overflow-hidden rounded-sm bg-neutral-50 px-1 font-mono text-[9px] leading-tight text-neutral-950"
        style={style}
      >
        {block.text}
      </div>
    );
  }

  if (!block.text?.trim()) {
    return null;
  }

  const isHeading =
    educationalRole === "chapter_title" ||
    educationalRole === "section_heading" ||
    educationalRole === "heading";
  const isCallout = [
    "activity",
    "example",
    "exercise",
    "think_reflect",
    "pause_ponder",
    "extension_box",
    "curiosity_box",
    "biography_box",
  ].includes(String(educationalRole));

  return (
    <div
      className={`absolute overflow-hidden whitespace-pre-wrap leading-snug ${
        block.type === "footer" || block.type === "header"
          ? "text-[8px] text-neutral-500"
          : isHeading
            ? "text-[10px] font-semibold"
            : isCallout
              ? "rounded-sm bg-amber-50/70 p-0.5 text-[9px] font-medium"
              : "text-[9px]"
      }`}
      style={style}
    >
      {block.inline_items?.length
        ? block.inline_items.map((inline, inlineIndex) => (
            <span
              key={`${block.id}-${inlineIndex}`}
              className={inline.type === "formula" ? "font-mono text-[8px]" : undefined}
            >
              {inline.type === "formula" ? `$${inline.content}$` : inline.content}{" "}
            </span>
          ))
        : block.text}
    </div>
  );
}

function CodePanel({ content, small = false }: { content: string; small?: boolean }) {
  return (
    <Card className="h-full border-border/30 bg-card/50 backdrop-blur-sm">
      <ScrollArea className="h-[calc(100vh-22rem)]">
        <CardContent className="p-6">
          <pre
            className={`whitespace-pre-wrap break-words font-mono text-slate-700 dark:text-slate-300 ${
              small ? "text-xs" : "text-sm"
            } leading-relaxed`}
          >
            {content}
          </pre>
        </CardContent>
      </ScrollArea>
    </Card>
  );
}

function DiagnosticsPanel({
  metadata,
  outline,
  sections,
  assets,
  assetManifest,
  passes,
}: {
  metadata: Record<string, unknown>;
  outline: OutlineItem[];
  sections: Array<Record<string, unknown>>;
  assets: EducationalAssets;
  assetManifest: Array<Record<string, unknown>>;
  passes: ExtractionPass[];
}) {
  const stats: Array<[string, unknown]> = [
    ["Backend", metadataValue(metadata, "mineru_backend")],
    ["Method", metadataValue(metadata, "method_used")],
    ["Language", metadataValue(metadata, "ocr_language")],
    ["CPU Threads", metadataValue(metadata, "cpu_threads")],
    ["Processing Time", metadataValue(metadata, "processing_time")],
    ["Structure Score", metadataValue(metadata, "educational_structure_score", 0)],
    ["Sections", sections.length],
  ];

  return (
    <Card className="h-full border-border/30 bg-card/50 backdrop-blur-sm">
      <ScrollArea className="h-[calc(100vh-22rem)]">
        <CardContent className="space-y-6 p-6">
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
            {stats.map(([label, value]) => (
              <div
                key={label}
                className="rounded-lg border border-border/30 bg-background/40 p-4"
              >
                <div className="mb-2 flex items-center gap-2 text-xs text-muted-foreground">
                  {label === "Backend" ? (
                    <Cpu className="h-3.5 w-3.5" />
                  ) : (
                    <BarChart3 className="h-3.5 w-3.5" />
                  )}
                  {label}
                </div>
                <div className="break-words text-sm font-medium">{String(value)}</div>
              </div>
            ))}
          </div>

          <div className="grid gap-4 xl:grid-cols-2">
            {passes.length > 0 && (
              <section className="rounded-lg border border-border/30 bg-background/40 p-4 xl:col-span-2">
                <div className="mb-3 flex items-center gap-2 text-sm font-medium">
                  <BarChart3 className="h-4 w-4 text-amber-200" />
                  Quality Passes
                </div>
                <div className="grid gap-3 md:grid-cols-3">
                  {passes.map((pass) => (
                    <div
                      key={pass.method}
                      className="rounded-md border border-border/20 bg-card/40 p-3"
                    >
                      <div className="flex items-center justify-between gap-3">
                        <div className="text-sm font-medium">{pass.method}</div>
                        <Badge variant="outline" className="text-[10px]">
                          {pass.quality_score ?? 0}/100
                        </Badge>
                      </div>
                      <div className="mt-3 grid grid-cols-2 gap-2 text-xs text-muted-foreground">
                        <span>{pass.markdown_characters ?? 0} chars</span>
                        <span>{pass.blocks ?? 0} blocks</span>
                        <span>{pass.tables ?? 0} tables</span>
                        <span>{pass.formulas ?? 0} formulas</span>
                        <span>{pass.images ?? 0} images</span>
                      </div>
                    </div>
                  ))}
                </div>
              </section>
            )}

            <section className="rounded-lg border border-border/30 bg-background/40 p-4">
              <div className="mb-3 flex items-center gap-2 text-sm font-medium">
                <BookOpen className="h-4 w-4 text-cyan-300" />
                Educational Outline
              </div>
              <div className="space-y-2">
                {outline.length ? (
                  outline.slice(0, 80).map((item, index) => (
                    <div
                      key={`${item.id}-${index}`}
                      className="rounded-md border border-border/20 bg-card/40 p-3"
                    >
                      <div className="flex items-center justify-between gap-3 text-xs text-muted-foreground">
                        <span>{item.role}</span>
                        <span>Page {(item.page_idx ?? 0) + 1}</span>
                      </div>
                      <div className="mt-1 text-sm">{item.title}</div>
                    </div>
                  ))
                ) : (
                  <p className="text-sm text-muted-foreground">No outline blocks detected.</p>
                )}
              </div>
            </section>

            <section className="rounded-lg border border-border/30 bg-background/40 p-4">
              <div className="mb-3 flex items-center gap-2 text-sm font-medium">
                <ImageIcon className="h-4 w-4 text-emerald-300" />
                Extracted Assets
              </div>
              <div className="grid gap-3 sm:grid-cols-3">
                {[
                  ["Figures", assets.figures.length],
                  ["Tables", assets.tables.length],
                  ["Formulas", assets.formulas.length],
                  ["Files", assetManifest.length],
                ].map(([label, count]) => (
                  <div
                    key={label}
                    className="rounded-md border border-border/20 bg-card/40 p-3"
                  >
                    <div className="text-xs text-muted-foreground">{label}</div>
                    <div className="mt-1 text-xl font-semibold">{count}</div>
                  </div>
                ))}
              </div>
              <div className="mt-4 space-y-2">
                {assets.figures.slice(0, 12).map((figure, index) => (
                  <div
                    key={`${String(figure.id)}-${index}`}
                    className="rounded-md border border-border/20 bg-card/40 p-3 text-sm"
                  >
                    <div className="text-xs text-muted-foreground">
                      Figure on page {Number(figure.page_idx ?? 0) + 1}
                    </div>
                    <div className="mt-1 text-muted-foreground">
                      {asString(figure.caption, "No caption")}
                    </div>
                  </div>
                ))}
              </div>
            </section>

            {sections.length > 0 && (
              <section className="rounded-lg border border-border/30 bg-background/40 p-4 xl:col-span-2">
                <div className="mb-3 flex items-center gap-2 text-sm font-medium">
                  <BookOpen className="h-4 w-4 text-emerald-300" />
                  Section Map
                </div>
                <div className="grid gap-3 md:grid-cols-2">
                  {sections.slice(0, 30).map((section, index) => (
                    <div
                      key={`${String(section.id)}-${index}`}
                      className="rounded-md border border-border/20 bg-card/40 p-3"
                    >
                      <div className="text-xs text-muted-foreground">
                        Page {Number(section.page_idx ?? 0) + 1} - {String(section.role ?? "section")}
                      </div>
                      <div className="mt-1 text-sm font-medium">
                        {String(section.title ?? "Untitled section")}
                      </div>
                      <div className="mt-2 flex flex-wrap gap-1.5 text-[10px] text-muted-foreground">
                        <Badge variant="outline">Blocks: {asArray(section.block_ids).length}</Badge>
                        <Badge variant="outline">Figures: {asArray(section.figures).length}</Badge>
                        <Badge variant="outline">Tables: {asArray(section.tables).length}</Badge>
                        <Badge variant="outline">Formulas: {asArray(section.formulas).length}</Badge>
                      </div>
                    </div>
                  ))}
                </div>
              </section>
            )}
          </div>
        </CardContent>
      </ScrollArea>
    </Card>
  );
}
