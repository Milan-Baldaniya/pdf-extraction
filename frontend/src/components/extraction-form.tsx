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

export function ExtractionForm({ onSuccess }: ExtractionFormProps) {
  const [url, setUrl] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [activeTab, setActiveTab] = useState("url");

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
    mutationFn: async (f: File) => {
      const { uploadPdf } = await import("@/lib/api");
      return uploadPdf(f);
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
    urlMutation.mutate({ pdf_url: pdfUrl });
  };

  const handleFileSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!file) {
      toast.error("Please select a PDF file.");
      return;
    }
    // Note: To fully support standard_id/etc for uploads, the backend upload endpoint 
    // needs to accept FormData with these fields. For now we just mutate the file.
    uploadMutation.mutate(file);
  };

  return (
    <div className="flex flex-col gap-6">
      <div className="space-y-3">
        <div className="inline-flex items-center gap-2 rounded-full border border-primary/20 bg-primary/5 px-4 py-1.5 text-sm font-medium text-primary">
          <Cpu className="h-3.5 w-3.5" />
          CPU Document Intelligence
        </div>
        <h1 className="text-3xl font-bold tracking-tight lg:text-4xl">
          NCERT
          <span className="bg-gradient-to-r from-cyan-300 via-emerald-300 to-amber-200 bg-clip-text text-transparent">
            {" "}Extractor
          </span>
        </h1>
        <p className="max-w-md leading-relaxed text-muted-foreground">
          Extract structured NCERT content with MinerU CPU pipeline, OCR,
          formulas, tables, diagrams, and educational layout diagnostics.
        </p>
      </div>

      <Card className="border-border/50 bg-card/50 backdrop-blur-sm">
        <Tabs value={activeTab} onValueChange={setActiveTab}>
          <CardHeader className="pb-4 flex flex-row items-center justify-between">
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
          <CardContent>
            <TabsContent value="url" className="mt-0">
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
            
            <TabsContent value="upload" className="mt-0">
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
        <Card className="animate-in fade-in border-cyan-500/20 bg-cyan-500/5 duration-300">
          <CardContent className="py-8">
            <div className="flex flex-col items-center gap-4">
              <div className="relative">
                <div className="absolute inset-0 h-16 w-16 rounded-full bg-cyan-500/15 animate-ping" />
                <div className="relative flex h-16 w-16 items-center justify-center rounded-full bg-cyan-500/20 shadow-lg shadow-cyan-500/20">
                  <Zap className="h-7 w-7 text-cyan-200 animate-pulse" />
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
                    <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin text-cyan-300" />
                    <span className="text-muted-foreground">{step}</span>
                  </div>
                ))}
              </div>
            </div>
          </CardContent>
        </Card>
      )}

      {!isPending && !isSuccess && (
        <div className="grid grid-cols-1 gap-4 animate-in fade-in duration-500 sm:grid-cols-3">
          {[
            {
              icon: FileText,
              title: "Markdown + JSON",
              desc: "Clean content and structured blocks",
            },
            {
              icon: Table2,
              title: "Tables + Formulas",
              desc: "MinerU pipeline parsing enabled",
            },
            {
              icon: Sparkles,
              title: "Education Structure",
              desc: "Headings, activities, captions, assets",
            },
          ].map((feature) => (
            <div
              key={feature.title}
              className="flex items-start gap-3 rounded-lg border border-border/30 bg-card/30 p-4"
            >
              <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-primary/10">
                <feature.icon className="h-4 w-4 text-primary" />
              </div>
              <div>
                <p className="text-sm font-medium">{feature.title}</p>
                <p className="text-xs text-muted-foreground">{feature.desc}</p>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
