import json
import logging
from typing import Any, Dict
from sqlalchemy import text
from app.db.mariadb import SessionLocal
from app.semantic_intelligence.deepseek_client import call_deepseek

logger = logging.getLogger(__name__)

CHAPTER_PROMPT = """You are an expert educational content analyst specializing in Indian school curriculum (NCERT and state boards) for standards 1 to 12, across all subjects including Hindi, Gujarati, English, Sanskrit, Mathematics, Science, Social Science, History, Geography, Civics, Biology, Chemistry, Physics, Computer Science, and any other subject.

Your task is to extract key concepts from a given chapter's content and return ONLY a valid JSON object — no explanation, no markdown, no preamble, no trailing text.

Rules you must follow:
1. Extract key concepts that are educationally significant for that standard and subject.
2. Adapt depth and complexity based on the standard level:
   - Std 1–5 (Primary): simple terms, basic ideas, foundational vocabulary
   - Std 6–8 (Middle): definitions, processes, relationships between ideas
   - Std 9–10 (Secondary): principles, laws, theories, formulas, cause-effect
   - Std 11–12 (Higher Secondary): advanced theories, derivations, analytical concepts
3. For language subjects (Hindi, Gujarati, English, Sanskrit, etc.), extract grammar topics, literary devices, author/poet concepts, and vocabulary themes.
4. For Mathematics, include formulas, theorems, and problem-solving techniques.
5. For Sciences, include laws, definitions, diagrams/processes mentioned, and chemical/biological terms.
6. CRITICAL INSTRUCTION: ALL extracted text (Concept Names AND Descriptions) MUST strictly remain in the ORIGINAL script/language (e.g., Sanskrit, Hindi, Gujarati, Marathi) found in the chapter content. DO NOT translate any text into English. Only the JSON keys must be in English.
7. Keep each concept name concise (2–6 words). The description should be 1–2 sentences max.
8. Extract between 5 and 20 key concepts depending on chapter length and complexity.
9. Output ONLY the JSON object. No other text.
10. If `Available Units` are provided below, analyze the semantic similarity between the `Chapter Name` / `Chapter Content` and the unit chapters/themes. Return the integer ID of the best matching unit in the `mapped_unit_id` field. If no matching unit is found or the list is empty, return null for `mapped_unit_id`.

Return the JSON in the following format:
{
  "mapped_unit_id": 123,
  "key_concepts": [
    {
      "name": "Concept Name",
      "description": "Concept Description"
    }
  ]
}

Chapter Name: {chapter_name}

Available Units:
{available_units}

Chapter Content:
{md_content}
"""

def process_chapter_by_id(extraction_id: int, force: bool = False) -> Dict[str, Any]:
    with SessionLocal() as db:
        # 1. Fetch the document extraction row
        row = db.execute(
            text("SELECT * FROM document_extractions WHERE id = :id"), 
            {"id": extraction_id}
        ).mappings().fetchone()
        
        if not row:
            raise ValueError(f"No document_extraction found for id {extraction_id}")
            
        # 0. Check if already processed to save tokens and preserve downstream integrity
        existing_chapter = db.execute(
            text("SELECT id FROM chapter_master WHERE extraction_id = :id LIMIT 1"), 
            {"id": extraction_id}
        ).fetchone()
        
        if existing_chapter and not force:
            return {
                "status": "already_processed", 
                "action": "skipped",
                "chapter_master_id": existing_chapter[0],
                "message": "Chapter already processed. Skipped to save LLM tokens and preserve downstream semantic data.",
                "chapter_data": get_chapter_data_by_extraction_id(extraction_id)
            }
            
        if str(row.get("document_type", "")).lower() != "chapter":
            raise ValueError(f"document_extraction {extraction_id} is not of type 'Chapter'")
            
        chapter_name = row.get("document_tittle", "")
        md_content = row.get("md_content", "")
        if not md_content:
            raise ValueError(f"document_extraction {extraction_id} has no md_content")
            
        std_id = row.get("standard_id")
        sub_id = row.get("subject_id")
        
        available_units_list = []
        units = []
        if std_id and sub_id:
            # Find curriculums matching the same standard and subject (or similar subject name)
            curriculums = db.execute(
                text("""
                    SELECT c.id 
                    FROM lms_curriculum c
                    LEFT JOIN subject cs ON c.subject_id = cs.id
                    LEFT JOIN subject ds ON ds.id = :sub_id
                    WHERE c.standard_id = :std_id 
                    AND (
                        c.subject_id = :sub_id 
                        OR LOWER(ds.subject_name) LIKE CONCAT(LOWER(cs.subject_name), '%')
                        OR LOWER(cs.subject_name) LIKE CONCAT(LOWER(ds.subject_name), '%')
                    )
                """), 
                {"std_id": std_id, "sub_id": sub_id}
            ).fetchall()
            
            if curriculums:
                curr_ids = [c[0] for c in curriculums]
                in_clause = ",".join(map(str, curr_ids))
                units = db.execute(
                    text(f"SELECT id, name, unit_chapters FROM lms_units WHERE curriculum_id IN ({in_clause})")
                ).mappings().fetchall()
                
                for u in units:
                    try:
                        u_chapters_str = u["unit_chapters"]
                        chapters_list = json.loads(u_chapters_str) if u_chapters_str else []
                        available_units_list.append({
                            "unit_id": u["id"],
                            "unit_name": u["name"],
                            "chapters_in_this_unit": chapters_list
                        })
                    except Exception as e:
                        logger.warning(f"Failed to parse unit_chapters for unit_id {u['id']}: {e}")
                        
        available_units_str = json.dumps(available_units_list, indent=2) if available_units_list else "[]"

        # 2. Call DeepSeek LLM to extract key concepts and map unit
        prompt = CHAPTER_PROMPT.replace("{md_content}", md_content).replace("{available_units}", available_units_str).replace("{chapter_name}", chapter_name)
        system_prompt = "You are a helpful assistant. Return ONLY a JSON object."
        deepseek_response = call_deepseek(prompt, system_prompt=system_prompt, response_format={"type": "json_object"})
        parsed_data = deepseek_response
        
        # Ensure we have the right structure
        data_dict = parsed_data.get("data", parsed_data)
        key_concepts = data_dict.get("key_concepts", [])
        key_concepts_json = json.dumps(key_concepts, ensure_ascii=False)
        
        # 3. Map unit_id
        unit_id = data_dict.get("mapped_unit_id")
        
        # fallback to simple string matching if DeepSeek fails
        if not unit_id and units:
            for u in units:
                try:
                    u_chapters_str = u["unit_chapters"]
                    if not u_chapters_str:
                        continue
                    chapters_list = json.loads(u_chapters_str)
                    if any(chapter_name.lower() in str(c).lower() or str(c).lower() in chapter_name.lower() for c in chapters_list):
                        unit_id = u["id"]
                        break
                except Exception:
                    pass
                        
        # 4. Fetch grade_id from standard table
        grade_id = None
        if std_id:
            grade_row = db.execute(text("SELECT grade_id FROM standard WHERE id = :st_id"), {"st_id": std_id}).fetchone()
            if grade_row:
                grade_id = grade_row[0]

        # 5. Insert or Update chapter_master
        existing = db.execute(
            text("SELECT id FROM chapter_master WHERE extraction_id = :id LIMIT 1"), 
            {"id": extraction_id}
        ).fetchone()
        
        if not existing:
            # Attempt to match an existing ERP chapter record before inserting a duplicate
            existing = db.execute(
                text("""SELECT id FROM chapter_master 
                        WHERE LOWER(TRIM(chapter_name)) = LOWER(TRIM(:cname)) 
                        AND standard_id = :std_id 
                        AND subject_id = :sub_id 
                        AND sub_institute_id = :sub_inst 
                        ORDER BY id ASC LIMIT 1"""),
                {
                    "cname": chapter_name,
                    "std_id": row.get("standard_id"),
                    "sub_id": row.get("subject_id"),
                    "sub_inst": row.get("sub_institute_id")
                }
            ).fetchone()

        if existing:
            chapter_master_id = existing[0]
            db.execute(text("""
                UPDATE chapter_master SET 
                    extraction_id = :ext_id,
                    sub_institute_id = :sub_inst,
                    subject_id = :sub_id,
                    standard_id = :std_id,
                    grade_id = :grade_id,
                    unit_id = :unit_id,
                    chapter_name = :cname,
                    key_concepts = :kconcepts,
                    syear = :syear,
                    updated_at = NOW()
                WHERE id = :cm_id
            """), {
                "ext_id": extraction_id,
                "sub_inst": row.get("sub_institute_id"),
                "sub_id": row.get("subject_id"),
                "std_id": row.get("standard_id"),
                "grade_id": grade_id,
                "unit_id": unit_id,
                "cname": chapter_name,
                "kconcepts": key_concepts_json,
                "syear": row.get("syear"),
                "cm_id": chapter_master_id
            })
            db.commit()
            return {
                "status": "success", 
                "action": "updated", 
                "chapter_master_id": chapter_master_id, 
                "unit_id_mapped": unit_id,
                "key_concepts_extracted": len(key_concepts),
                "chapter_data": get_chapter_data_by_extraction_id(extraction_id)
            }
        else:
            res = db.execute(text("""
                INSERT INTO chapter_master 
                (extraction_id, sub_institute_id, subject_id, standard_id, grade_id, unit_id, chapter_name, key_concepts, syear, created_at, updated_at)
                VALUES 
                (:ext_id, :sub_inst, :sub_id, :std_id, :grade_id, :unit_id, :cname, :kconcepts, :syear, NOW(), NOW())
            """), {
                "ext_id": extraction_id,
                "sub_inst": row.get("sub_institute_id"),
                "sub_id": row.get("subject_id"),
                "std_id": row.get("standard_id"),
                "grade_id": grade_id,
                "unit_id": unit_id,
                "cname": chapter_name,
                "kconcepts": key_concepts_json,
                "syear": row.get("syear")
            })
            db.commit()
            return {
                "status": "success", 
                "action": "inserted", 
                "chapter_master_id": res.lastrowid, 
                "unit_id_mapped": unit_id,
                "key_concepts_extracted": len(key_concepts),
                "chapter_data": get_chapter_data_by_extraction_id(extraction_id)
            }

def get_chapter_data_by_extraction_id(extraction_id: int):
    with SessionLocal() as db:
        chp = db.execute(
            text("SELECT * FROM chapter_master WHERE extraction_id = :id"), 
            {"id": extraction_id}
        ).mappings().fetchone()
        
        if not chp:
            return None
            
        unit_name = None
        if chp.get("unit_id"):
            u = db.execute(text("SELECT name FROM lms_units WHERE id = :uid"), {"uid": chp["unit_id"]}).mappings().fetchone()
            if u:
                unit_name = u["name"]
                
        # Parse key_concepts back to JSON for frontend
        concepts = []
        try:
            if chp.get("key_concepts"):
                concepts = json.loads(chp["key_concepts"])
        except:
            pass
            
        return {
            "chapter_master_id": chp["id"],
            "unit_id": chp["unit_id"],
            "unit_name": unit_name,
            "chapter_name": chp["chapter_name"],
            "syear": chp["syear"],
            "key_concepts": concepts
        }

def get_all_chapters() -> list[dict[str, Any]]:
    with SessionLocal() as db:
        query = text("""
            SELECT d.id, d.document_tittle, d.subject_name, d.standard, d.syear, d.chapter_number, d.created_at,
                   EXISTS(SELECT 1 FROM chapter_master c WHERE c.extraction_id = d.id) as is_processed
            FROM document_extractions d
            WHERE LOWER(d.document_type) = 'chapter'
            ORDER BY d.id DESC
        """)
        rows = db.execute(query).mappings().fetchall()
        return [dict(row) for row in rows]
