import json
import logging
from typing import Any, Dict, List
from sqlalchemy import text
from app.db.mariadb import SessionLocal
from app.semantic_intelligence.router import _two_pass_extraction
from app.semantic_intelligence.gemini_client import _get_model

logger = logging.getLogger(__name__)

def get_all_semantic_chapters() -> List[Dict[str, Any]]:
    with SessionLocal() as db:
        query = text("""
            SELECT d.id, d.document_tittle, d.subject_name, d.standard, d.syear, d.chapter_number, d.created_at,
                   EXISTS(SELECT 1 FROM semantic_intelligence s WHERE s.extraction_id = d.id) as is_processed
            FROM document_extractions d
            WHERE LOWER(d.document_type) = 'chapter'
            ORDER BY d.id DESC
        """)
        rows = db.execute(query).mappings().fetchall()
        return [dict(r) for r in rows]

async def process_semantic_chapter_by_id(extraction_id: int) -> Dict[str, Any]:
    with SessionLocal() as db:
        row = db.execute(
            text("SELECT * FROM document_extractions WHERE id = :id"), 
            {"id": extraction_id}
        ).mappings().fetchone()
        
        if not row:
            raise ValueError(f"No document_extraction found for id {extraction_id}")
            
        md_content = row.get("md_content", "")
        if not md_content:
            raise ValueError(f"document_extraction {extraction_id} has no md_content")
            
        subject = str(row.get("subject_name", "Science"))
        class_level = str(row.get("standard", "10"))
        
        # 1. Run the two-pass extraction logic
        assembled_json, total_input_tokens, total_output_tokens = await _two_pass_extraction(
            markdown_content=md_content,
            subject=subject,
            class_level=class_level
        )
        
        from app.semantic_intelligence.parser import validate_semantic_intelligence_output, calculate_quality_flag
        try:
            validated = validate_semantic_intelligence_output(assembled_json)
            quality_flag = calculate_quality_flag(validated)
        except Exception as e:
            logger.error(f"Validation failed for extraction {extraction_id}: {e}")
            quality_flag = "regenerate"
            
        # 2. Extract values for table
        learning_objective = assembled_json.get("learning_objectives", "")
        teaching_units = assembled_json.get("teaching_units", [])
        total_topics = len(teaching_units)
        full_json_str = json.dumps(assembled_json)
        llm_model = "gemini-1.5-flash" # the default used
        
        # 3. Find matching chapter_id from chapter_master
        chapter_row = db.execute(
            text("SELECT id FROM chapter_master WHERE extraction_id = :id"),
            {"id": extraction_id}
        ).fetchone()
        chapter_id = chapter_row[0] if chapter_row else None
        
        # 4. Insert or update in semantic_intelligence table
        existing = db.execute(
            text("SELECT id FROM semantic_intelligence WHERE extraction_id = :id"),
            {"id": extraction_id}
        ).fetchone()
        
        params = {
            "ext_id": extraction_id,
            "std_id": row.get("standard_id"),
            "sub_id": row.get("subject_id"),
            "ch_id": chapter_id,
            "sub_name": row.get("subject_name"),
            "std": row.get("standard"),
            "ch_num": row.get("chapter_number"),
            "lo": learning_objective,
            "topics": total_topics,
            "full_json": full_json_str,
            "model": llm_model,
            "in_tok": total_input_tokens,
            "out_tok": total_output_tokens,
            "qf": quality_flag
        }
        
        if existing:
            db.execute(text("""
                UPDATE semantic_intelligence
                SET standard_id=:std_id, subject_id=:sub_id, chapter_id=:ch_id,
                    subject_name=:sub_name, standard=:std, chapter_number=:ch_num,
                    learning_objective=:lo, total_topics=:topics, full_intelegance_json=:full_json,
                    llm_model=:model, input_token=:in_tok, output_token=:out_tok, qulity_flag=:qf,
                    updated_at=CURRENT_TIMESTAMP
                WHERE id=:id
            """), {**params, "id": existing[0]})
            action = "updated"
            record_id = existing[0]
        else:
            res = db.execute(text("""
                INSERT INTO semantic_intelligence
                (extraction_id, standard_id, subject_id, chapter_id, subject_name, standard, chapter_number,
                 learning_objective, total_topics, full_intelegance_json, llm_model, input_token, output_token, qulity_flag)
                VALUES
                (:ext_id, :std_id, :sub_id, :ch_id, :sub_name, :std, :ch_num,
                 :lo, :topics, :full_json, :model, :in_tok, :out_tok, :qf)
            """), params)
            action = "inserted"
            record_id = res.lastrowid
            
        db.commit()
        
        # Return the data to populate frontend state immediately
        return {
            "status": "success",
            "action": action,
            "semantic_id": record_id,
            "semantic_data": {
                "subject_name": params["sub_name"],
                "standard": params["std"],
                "total_topics": params["topics"],
                "qulity_flag": params["qf"],
                "input_token": params["in_tok"],
                "output_token": params["out_tok"]
            }
        }

def get_semantic_data_by_extraction_id(extraction_id: int):
    with SessionLocal() as db:
        res = db.execute(
            text("SELECT * FROM semantic_intelligence WHERE extraction_id = :id"),
            {"id": extraction_id}
        ).mappings().fetchone()
        
        if not res:
            return None
            
        data = dict(res)
        if isinstance(data.get("full_intelegance_json"), str):
            try:
                data["full_intelegance_json"] = json.loads(data["full_intelegance_json"])
            except:
                pass
        return data
