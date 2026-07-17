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

async def process_semantic_chapter_by_id(extraction_id: int, force: bool = False) -> Dict[str, Any]:
    # 1. Fetch all necessary data
    with SessionLocal() as db:
        row = db.execute(
            text("SELECT * FROM document_extractions WHERE id = :id"), 
            {"id": extraction_id}
        ).mappings().fetchone()
        
        if not row:
            raise ValueError(f"No document_extraction found for id {extraction_id}")
            
        # 0. Check if already processed to save tokens
        existing_semantic = db.execute(
            text("SELECT id FROM semantic_intelligence WHERE extraction_id = :id LIMIT 1"),
            {"id": extraction_id}
        ).fetchone()
        
        if existing_semantic and not force:
            return {
                "status": "already_processed",
                "action": "skipped",
                "message": "Semantic Intelligence already processed. Skipped to save LLM tokens.",
                "data": get_semantic_data_by_extraction_id(extraction_id)
            }
            
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
        
        # 2b. Find the official curriculum learning outcomes for this standard and subject
        curr_row = db.execute(
            text("SELECT id FROM lms_curriculum WHERE standard_id = :st_id AND subject_id = :sub_id ORDER BY id DESC LIMIT 1"),
            {"st_id": standard_id, "sub_id": subject_id}
        ).fetchone()
        
        official_outcomes_str = "No official curriculum outcomes available for this subject."
        if curr_row:
            outcomes = db.execute(
                text("SELECT code, description FROM lms_learning_outcomes WHERE curriculum_id = :cid"),
                {"cid": curr_row[0]}
            ).fetchall()
            if outcomes:
                official_outcomes_str = "\n".join([f"- [{o[0]}] {o[1]}" for o in outcomes])
        
    # 3. Run the NEW Swarm Pipeline logic (OUTSIDE THE DB SESSION!)
    from app.semantic_intelligence.pipeline import generate_chapter_intelligence
    chapter_name = document_tittle
    assembled_json = await generate_chapter_intelligence(
        chapter_name=chapter_name,
        raw_markdown=md_content,
        key_concepts=key_concepts,
        official_outcomes=official_outcomes_str
    )
    
    # We now track tokens accurately through the swarm and pipeline!
    total_input_tokens = assembled_json.get("total_input_tokens", 0)
    total_output_tokens = assembled_json.get("total_output_tokens", 0)
    
    # In the new schema we don't have topics, we have concepts directly at root
    concepts_list = assembled_json.get("concepts", [])
    
    all_lo = []
    
    # Initialize aggregated lists for the 13 columns
    agg_knowledge = []
    agg_ability = []
    agg_skill = []
    agg_competency = []
    agg_blooms = []
    agg_dok = []
    agg_prereqs = []
    agg_misconceptions = []
    agg_rwa = []
    agg_pedagogy = []
    agg_lo = []
    agg_outcomes = []
    agg_blueprint = []
    
    for concept_wrapper in concepts_list:
        concept_meta = concept_wrapper.get("concept", {})
        concept_name = concept_meta.get("concept_name", "Unknown Concept")
        
        def inject_meta(items, parent_key="concept_name"):
            """Tag each item with its parent concept name.
            Use parent_key to control which field gets the parent concept name.
            For prerequisites, we use '_parent_concept' to avoid overwriting
            the prerequisite's own 'concept_name' field."""
            if not isinstance(items, list): return items
            for item in items:
                if isinstance(item, dict):
                    item[parent_key] = concept_name
            return items

        agg_knowledge.extend(inject_meta(concept_wrapper.get("knowledge_items", [])))
        agg_ability.extend(inject_meta(concept_wrapper.get("abilities", [])))
        agg_skill.extend(inject_meta(concept_wrapper.get("skills", [])))
        agg_competency.extend(inject_meta(concept_wrapper.get("competencies", [])))
        agg_blooms.extend(inject_meta(concept_wrapper.get("blooms", [])))
        agg_dok.extend(inject_meta(concept_wrapper.get("dok", [])))
        # CRITICAL: Prerequisites have their OWN concept_name field (the prerequisite name).
        # We must NOT overwrite it. Tag with '_parent_concept' instead.
        agg_prereqs.extend(inject_meta(concept_wrapper.get("prerequisites", []), parent_key="_parent_concept"))
        agg_misconceptions.extend(inject_meta(concept_wrapper.get("misconceptions", [])))
        agg_rwa.extend(inject_meta(concept_wrapper.get("real_world_applications", [])))
        agg_pedagogy.extend(inject_meta(concept_wrapper.get("pedagogy_recommendations", [])))
        agg_lo.extend(inject_meta(concept_wrapper.get("learning_objectives", [])))
        agg_outcomes.extend(inject_meta(concept_wrapper.get("learning_outcomes", [])))
        agg_blueprint.extend(inject_meta(concept_wrapper.get("assessment_blueprint", [])))
        
        for lo in concept_wrapper.get("learning_objectives", []):
            obj_text = lo.get("objective", "")
            if obj_text:
                all_lo.append(obj_text)
                    
    learning_objective = "\n".join(all_lo) if all_lo else ""
    
    total_topics = len(concepts_list) # Still mapping to total_topics column
    full_json_str = json.dumps(assembled_json, ensure_ascii=False)
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
            "qf": quality_flag,
            "knowledge": json.dumps(agg_knowledge, ensure_ascii=False),
            "ability": json.dumps(agg_ability, ensure_ascii=False),
            "skill": json.dumps(agg_skill, ensure_ascii=False),
            "competency": json.dumps(agg_competency, ensure_ascii=False),
            "blooms_level": json.dumps(agg_blooms, ensure_ascii=False),
            "dok": json.dumps(agg_dok, ensure_ascii=False),
            "prerequisites": json.dumps(agg_prereqs, ensure_ascii=False),
            "misconceptions": json.dumps(agg_misconceptions, ensure_ascii=False),
            "real_world_applications": json.dumps(agg_rwa, ensure_ascii=False),
            "pedagogy": json.dumps(agg_pedagogy, ensure_ascii=False),
            "learning_objectives": json.dumps(agg_lo, ensure_ascii=False),
            "learning_outcomes": json.dumps(agg_outcomes, ensure_ascii=False),
            "assessment_blueprint": json.dumps(agg_blueprint, ensure_ascii=False)
        }
        
        if existing:
            db.execute(text("""
                UPDATE semantic_intelligence
                SET standard_id=:std_id, subject_id=:sub_id, chapter_id=:ch_id,
                    subject_name=:sub_name, standard=:std, chapter_number=:ch_num,
                    learning_objective=:lo, total_concepts=:topics, full_intelegance_json=:full_json,
                    llm_model=:model, input_token=:in_tok, output_token=:out_tok, qulity_flag=:qf,
                    knowledge=:knowledge, ability=:ability, skill=:skill, competency=:competency,
                    blooms_level=:blooms_level, dok=:dok, prerequisites=:prerequisites,
                    misconceptions=:misconceptions, real_world_applications=:real_world_applications,
                    pedagogy=:pedagogy, learning_objectives=:learning_objectives,
                    learning_outcomes=:learning_outcomes, assessment_blueprint=:assessment_blueprint,
                    sub_institute_id=1, updated_at=CURRENT_TIMESTAMP
                WHERE id=:id
            """), {**params, "id": existing[0]})
            action = "updated"
            record_id = existing[0]
        else:
            res = db.execute(text("""
                INSERT INTO semantic_intelligence
                (extraction_id, sub_institute_id, standard_id, subject_id, chapter_id, subject_name, standard, chapter_number,
                 learning_objective, total_concepts, full_intelegance_json, llm_model, input_token, output_token, qulity_flag,
                 knowledge, ability, skill, competency, blooms_level, dok, prerequisites, misconceptions,
                 real_world_applications, pedagogy, learning_objectives, learning_outcomes, assessment_blueprint)
                VALUES
                (:ext_id, 1, :std_id, :sub_id, :ch_id, :sub_name, :std, :ch_num,
                 :lo, :topics, :full_json, :model, :in_tok, :out_tok, :qf,
                 :knowledge, :ability, :skill, :competency, :blooms_level, :dok, :prerequisites, :misconceptions,
                 :real_world_applications, :pedagogy, :learning_objectives, :learning_outcomes, :assessment_blueprint)
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
            text("""
                SELECT s.*, d.md_content 
                FROM semantic_intelligence s
                LEFT JOIN document_extractions d ON s.extraction_id = d.id
                WHERE s.extraction_id = :id
            """),
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
