import json
import logging
from typing import Any, Dict, List
from sqlalchemy import text
from app.db.mariadb import SessionLocal
from app.utils.config import settings

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
    # 1. Fetch all necessary data
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
        
        # 2. Find matching chapter_id from chapter_master to get key_concepts
        chapter_row = db.execute(
            text("SELECT id, key_concepts FROM chapter_master WHERE extraction_id = :id"),
            {"id": extraction_id}
        ).fetchone()
        
        chapter_id = chapter_row[0] if chapter_row else None
        key_concepts = chapter_row[1] if chapter_row and chapter_row[1] else "No predefined key concepts."
        
        # Save local copies of row fields so we don't need the DB connection
        standard_id = row.get("standard_id")
        subject_id = row.get("subject_id")
        subject_name = row.get("subject_name")
        standard = row.get("standard")
        chapter_number = row.get("chapter_number")
        document_tittle = str(row.get("document_tittle", subject + " Chapter"))
        
    # 3. Run the NEW Swarm Pipeline logic (OUTSIDE THE DB SESSION!)
    from app.semantic_intelligence.pipeline import generate_chapter_intelligence
    chapter_name = document_tittle
    assembled_json = await generate_chapter_intelligence(
        chapter_name=chapter_name,
        raw_markdown=md_content,
        key_concepts=key_concepts
    )
    
    # We now track tokens accurately through the swarm and pipeline!
    total_input_tokens = assembled_json.get("total_input_tokens", 0)
    total_output_tokens = assembled_json.get("total_output_tokens", 0)
    
    # In the new schema we don't have teaching_units, we have topics
    topics_list = assembled_json.get("topics", [])
    
    all_lo = []
    for topic in topics_list:
        for concept in topic.get("concepts", []):
            for lo in concept.get("learning_objectives", []):
                obj_text = lo.get("objective", "")
                if obj_text:
                    all_lo.append(obj_text)
                    
    learning_objective = "\n".join(all_lo) if all_lo else ""
    
    total_topics = len(topics_list)
    full_json_str = json.dumps(assembled_json)
    llm_model = settings.deepseek_model
    
    # Set quality flag to good for now since pydantic enforces schema
    quality_flag = "good"
    
    # 4. Insert or update in semantic_intelligence table
    with SessionLocal() as db:
        existing = db.execute(
            text("SELECT id FROM semantic_intelligence WHERE extraction_id = :id"),
            {"id": extraction_id}
        ).fetchone()
        
        params = {
            "ext_id": extraction_id,
            "std_id": standard_id,
            "sub_id": subject_id,
            "ch_id": chapter_id,
            "sub_name": subject_name,
            "std": standard,
            "ch_num": chapter_number,
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
