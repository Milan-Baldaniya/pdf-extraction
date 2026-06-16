import json
import logging
from typing import Any, Dict
from sqlalchemy import text
from app.db.mariadb import SessionLocal
from app.semantic_intelligence.deepseek_client import call_deepseek

logger = logging.getLogger(__name__)

CONCEPT_PROMPT = """You are an expert instructional designer and educational content analyst.
Your task is to analyze a list of key concepts for a chapter alongside the chapter's markdown content, and determine highly accurate, scientifically-backed mastery thresholds and estimated learning times for each concept. This data will be used directly for teacher and student training in schools, so precision and pedagogical methodology are critical.

Rules you must follow:
1. You will be provided with a JSON array of `key_concepts` (containing `name` and `description`) and the full `md_content` of the chapter.
2. For every concept in the `key_concepts` array, you must assign a `mastery_threshold` (integer percentage) using this strict pedagogical rubric:
   - 90 to 95: Foundational & Prerequisite concepts (Crucial for future learning; e.g., basic formulas, core definitions).
   - 80 to 85: Core/Standard concepts (Main syllabus topics; Application of knowledge).
   - 70 to 75: Advanced/Enrichment concepts (High-level synthesis, complex analysis, or abstract theoretical concepts where perfection is rare).
3. Assign `estimated_mastery_minutes` (integer) using Cognitive Load Theory & Bloom's Taxonomy:
   - 10 to 15 mins: Low Cognitive Load (Remembering, Identifying, Memorizing definitions/facts).
   - 20 to 30 mins: Medium Cognitive Load (Understanding, Applying, Solving basic problems, Explaining processes).
   - 45 to 60+ mins: High Cognitive Load (Analyzing, Evaluating, Derivations, Complex multi-step problem solving, Abstract reasoning).
4. Return ONLY a JSON object containing a `concepts` array.
5. Each object in the `concepts` array must have: `name`, `description`, `mastery_threshold`, and `estimated_mastery_minutes`.
6. Do not omit any concepts from the input list. The output array must contain exactly the same concepts.

Return the JSON in the following format:
{
  "concepts": [
    {
      "name": "Concept Name",
      "description": "Concept Description",
      "mastery_threshold": 80,
      "estimated_mastery_minutes": 45
    }
  ]
}

Key Concepts:
{key_concepts}

Chapter Content:
{md_content}
"""

def process_concept_by_id(extraction_id: int, force: bool = False) -> Dict[str, Any]:
    with SessionLocal() as db:
        # 1. Fetch document_extractions row
        row = db.execute(
            text("SELECT * FROM document_extractions WHERE id = :id"), 
            {"id": extraction_id}
        ).mappings().fetchone()
        
        if not row:
            raise ValueError(f"No document_extraction found for id {extraction_id}")
            
        # 0. Check if already processed to save tokens
        existing_concepts = db.execute(
            text("SELECT id FROM lms_concept WHERE extraction_id = :id LIMIT 1"),
            {"id": extraction_id}
        ).fetchone()
        
        if existing_concepts and not force:
            return {
                "status": "already_processed",
                "action": "skipped",
                "message": "Concepts already processed. Skipped to save LLM tokens.",
                **get_concept_data_by_extraction_id(extraction_id)
            }
            
        md_content = row.get("md_content", "")
        std_id = row.get("standard_id")
        sub_id = row.get("subject_id")
        sub_inst_id = row.get("sub_institute_id")
        syear = row.get("syear")
        
        # 2. Fetch chapter_master row to get key_concepts
        chapter_row = db.execute(
            text("SELECT id, key_concepts FROM chapter_master WHERE extraction_id = :id"),
            {"id": extraction_id}
        ).mappings().fetchone()
        
        if not chapter_row:
            raise ValueError(f"No chapter_master found for extraction_id {extraction_id}. Process the chapter first.")
            
        chapter_id = chapter_row.get("id")
        key_concepts_raw = chapter_row.get("key_concepts", "[]")
        
        # 3. Call DeepSeek LLM
        prompt = CONCEPT_PROMPT.replace("{key_concepts}", key_concepts_raw).replace("{md_content}", md_content)
        system_prompt = "You are a helpful assistant. Return ONLY a JSON object."
        
        deepseek_response = call_deepseek(prompt, system_prompt=system_prompt, response_format={"type": "json_object"})
        
        data_dict = deepseek_response.get("data", deepseek_response)
        concepts = data_dict.get("concepts", [])
        
        # 4. Insert or Update lms_concept table
        # First, clean up old concepts for this extraction_id to prevent duplicates on reprocess
        db.execute(
            text("DELETE FROM lms_concept WHERE extraction_id = :id"),
            {"id": extraction_id}
        )
        db.commit()
        
        insert_concept_sql = text("""
            INSERT INTO lms_concept (
                extraction_id, name, description, standard_id, subject_id, 
                chapter_id, sub_institute_id, mastery_threshold, 
                estimated_mastery_minutes, syear, created_at
            ) VALUES (
                :ext_id, :name, :description, :std_id, :sub_id,
                :chapter_id, :sub_inst, :mastery, :mins, :syear, NOW()
            )
        """)
        
        for c in concepts:
            db.execute(insert_concept_sql, {
                "ext_id": extraction_id,
                "name": c.get("name", ""),
                "description": c.get("description", ""),
                "std_id": std_id,
                "sub_id": sub_id,
                "chapter_id": chapter_id,
                "sub_inst": sub_inst_id,
                "mastery": c.get("mastery_threshold", 80),
                "mins": c.get("estimated_mastery_minutes", 30),
                "syear": syear
            })
            
        db.commit()
        
        # 5. Fetch and return standardized response
        inserted = db.execute(
            text("SELECT * FROM lms_concept WHERE extraction_id = :id ORDER BY id ASC"),
            {"id": extraction_id}
        ).mappings().fetchall()
        
        return {
            "status": "success",
            "extraction_id": extraction_id,
            "chapter_id": chapter_id,
            "concepts_extracted": len(concepts),
            "concepts": [dict(c) for c in inserted]
        }

def get_concept_data_by_extraction_id(extraction_id: int):
    with SessionLocal() as db:
        concepts = db.execute(
            text("SELECT * FROM lms_concept WHERE extraction_id = :id ORDER BY id ASC"),
            {"id": extraction_id}
        ).mappings().fetchall()
        
        if not concepts:
            return None
            
        return {
            "extraction_id": extraction_id,
            "chapter_id": concepts[0].get("chapter_id"),
            "concepts": [dict(c) for c in concepts]
        }

def get_all_concepts_queue():
    with SessionLocal() as db:
        query = text("""
            SELECT d.id, d.document_tittle, d.subject_name, d.standard, d.syear, d.board, d.chapter_number, d.created_at,
                   EXISTS(SELECT 1 FROM lms_concept c WHERE c.extraction_id = d.id) as is_processed,
                   EXISTS(SELECT 1 FROM chapter_master cm WHERE cm.extraction_id = d.id) as has_chapter
            FROM document_extractions d
            WHERE LOWER(d.document_type) = 'chapter'
            ORDER BY d.id DESC
        """)
        rows = db.execute(query).mappings().fetchall()
        return [dict(row) for row in rows]
