"use client";

import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import toast from "react-hot-toast";
import { extractPdf, type ExtractionResponse } from "@/lib/api";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import {
  ArrowRight,
  Cpu,
  FileText,
  Globe,
  Loader2,
  Sparkles,
  Table2,
  X,
  Zap,
} from "lucide-react";

interface ExtractionFormProps {
  onSuccess: (data: ExtractionResponse) => void;
}

const SAMPLE_URLS = [
  {
    label: "Science Ch.1",
    url: "https://ncert.nic.in/textbook/pdf/iesc101.pdf",
  },
  {
    label: "Maths Ch.1",
    url: "https://ncert.nic.in/textbook/pdf/iemh101.pdf",
  },
  {
    label: "History Ch.1",
    url: "https://ncert.nic.in/textbook/pdf/iess301.pdf",
  },
];

import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Upload } from "lucide-react";
import { CustomSelect } from "@/components/ui/custom-select";

export function ExtractionForm({ onSuccess }: ExtractionFormProps) {
  const [url, setUrl] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [activeTab, setActiveTab] = useState("url");

  // Metadata State
  const [documentType, setDocumentType] = useState("Chapter");
  const [documentTitle, setDocumentTitle] = useState("");
  const [chapterNumber, setChapterNumber] = useState("");
  const [standard, setStandard] = useState("10");
  const [subjectName, setSubjectName] = useState("Science");
  const [board, setBoard] = useState("CBSE");
  const [syear, setSyear] = useState("2024-2025");
  const [customSubject, setCustomSubject] = useState("");

  const getMetadata = () => ({
    document_type: documentType,
    document_title: documentTitle,
    chapter_number: chapterNumber,
    standard,
    subject_name: subjectName === "Others" ? customSubject : subjectName,
    board,
    syear,
  });

  const urlMutation = useMutation({
    mutationFn: extractPdf,
    onSuccess: (data) => {
      toast.success("PDF extracted successfully.");
      onSuccess(data);
    },
    onError: (error: Error & { response?: { data?: { detail?: string } } }) => {
      const message =
        error.response?.data?.detail ||
        error.message ||
        "Extraction failed. Please try again.";
      toast.error(message);
    },
  });

  const uploadMutation = useMutation({
    mutationFn: async ({ f, meta }: { f: File; meta: any }) => {
      const { uploadPdf } = await import("@/lib/api");
      return uploadPdf(f, meta);
    },
    onSuccess: (data) => {
      toast.success("PDF uploaded and extracted successfully.");
      onSuccess(data);
    },
    onError: (error: Error & { response?: { data?: { detail?: string } } }) => {
      const message =
        error.response?.data?.detail ||
        error.message ||
        "Upload failed. Please try again.";
      toast.error(message);
    },
  });

  const isPending = urlMutation.isPending || uploadMutation.isPending;
  const isSuccess = urlMutation.isSuccess || uploadMutation.isSuccess;

  const handleUrlSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const pdfUrl = url.trim();
    if (!pdfUrl) {
      toast.error("Please enter a PDF URL.");
      return;
    }
    try {
      new URL(pdfUrl);
    } catch {
      toast.error("Please enter a valid URL.");
      return;
    }
    urlMutation.mutate({ pdf_url: pdfUrl, ...getMetadata() });
  };

  const handleFileSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!file) {
      toast.error("Please select a PDF file.");
      return;
    }
    // Note: To fully support standard_id/etc for uploads, the backend upload endpoint 
    // needs to accept FormData with these fields. For now we just mutate the file.
    uploadMutation.mutate({ f: file, meta: getMetadata() });
  };

  return (
    <div className="flex flex-col gap-4 h-full min-h-0">
      <div className="space-y-2 shrink-0">
        <div className="inline-flex items-center gap-2 rounded-full border border-white/10 bg-white/5 backdrop-blur-md px-4 py-1.5 text-sm font-medium text-foreground shadow-sm">
          <Cpu className="h-3.5 w-3.5" />
          CPU Document Intelligence
        </div>
        <h1 className="text-3xl font-bold tracking-tight lg:text-4xl text-foreground">
          PDF EXTRACTOR
        </h1>
      </div>

      <Card className="overflow-visible flex flex-col flex-1 min-h-0 border-[0.5px] border-black/5 dark:border-white/10 bg-white/40 dark:bg-black/40 backdrop-blur-[24px] saturate-150 shadow-[0_8px_32px_0_rgba(0,0,0,0.04)] rounded-[24px]">
        <Tabs value={activeTab} onValueChange={setActiveTab} className="flex flex-1 flex-col">
          <CardHeader className="pb-3 shrink-0 flex flex-row items-center justify-between">
            <div className="space-y-1.5">
              <CardTitle className="flex items-center gap-2 text-base">
                <Globe className="h-4 w-4 text-muted-foreground" />
                PDF Source
              </CardTitle>
              <CardDescription>
                Provide a PDF link or upload a file.
              </CardDescription>
            </div>
            <TabsList className="grid w-[180px] grid-cols-2">
              <TabsTrigger value="url">URL</TabsTrigger>
              <TabsTrigger value="upload">Upload</TabsTrigger>
            </TabsList>
          </CardHeader>
          <CardContent className="space-y-4 flex flex-1 flex-col min-h-0 overflow-y-auto overflow-x-visible custom-scrollbar pb-6">
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3 shrink-0 animate-in fade-in slide-in-from-bottom-2 duration-500">
              <div className="space-y-1.5 relative z-[60]">
                <label className="text-xs font-medium text-foreground/80 pl-1">Document Type</label>
                <CustomSelect
                  value={documentType}
                  onChange={setDocumentType}
                  options={[
                    { label: "Chapter", value: "Chapter" },
                    { label: "Curriculum", value: "Curriculum" },
                    { label: "Syllabus", value: "Syllabus" },
                  ]}
                />
              </div>
              
              <div className="space-y-1.5">
                <label className="text-xs font-medium text-foreground/80 pl-1">Document Title</label>
                <input type="text" value={documentTitle} onChange={e => setDocumentTitle(e.target.value)} placeholder="e.g. Chemical Reactions" className="h-10 w-full rounded-xl border-[0.5px] border-black/10 dark:border-white/10 bg-white/50 dark:bg-black/50 px-3 text-sm outline-none backdrop-blur-md transition-colors focus:border-primary focus:ring-1 focus:ring-primary placeholder:text-muted-foreground/50 hover:bg-white/60 dark:hover:bg-black/60" />
              </div>

              <div className="space-y-1.5">
                <label className="text-xs font-medium text-foreground/80 pl-1">Chapter Number</label>
                <input type="text" value={chapterNumber} onChange={e => setChapterNumber(e.target.value)} placeholder="e.g. 1" className="h-10 w-full rounded-xl border-[0.5px] border-black/10 dark:border-white/10 bg-white/50 dark:bg-black/50 px-3 text-sm outline-none backdrop-blur-md transition-colors focus:border-primary focus:ring-1 focus:ring-primary placeholder:text-muted-foreground/50 hover:bg-white/60 dark:hover:bg-black/60" />
              </div>

              <div className="space-y-1.5 relative z-[50]">
                <label className="text-xs font-medium text-foreground/80 pl-1">Standard</label>
                <CustomSelect
                  value={standard}
                  onChange={setStandard}
                  options={["1","2","3","4","5","6","7","8","9","10","11","12"].map(s => ({ label: `Standard ${s}`, value: s }))}
                />
              </div>

              <div className="space-y-1.5 relative z-[40]">
                <label className="text-xs font-medium text-foreground/80 pl-1">Subject Name</label>
                <div className="flex flex-col gap-2">
                  <CustomSelect
                    value={subjectName}
                    onChange={setSubjectName}
                    options={["Maths", "Science", "Physics", "Chemistry", "Biology", "History", "Geography", "Civics", "Economics", "English", "Hindi", "Sanskrit", "Accountancy", "Business Studies", "Computer Science", "Information Practices", "Physical Education", "Others"].map(s => ({ label: s, value: s }))}
                  />
                  {subjectName === "Others" && (
                    <input autoFocus type="text" value={customSubject} onChange={e => setCustomSubject(e.target.value)} placeholder="Type custom subject..." className="h-10 w-full rounded-xl border-[0.5px] border-primary/40 bg-primary/5 px-3 text-sm outline-none backdrop-blur-md transition-all focus:border-primary focus:ring-1 focus:ring-primary placeholder:text-muted-foreground/50 animate-in slide-in-from-top-1 fade-in duration-200" />
                  )}
                </div>
              </div>

              <div className="space-y-1.5">
                <label className="text-xs font-medium text-foreground/80 pl-1">Board</label>
                <input type="text" value={board} onChange={e => setBoard(e.target.value)} placeholder="CBSE" className="h-10 w-full rounded-xl border-[0.5px] border-black/10 dark:border-white/10 bg-white/50 dark:bg-black/50 px-3 text-sm outline-none backdrop-blur-md transition-colors focus:border-primary focus:ring-1 focus:ring-primary placeholder:text-muted-foreground/50 hover:bg-white/60 dark:hover:bg-black/60" />
              </div>

              <div className="space-y-1.5 md:col-span-2 relative z-[30]">
                <label className="text-xs font-medium text-foreground/80 pl-1">Academic Year</label>
                <CustomSelect
                  value={syear}
                  onChange={setSyear}
                  options={["2022-2023", "2023-2024", "2024-2025", "2025-2026", "2026-2027", "2027-2028", "2028-2029", "2029-2030", "2030-2031"].map(y => ({ label: y, value: y }))}
                />
              </div>
            </div>

            <TabsContent value="url" className="mt-auto pt-4 shrink-0">
              <form onSubmit={handleUrlSubmit} className="space-y-4">
                <div className="flex gap-3">
                  <div className="relative min-w-0 flex-1">
                    <input
                      id="pdf-url-input"
                      type="text"
                      inputMode="url"
                      autoComplete="url"
                      spellCheck={false}
                      placeholder="https://ncert.nic.in/textbook/pdf/..."
                      value={url}
                      onChange={(e) => setUrl(e.target.value)}
                      disabled={isPending}
                      suppressHydrationWarning
                      className="h-12 w-full min-w-0 rounded-lg border border-border/50 bg-background/50 px-3 pr-10 text-base outline-none transition-colors placeholder:text-muted-foreground/50 focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-primary/30 disabled:pointer-events-none disabled:cursor-not-allowed disabled:opacity-50"
                    />
                    {url && !isPending && (
                      <button
                        type="button"
                        aria-label="Clear PDF URL"
                        onClick={() => setUrl("")}
                        className="absolute right-2 top-1/2 flex h-7 w-7 -translate-y-1/2 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
                      >
                        <X className="h-4 w-4" />
                      </button>
                    )}
                  </div>
                  <Button
                    id="extract-button"
                    type="submit"
                    disabled={isPending || !url.trim()}
                    className="h-12 px-6 font-medium shadow-lg shadow-cyan-500/15 transition-all hover:scale-[1.02] active:scale-[0.98]"
                  >
                    {isPending ? (
                      <>
                        <Loader2 className="h-4 w-4 animate-spin" />
                        Extracting
                      </>
                    ) : (
                      <>
                        <FileText className="h-4 w-4" />
                        Extract
                        <ArrowRight className="h-4 w-4" />
                      </>
                    )}
                  </Button>
                </div>

                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-xs text-muted-foreground">Try:</span>
                  {SAMPLE_URLS.map((sample) => (
                    <Badge
                      key={sample.label}
                      variant="outline"
                      className="cursor-pointer border-border/50 px-3 py-1 text-xs transition-colors hover:bg-accent"
                      onClick={() => setUrl(sample.url)}
                    >
                      {sample.label}
                    </Badge>
                  ))}
                </div>
              </form>
            </TabsContent>
            
            <TabsContent value="upload" className="mt-auto pt-4 shrink-0">
              <form onSubmit={handleFileSubmit} className="space-y-4">
                <div className="flex gap-3">
                  <div className="relative min-w-0 flex-1">
                    <input
                      id="pdf-file-input"
                      type="file"
                      accept="application/pdf"
                      onChange={(e) => setFile(e.target.files?.[0] || null)}
                      disabled={isPending}
                      className="file:mr-4 file:py-2 file:px-4 file:rounded-md file:border-0 file:text-sm file:font-semibold file:bg-primary/10 file:text-primary hover:file:bg-primary/20 flex h-12 w-full min-w-0 items-center justify-center rounded-lg border border-border/50 bg-background/50 px-3 text-base outline-none transition-colors focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-primary/30 disabled:pointer-events-none disabled:cursor-not-allowed disabled:opacity-50"
                    />
                  </div>
                  <Button
                    id="upload-button"
                    type="submit"
                    disabled={isPending || !file}
                    className="h-12 px-6 font-medium shadow-lg shadow-cyan-500/15 transition-all hover:scale-[1.02] active:scale-[0.98]"
                  >
                    {isPending ? (
                      <>
                        <Loader2 className="h-4 w-4 animate-spin" />
                        Extracting
                      </>
                    ) : (
                      <>
                        <Upload className="h-4 w-4" />
                        Upload
                        <ArrowRight className="h-4 w-4" />
                      </>
                    )}
                  </Button>
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-xs text-muted-foreground">Accepts: PDF files only. (Max ~50MB recommended)</span>
                </div>
              </form>
            </TabsContent>
          </CardContent>
        </Tabs>
      </Card>

      {isPending && (
        <Card className="animate-in fade-in border-[0.5px] border-black/5 dark:border-white/10 bg-white/40 dark:bg-black/40 backdrop-blur-[24px] saturate-150 shadow-[0_8px_32px_0_rgba(0,0,0,0.04)] rounded-[24px] duration-300">
          <CardContent className="py-8">
            <div className="flex flex-col items-center gap-4">
              <div className="relative">
                <div className="absolute inset-0 h-16 w-16 rounded-full bg-primary/10 animate-ping" />
                <div className="relative flex h-16 w-16 items-center justify-center rounded-full bg-primary/20 shadow-lg shadow-primary/20">
                  <Zap className="h-7 w-7 text-primary animate-pulse" />
                </div>
              </div>

              <div className="space-y-2 text-center">
                <p className="font-semibold text-foreground">
                  Extracting PDF Content
                </p>
                <p className="max-w-xs text-sm text-muted-foreground">
                  MinerU is running layout analysis, OCR, table parsing,
                  formula extraction, and educational structure enrichment.
                </p>
              </div>

              <div className="mt-2 w-full max-w-xs space-y-2">
                {[
                  "Downloading / Preparing PDF...",
                  "Running CPU layout analysis...",
                  "Extracting tables, formulas, and diagrams...",
                  "Building markdown, JSON, and diagnostics...",
                ].map((step, i) => (
                  <div
                    key={step}
                    className="flex items-center gap-3 text-sm animate-in fade-in slide-in-from-left-2"
                    style={{
                      animationDelay: `${i * 1.5}s`,
                      animationFillMode: "backwards",
                    }}
                  >
                    <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin text-primary" />
                    <span className="text-muted-foreground">{step}</span>
                  </div>
                ))}
              </div>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
