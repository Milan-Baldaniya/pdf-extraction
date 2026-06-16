"use client";

import React, { useCallback, useMemo } from 'react';
import {
  ReactFlow,
  MiniMap,
  Controls,
  Background,
  useNodesState,
  useEdgesState,
  Handle,
  Position,
  BackgroundVariant,
  MarkerType,
  Panel,
  Edge,
  Node,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import { Key, Link, Sparkles, Database, FileText, Bot, ArrowRight, BrainCircuit } from 'lucide-react';

const TableNode = ({ id, data }: any) => {
  const isHovered = data.hoveredNodeId === id;
  const isDimmed = data.hoveredNodeId !== null && data.hoveredNodeId !== id;

  return (
    <div 
      className={`bg-white/90 dark:bg-black/90 backdrop-blur-xl rounded-xl border border-black/10 dark:border-white/10 shadow-2xl overflow-hidden min-w-[320px] transition-all duration-500 ease-out origin-center ${
        isHovered ? 'scale-[1.25] ring-8 ring-purple-500/30 z-50' : ''
      } ${
        isDimmed ? 'opacity-30 grayscale-[0.8] blur-[2px] scale-[0.98]' : 'opacity-100'
      }`}
    >
      <div className="bg-gradient-to-r from-blue-500/10 to-purple-500/10 p-4 border-b border-black/10 dark:border-white/10 flex items-center gap-2">
        <Database className="h-5 w-5 text-blue-500" />
        <span className="font-bold text-base tracking-wide">{data.label}</span>
      </div>
      <div className="flex flex-col py-3">
        {data.columns.map((col: any, index: number) => (
          <div key={col.name} className="relative group px-5 py-2 flex items-center justify-between hover:bg-black/5 dark:hover:bg-white/5 transition-colors">

            {/* Source Handle (Right) */}
            <Handle
              type="source"
              position={Position.Right}
              id={col.name}
              className="w-2 h-2 !bg-blue-500 !border-white dark:!border-black opacity-0 group-hover:opacity-100 transition-opacity"
            />
            {/* Target Handle (Left) */}
            <Handle
              type="target"
              position={Position.Left}
              id={col.name}
              className="w-2 h-2 !bg-emerald-500 !border-white dark:!border-black opacity-0 group-hover:opacity-100 transition-opacity"
            />

            <div className="flex items-center gap-3">
              {col.isPrimary && <Key className="h-4 w-4 text-amber-500" />}
              {col.isForeign && <Link className="h-4 w-4 text-blue-500" />}
              {!col.isPrimary && !col.isForeign && <div className="w-4" />}
              <span className={`text-sm font-mono ${col.isPrimary ? 'font-extrabold text-foreground' : 'font-medium text-foreground/80'}`}>{col.name}</span>
            </div>
            <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wider bg-black/5 dark:bg-white/5 px-2 py-0.5 rounded-md">{col.type}</span>
          </div>
        ))}
      </div>
    </div>
  );
};

const LLMNode = ({ id, data }: any) => {
  const isHovered = data.hoveredNodeId === id;
  const isDimmed = data.hoveredNodeId !== null && data.hoveredNodeId !== id;

  return (
    <div 
      className={`bg-gradient-to-br from-indigo-500 to-purple-600 p-[1px] rounded-2xl shadow-xl shadow-purple-500/20 w-[380px] transition-all duration-500 ease-out origin-center ${
        isHovered ? 'scale-[1.25] ring-8 ring-indigo-500/30 z-50' : ''
      } ${
        isDimmed ? 'opacity-30 grayscale-[0.8] blur-[2px] scale-[0.98]' : 'opacity-100'
      }`}
    >
      <div className="bg-white dark:bg-black rounded-[15px] p-5 h-full relative flex flex-col gap-4">
        <Handle type="target" position={Position.Left} id="in" className="w-3 h-3 !bg-purple-500" />
        <Handle type="source" position={Position.Right} id="out" className="w-3 h-3 !bg-purple-500" />

        <div className="flex items-center gap-3 border-b border-black/10 dark:border-white/10 pb-3">
          <BrainCircuit className="h-6 w-6 text-indigo-500" />
          <div>
            <h3 className="font-bold text-base text-indigo-600 dark:text-indigo-400">{data.label}</h3>
            <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider">{data.role}</p>
          </div>
        </div>

        {data.description && (
          <div className="bg-indigo-500/10 dark:bg-indigo-500/20 p-3 rounded-lg border border-indigo-500/20">
            <p className="text-sm font-medium text-indigo-900 dark:text-indigo-100 leading-snug">
              {data.description}
            </p>
          </div>
        )}

        <div className="flex flex-col gap-2">
          <div className="flex items-center justify-between bg-black/5 dark:bg-white/5 p-2 rounded-lg">
            <span className="text-xs font-mono font-semibold text-muted-foreground">IN:</span>
            <span className="text-sm font-medium bg-blue-100 text-blue-700 dark:bg-blue-900/50 dark:text-blue-300 px-2 py-0.5 rounded-md">{data.input}</span>
          </div>
          <div className="flex items-center justify-between bg-black/5 dark:bg-white/5 p-2 rounded-lg">
            <span className="text-xs font-mono font-semibold text-muted-foreground">OUT:</span>
            <span className="text-sm font-medium bg-emerald-100 text-emerald-700 dark:bg-emerald-900/50 dark:text-emerald-300 px-2 py-0.5 rounded-md">{data.output}</span>
          </div>
        </div>
      </div>
    </div>
  );
};

const initialNodes: Node[] = [
  // -----------------------------------------
  // CORE EXTRACTION
  // -----------------------------------------
  {
    id: 'doc_extract',
    type: 'tableNode',
    position: { x: -100, y: 200 },
    data: {
      label: 'document_extractions',
      columns: [
        { name: 'id', type: 'integer', isPrimary: true },
        { name: 'document_type', type: 'varchar' },
        { name: 'document_title', type: 'varchar' },
        { name: 'document_text', type: 'text' },
        { name: 'file_name', type: 'varchar' },
        { name: 'file_size', type: 'integer' },
        { name: 'total_pages', type: 'integer' },
        { name: 'file_path', type: 'varchar' },
        { name: 'md_content', type: 'text' },
        { name: 'processed_images', type: 'json' },
        { name: 'subject_name', type: 'varchar' },
        { name: 'standard', type: 'integer' },
        { name: 'chapter_number', type: 'integer' },
        { name: 'board', type: 'varchar' },
        { name: 'syear', type: 'varchar' },
        { name: 'created_at', type: 'datetime' },
        { name: 'updated_at', type: 'datetime' },
      ],
    },
  },

  // -----------------------------------------
  // MASTERS (Left Side)
  // -----------------------------------------
  {
    id: 'standard_master',
    type: 'tableNode',
    position: { x: -600, y: 600 },
    data: {
      label: 'standard_master',
      columns: [
        { name: 'id', type: 'integer', isPrimary: true },
        { name: 'standard_name', type: 'varchar' },
      ],
    },
  },
  {
    id: 'subject_master',
    type: 'tableNode',
    position: { x: -600, y: 800 },
    data: {
      label: 'subject_master',
      columns: [
        { name: 'id', type: 'integer', isPrimary: true },
        { name: 'subject_name', type: 'varchar' },
      ],
    },
  },

  // -----------------------------------------
  // CURRICULUM PIPELINE (Top)
  // -----------------------------------------
  {
    id: 'llm_curriculum',
    type: 'llmNode',
    position: { x: 400, y: -50 },
    data: {
      label: 'Gemini 2.5 Flash',
      role: 'Curriculum Parsing',
      description: 'Extracts the structured framework directly from the raw markdown document. Maps the syllabus into standard units, calculates total marks, and instantly populates the lms_curriculum and lms_units tables.',
      input: 'Markdown Content',
      output: 'JSON Schema (Framework)',
    },
  },
  {
    id: 'lms_curriculum',
    type: 'tableNode',
    position: { x: 900, y: -150 },
    data: {
      label: 'lms_curriculum',
      columns: [
        { name: 'id', type: 'integer', isPrimary: true },
        { name: 'extraction_id', type: 'integer', isForeign: true },
        { name: 'framework', type: 'varchar' },
        { name: 'total_marks', type: 'integer' },
        { name: 'internal_marks', type: 'integer' },
        { name: 'created_at', type: 'datetime' },
      ],
    },
  },
  {
    id: 'lms_units',
    type: 'tableNode',
    position: { x: 1400, y: -150 },
    data: {
      label: 'lms_units',
      columns: [
        { name: 'id', type: 'integer', isPrimary: true },
        { name: 'curriculum_id', type: 'integer', isForeign: true },
        { name: 'unit_number', type: 'varchar' },
        { name: 'unit_name', type: 'varchar' },
        { name: 'unit_chapter', type: 'varchar' },
        { name: 'marks', type: 'integer' },
        { name: 'created_at', type: 'datetime' },
      ],
    },
  },
  {
    id: 'lms_learning_outcomes',
    type: 'tableNode',
    position: { x: 1400, y: 200 },
    data: {
      label: 'lms_learning_outcomes',
      columns: [
        { name: 'id', type: 'integer', isPrimary: true },
        { name: 'curriculum_id', type: 'integer', isForeign: true },
        { name: 'extraction_id', type: 'integer', isForeign: true },
        { name: 'standard_id', type: 'integer', isForeign: true },
        { name: 'subject_id', type: 'integer', isForeign: true },
        { name: 'chapter_id', type: 'integer', isForeign: true },
        { name: 'parent_id', type: 'integer', isForeign: true },
        { name: 'code', type: 'varchar' },
        { name: 'type', type: 'varchar' },
        { name: 'description', type: 'text' },
        { name: 'created_at', type: 'datetime' },
        { name: 'updated_at', type: 'datetime' },
      ],
    },
  },

  // -----------------------------------------
  // -----------------------------------------
  // CHAPTER PIPELINE (Middle)
  // -----------------------------------------
  {
    id: 'llm_chapter',
    type: 'llmNode',
    position: { x: 400, y: 350 },
    data: {
      label: 'Gemini 2.5 Flash',
      role: 'Chapter Matching',
      description: 'Scans the extracted curriculum to explicitly identify and isolate individual chapters. It pairs these chapters back to their parent unit_id and generates the core rows for the chapter_master table.',
      input: 'Markdown Content',
      output: 'JSON Schema (Match)',
    },
  },
  {
    id: 'chapter_master',
    type: 'tableNode',
    position: { x: 900, y: 300 },
    data: {
      label: 'chapter_master',
      columns: [
        { name: 'id', type: 'integer', isPrimary: true },
        { name: 'extraction_id', type: 'integer', isForeign: true },
        { name: 'unit_id', type: 'integer', isForeign: true },
        { name: 'chapter_name', type: 'varchar' },
        { name: 'status', type: 'varchar' },
        { name: 'key_concepts', type: 'json' },
        { name: 'created_at', type: 'datetime' },
      ],
    },
  },
  {
    id: 'lms_concept',
    type: 'tableNode',
    position: { x: 1400, y: 750 },
    data: {
      label: 'lms_concept',
      columns: [
        { name: 'id', type: 'integer', isPrimary: true },
        { name: 'extraction_id', type: 'integer', isForeign: true },
        { name: 'name', type: 'varchar' },
        { name: 'description', type: 'text' },
        { name: 'standard_id', type: 'integer', isForeign: true },
        { name: 'subject_id', type: 'integer', isForeign: true },
        { name: 'chapter_id', type: 'integer', isForeign: true },
        { name: 'sub_institute_id', type: 'integer' },
        { name: 'mastery_threshold', type: 'integer' },
        { name: 'estimated_mastery_minutes', type: 'integer' },
        { name: 'syear', type: 'varchar' },
        { name: 'created_at', type: 'datetime' },
      ],
    },
  },

  // -----------------------------------------
  // CONCEPT PIPELINE
  // -----------------------------------------
  {
    id: 'llm_concept',
    type: 'llmNode',
    position: { x: 400, y: 600 },
    data: {
      label: 'DeepSeek (Pedagogical)',
      role: 'Mastery & Depth Analysis',
      description: 'Uses Cognitive Load Theory and Blooms Taxonomy to analyze chapter markdown and generate scientifically-backed mastery thresholds and learning times.',
      input: 'Markdown & Key Concepts',
      output: 'JSON Mastery Schema',
    },
  },

  // -----------------------------------------
  // SEMANTIC INTELLIGENCE PIPELINE (Bottom)
  // -----------------------------------------
  {
    id: 'llm_semantic',
    type: 'llmNode',
    position: { x: 400, y: 850 },
    data: {
      label: 'Gemini 2.5 Flash (Two-Pass)',
      role: 'Deep Semantic Extraction',
      description: 'Performs deep semantic chunking and learning objective isolation for every single chapter. It processes the text, measures AI token costs, checks quality flags, and creates the massive intelligence payload for the semantic_intelligence table.',
      input: 'Markdown Content',
      output: 'JSON Deep Metdata',
    },
  },
  {
    id: 'semantic_intelligence',
    type: 'tableNode',
    position: { x: 900, y: 750 },
    data: {
      label: 'semantic_intelligence',
      columns: [
        { name: 'extraction_id', type: 'integer', isPrimary: true, isForeign: true },
        { name: 'standard_id', type: 'integer' },
        { name: 'subject_id', type: 'integer' },
        { name: 'chapter_id', type: 'integer', isForeign: true },
        { name: 'subject_name', type: 'varchar' },
        { name: 'standard', type: 'integer' },
        { name: 'chapter_number', type: 'integer' },
        { name: 'learning_objective', type: 'varchar' },
        { name: 'total_topics', type: 'integer' },
        { name: 'full_intelegance_json', type: 'json' },
        { name: 'llm_model', type: 'varchar' },
        { name: 'input_token', type: 'integer' },
        { name: 'output_token', type: 'integer' },
        { name: 'quality_flag', type: 'varchar' },
      ],
    },
  },
];

const initialEdges: Edge[] = [
  // Data Flow to LLMs
  { id: 'e-doc-curr', source: 'doc_extract', sourceHandle: 'md_content', target: 'llm_curriculum', targetHandle: 'in', animated: true, style: { stroke: '#8b5cf6', strokeWidth: 2 } },
  { id: 'e-doc-chap', source: 'doc_extract', sourceHandle: 'md_content', target: 'llm_chapter', targetHandle: 'in', animated: true, style: { stroke: '#8b5cf6', strokeWidth: 2 } },
  { id: 'e-doc-concept', source: 'doc_extract', sourceHandle: 'md_content', target: 'llm_concept', targetHandle: 'in', animated: true, style: { stroke: '#8b5cf6', strokeWidth: 2 } },
  { id: 'e-chap-concept-in', source: 'chapter_master', sourceHandle: 'key_concepts', target: 'llm_concept', targetHandle: 'in', animated: true, style: { stroke: '#8b5cf6', strokeWidth: 2, strokeDasharray: '4,4' } },
  { id: 'e-doc-sem', source: 'doc_extract', sourceHandle: 'md_content', target: 'llm_semantic', targetHandle: 'in', animated: true, style: { stroke: '#8b5cf6', strokeWidth: 2 } },

  // LLM Outputs to Tables
  { id: 'e-llm-curr', source: 'llm_curriculum', sourceHandle: 'out', target: 'lms_curriculum', targetHandle: 'extraction_id', animated: true, style: { stroke: '#10b981', strokeWidth: 2 } },
  { id: 'e-llm-chap', source: 'llm_chapter', sourceHandle: 'out', target: 'chapter_master', targetHandle: 'extraction_id', animated: true, style: { stroke: '#10b981', strokeWidth: 2 } },
  { id: 'e-llm-concept', source: 'llm_concept', sourceHandle: 'out', target: 'lms_concept', targetHandle: 'extraction_id', animated: true, style: { stroke: '#10b981', strokeWidth: 2 } },
  { id: 'e-llm-sem', source: 'llm_semantic', sourceHandle: 'out', target: 'semantic_intelligence', targetHandle: 'extraction_id', animated: true, style: { stroke: '#10b981', strokeWidth: 2 } },

  // Foreign Key Relationships
  {
    id: 'e-fk-doc-curr',
    source: 'doc_extract', sourceHandle: 'id',
    target: 'lms_curriculum', targetHandle: 'extraction_id',
    type: 'smoothstep',
    markerEnd: { type: MarkerType.ArrowClosed, color: '#3b82f6' },
    style: { stroke: '#3b82f6', strokeWidth: 2, strokeDasharray: '5,5' }
  },
  {
    id: 'e-fk-doc-chap',
    source: 'doc_extract', sourceHandle: 'id',
    target: 'chapter_master', targetHandle: 'extraction_id',
    type: 'smoothstep',
    markerEnd: { type: MarkerType.ArrowClosed, color: '#3b82f6' },
    style: { stroke: '#3b82f6', strokeWidth: 2, strokeDasharray: '5,5' }
  },
  {
    id: 'e-fk-doc-sem',
    source: 'doc_extract', sourceHandle: 'id',
    target: 'semantic_intelligence', targetHandle: 'extraction_id',
    type: 'smoothstep',
    markerEnd: { type: MarkerType.ArrowClosed, color: '#3b82f6' },
    style: { stroke: '#3b82f6', strokeWidth: 2, strokeDasharray: '5,5' }
  },
  {
    id: 'e-fk-std-sem',
    source: 'standard_master', sourceHandle: 'id',
    target: 'semantic_intelligence', targetHandle: 'standard_id',
    type: 'smoothstep',
    markerEnd: { type: MarkerType.ArrowClosed, color: '#3b82f6' },
    style: { stroke: '#3b82f6', strokeWidth: 2 }
  },
  {
    id: 'e-fk-sub-sem',
    source: 'subject_master', sourceHandle: 'id',
    target: 'semantic_intelligence', targetHandle: 'subject_id',
    type: 'smoothstep',
    markerEnd: { type: MarkerType.ArrowClosed, color: '#3b82f6' },
    style: { stroke: '#3b82f6', strokeWidth: 2 }
  },
  {
    id: 'e-fk-curr-unit',
    source: 'lms_curriculum', sourceHandle: 'id',
    target: 'lms_units', targetHandle: 'curriculum_id',
    type: 'smoothstep',
    markerEnd: { type: MarkerType.ArrowClosed, color: '#3b82f6' },
    style: { stroke: '#3b82f6', strokeWidth: 2 }
  },
  {
    id: 'e-fk-curr-outcomes',
    source: 'lms_curriculum', sourceHandle: 'id',
    target: 'lms_learning_outcomes', targetHandle: 'curriculum_id',
    type: 'smoothstep',
    markerEnd: { type: MarkerType.ArrowClosed, color: '#3b82f6' },
    style: { stroke: '#3b82f6', strokeWidth: 2 }
  },
  {
    id: 'e-fk-doc-outcomes',
    source: 'doc_extract', sourceHandle: 'id',
    target: 'lms_learning_outcomes', targetHandle: 'extraction_id',
    type: 'smoothstep',
    markerEnd: { type: MarkerType.ArrowClosed, color: '#3b82f6' },
    style: { stroke: '#3b82f6', strokeWidth: 2, strokeDasharray: '5,5' }
  },
  {
    id: 'e-fk-std-outcomes',
    source: 'standard_master', sourceHandle: 'id',
    target: 'lms_learning_outcomes', targetHandle: 'standard_id',
    type: 'smoothstep',
    markerEnd: { type: MarkerType.ArrowClosed, color: '#3b82f6' },
    style: { stroke: '#3b82f6', strokeWidth: 2 }
  },
  {
    id: 'e-fk-sub-outcomes',
    source: 'subject_master', sourceHandle: 'id',
    target: 'lms_learning_outcomes', targetHandle: 'subject_id',
    type: 'smoothstep',
    markerEnd: { type: MarkerType.ArrowClosed, color: '#3b82f6' },
    style: { stroke: '#3b82f6', strokeWidth: 2 }
  },
  {
    id: 'e-fk-chap-outcomes',
    source: 'chapter_master', sourceHandle: 'id',
    target: 'lms_learning_outcomes', targetHandle: 'chapter_id',
    type: 'smoothstep',
    markerEnd: { type: MarkerType.ArrowClosed, color: '#3b82f6' },
    style: { stroke: '#3b82f6', strokeWidth: 2 }
  },
  {
    id: 'e-fk-unit-chap',
    source: 'lms_units', sourceHandle: 'id',
    target: 'chapter_master', targetHandle: 'unit_id',
    type: 'smoothstep',
    markerEnd: { type: MarkerType.ArrowClosed, color: '#3b82f6' },
    style: { stroke: '#3b82f6', strokeWidth: 2 }
  },
  {
    id: 'e-fk-chap-sem',
    source: 'chapter_master', sourceHandle: 'id',
    target: 'semantic_intelligence', targetHandle: 'chapter_id',
    type: 'smoothstep',
    markerEnd: { type: MarkerType.ArrowClosed, color: '#3b82f6' },
    style: { stroke: '#3b82f6', strokeWidth: 2 }
  },
  {
    id: 'e-fk-doc-concept',
    source: 'doc_extract', sourceHandle: 'id',
    target: 'lms_concept', targetHandle: 'extraction_id',
    type: 'smoothstep',
    markerEnd: { type: MarkerType.ArrowClosed, color: '#3b82f6' },
    style: { stroke: '#3b82f6', strokeWidth: 2, strokeDasharray: '5,5' }
  },
  {
    id: 'e-fk-std-concept',
    source: 'standard_master', sourceHandle: 'id',
    target: 'lms_concept', targetHandle: 'standard_id',
    type: 'smoothstep',
    markerEnd: { type: MarkerType.ArrowClosed, color: '#3b82f6' },
    style: { stroke: '#3b82f6', strokeWidth: 2 }
  },
  {
    id: 'e-fk-sub-concept',
    source: 'subject_master', sourceHandle: 'id',
    target: 'lms_concept', targetHandle: 'subject_id',
    type: 'smoothstep',
    markerEnd: { type: MarkerType.ArrowClosed, color: '#3b82f6' },
    style: { stroke: '#3b82f6', strokeWidth: 2 }
  },
  {
    id: 'e-fk-chap-concept',
    source: 'chapter_master', sourceHandle: 'id',
    target: 'lms_concept', targetHandle: 'chapter_id',
    type: 'smoothstep',
    markerEnd: { type: MarkerType.ArrowClosed, color: '#3b82f6' },
    style: { stroke: '#3b82f6', strokeWidth: 2 }
  },
];

const nodeTypes = {
  tableNode: TableNode,
  llmNode: LLMNode,
};

export function SchemaVisualizer() {
  const [nodes, setNodes, onNodesChange] = useNodesState(initialNodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState(initialEdges);
  const [hoveredNodeId, setHoveredNodeId] = React.useState<string | null>(null);

  // Sync hoveredNodeId down to all nodes' data objects
  const nodesWithHoverState = useMemo(() => {
    return nodes.map((n) => ({
      ...n,
      data: { ...n.data, hoveredNodeId },
      zIndex: hoveredNodeId === n.id ? 1000 : 0,
    }));
  }, [nodes, hoveredNodeId]);

  // Sync edges to dim when a node is hovered, unless it's connected
  const edgesWithHoverState = useMemo(() => {
    return edges.map((e) => {
      const isConnectedToHovered = hoveredNodeId === e.source || hoveredNodeId === e.target;
      const shouldDim = hoveredNodeId !== null && !isConnectedToHovered;
      const shouldHighlight = hoveredNodeId !== null && isConnectedToHovered;
      
      return {
        ...e,
        style: {
          ...e.style,
          strokeOpacity: shouldDim ? 0.1 : 1,
          strokeWidth: shouldHighlight ? Number(e.style?.strokeWidth || 2) + 1 : e.style?.strokeWidth,
        },
        animated: shouldHighlight ? true : (e.animated === true),
      };
    });
  }, [edges, hoveredNodeId]);

  const onNodeMouseEnter = useCallback((_: React.MouseEvent, node: any) => {
    setHoveredNodeId(node.id);
  }, []);

  const onNodeMouseLeave = useCallback(() => {
    setHoveredNodeId(null);
  }, []);

  return (
    <div className="flex-1 w-full h-full rounded-[2rem] border-[0.5px] border-black/10 dark:border-white/20 bg-white/40 dark:bg-black/40 backdrop-blur-[40px] saturate-200 shadow-[0_8px_32px_0_rgba(0,0,0,0.1)] relative overflow-hidden flex flex-col">
      <div style={{ width: "100%", height: "100%" }}>
        <ReactFlow
          nodes={nodesWithHoverState}
          edges={edgesWithHoverState}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          onNodeMouseEnter={onNodeMouseEnter}
          onNodeMouseLeave={onNodeMouseLeave}
          nodeTypes={nodeTypes}
          fitView
          fitViewOptions={{ padding: 0.2 }}
          minZoom={0.05}
          maxZoom={4}
          proOptions={{ hideAttribution: true }}
          className="bg-transparent transition-all duration-500"
        >
          <Background variant={BackgroundVariant.Dots} gap={24} size={2} className="opacity-40" />
          <Controls position="top-right" showInteractive={true} showZoom={true} showFitView={true} className="bg-white dark:bg-black backdrop-blur-md border border-black/10 dark:border-white/10 rounded-xl overflow-hidden shadow-lg p-1" />
          <MiniMap zoomable pannable className="bg-white/90 dark:bg-black/90 backdrop-blur-md border border-black/10 dark:border-white/10 rounded-xl shadow-lg mb-[100px] sm:mb-0" maskColor="rgba(0,0,0,0.1)" />
          
          <Panel position="bottom-left" className="bg-white/90 dark:bg-black/90 backdrop-blur-md border border-black/10 dark:border-white/10 rounded-xl shadow-lg p-4 m-4 max-w-[280px]">
            <div className="flex flex-col gap-3">
              <h4 className="font-bold text-sm border-b border-black/10 dark:border-white/10 pb-2">Graph Legend</h4>
              
              <div className="flex items-center gap-3">
                 <div className="w-8 h-[2px] bg-purple-500 rounded flex-shrink-0"></div>
                 <span className="text-xs font-medium text-muted-foreground leading-tight">AI Input Flow (Raw Content)</span>
              </div>
          
              <div className="flex items-center gap-3">
                 <div className="w-8 h-[2px] bg-emerald-500 rounded flex-shrink-0"></div>
                 <span className="text-xs font-medium text-muted-foreground leading-tight">AI Output (JSON to Database)</span>
              </div>
          
              <div className="flex items-center gap-3">
                 <div className="w-8 h-[2px] bg-blue-500 rounded flex-shrink-0"></div>
                 <span className="text-xs font-medium text-muted-foreground leading-tight">Foreign Key Relationship</span>
              </div>
          
              <div className="flex items-center gap-3">
                 <div className="w-8 border-b-[2px] border-dashed border-blue-500 flex-shrink-0"></div>
                 <span className="text-xs font-medium text-muted-foreground leading-tight">Global Extraction ID Tracking</span>
              </div>
          
              <div className="flex items-center gap-3 mt-1">
                 <Key className="h-4 w-4 text-amber-500 flex-shrink-0" />
                 <span className="text-xs font-medium text-muted-foreground">Primary Key (Unique ID)</span>
              </div>
              
              <div className="flex items-center gap-3">
                 <Link className="h-4 w-4 text-blue-500 flex-shrink-0" />
                 <span className="text-xs font-medium text-muted-foreground">Foreign Key (Reference)</span>
              </div>
            </div>
          </Panel>
        </ReactFlow>
      </div>
    </div>
  );
}
