import asyncio
import json
import logging
from typing import Any, Dict, List
from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from app.db.mariadb import SessionLocal
from app.utils.config import settings

logger = logging.getLogger(__name__)

# Retries for the post-swarm write, so a brief DB blip does not throw away
# a multi-minute LLM run.
_PERSIST_ATTEMPTS = 4
_PERSIST_BACKOFF_SEC = 3

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

def _topic_plan(db, extraction_id: int) -> List[Dict[str, Any]]:
    """This chapter's topics, each carrying the concepts it teaches.

    Semantic Intelligence analyses the SAME units the extraction hierarchy
    defines. Chapter -> Topics -> Concepts already decided what this chapter
    teaches, so the swarm runs over those topics and returns one intelligence
    object per concept underneath them.

    The shape matters as much as the content. Handing the swarm the flat list
    of leaf concepts made it fire once per concept - 37 times on a six-topic
    chapter - and each firing carries ~9,000 tokens of role prompt and JSON
    schema whatever the slice size. Grouped by topic it fires six times for the
    same 37 concepts.

    Returns [] when the hierarchy has not been generated, so the caller can fall
    back to the chapter-level key_concepts JSON and the original slicer.
    """
    rows = db.execute(
        text("""
            SELECT t.id AS topic_id, t.name AS topic_name, t.description AS topic_description,
                   t.topic_sort_order,
                   c.name AS concept_name, c.description AS concept_description
              FROM topic_master t
         LEFT JOIN lms_concept c ON c.topic_id = t.id
             WHERE t.extraction_id = :id AND COALESCE(t.topic_show_hide, 1) = 1
          ORDER BY t.topic_sort_order ASC, t.id ASC, c.id ASC
        """),
        {"id": extraction_id},
    ).mappings().fetchall()

    plan: List[Dict[str, Any]] = []
    index: Dict[Any, Dict[str, Any]] = {}
    for row in rows:
        topic = index.get(row["topic_id"])
        if topic is None:
            topic = {
                "topic_id": row["topic_id"],
                "topic_name": row["topic_name"],
                "description": (row["topic_description"] or "").strip(),
                "concepts": [],
            }
            index[row["topic_id"]] = topic
            plan.append(topic)
        if row["concept_name"]:
            topic["concepts"].append({
                "name": row["concept_name"],
                "description": (row["concept_description"] or "").strip(),
            })

    # A hierarchy of topics with no concepts under any of them is the Topic
    # Queue having run without the Concept Queue. There is nothing for the
    # agents to key their answers to, so fall back rather than fan out blind.
    return plan if any(t["concepts"] for t in plan) else []


def _outline_text(plan: List[Dict[str, Any]]) -> str:
    """The plan rendered for the slicer fallback, which takes a flat string."""
    blocks: list[str] = []
    for number, topic in enumerate(plan, start=1):
        blocks.append(f"Topic {number}: {topic['topic_name']}")
        for concept in topic["concepts"]:
            desc = concept["description"]
            blocks.append(f"  - {concept['name']}" + (f" - {desc}" if desc else ""))
    return "\n".join(blocks).strip()


async def process_semantic_chapter_by_id(extraction_id: int, force: bool = False) -> Dict[str, Any]:
    # 1. Fetch all necessary data
    with SessionLocal() as db:
        row = db.execute(
            text("SELECT * FROM document_extractions WHERE id = :id"), 
            {"id": extraction_id}
        ).mappings().fetchone()
        
        if not row:
            raise ValueError(f"No document_extraction found for id {extraction_id}")
            
        # 0. Check if already processed to save tokens.
        #    A row whose payload columns are all empty JSON arrays is a failed
        #    run, not a processed chapter. Skipping those would make the failure
        #    permanent: Process & Fill would keep returning the same null data.
        existing_semantic = db.execute(
            text("""
                SELECT id,
                       GREATEST(
                           CHAR_LENGTH(COALESCE(knowledge, '')),
                           CHAR_LENGTH(COALESCE(learning_outcomes, '')),
                           CHAR_LENGTH(COALESCE(assessment_blueprint, ''))
                       ) AS payload_len
                FROM semantic_intelligence WHERE extraction_id = :id LIMIT 1
            """),
            {"id": extraction_id}
        ).fetchone()

        # len(2) is the empty JSON array "[]".
        has_payload = bool(existing_semantic) and (existing_semantic[1] or 0) > 2

        if existing_semantic and has_payload and not force:
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
            text("SELECT id, key_concepts, sub_institute_id FROM chapter_master WHERE extraction_id = :id"),
            {"id": extraction_id}
        ).fetchone()

        chapter_id = chapter_row[0] if chapter_row else None
        # The tenant comes from the chapter, exactly as it does for topic_master
        # and lms_concept. It used to be hardcoded to 341, which wrote the
        # semantic row into a different tenant from its own chapter whenever the
        # chapter belonged to anyone else -- and the ERP scopes by
        # sub_institute_id, so those rows existed but were never listed.
        sub_institute_id = (chapter_row[2] if chapter_row else None) or row.get("sub_institute_id") or 341

        # Chapter -> Topics -> Concepts already decided what this chapter
        # teaches; slicing against chapter_master.key_concepts instead would let
        # the semantic layer invent a second, differently worded vocabulary for
        # the same chapter, and nothing downstream could join the two.
        # key_concepts stays as the fallback for a chapter whose Topic and
        # Concept queues have not run yet.
        topic_plan = _topic_plan(db, extraction_id)
        key_concepts = _outline_text(topic_plan)
        if not key_concepts:
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
        official_outcomes=official_outcomes_str,
        subject_name=subject,
        class_level=class_level,
        topic_plan=topic_plan
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
    # Rubrics stay concept-wise: one block per concept, each holding its own
    # items and teaching notes, rather than being flattened like the other 12.
    agg_rubrics = []

    for concept_wrapper in concepts_list:
        concept_meta = concept_wrapper.get("concept", {})
        concept_name = concept_meta.get("concept_name", "Unknown Concept")
        # Set by the pipeline from the slice this concept was extracted from.
        # These 13 columns are flattened lists that lose the concept nesting, so
        # without the tag an item cannot be traced back past its concept name.
        topic_id = concept_wrapper.get("topic_id")
        topic_name = concept_wrapper.get("topic_name")

        def inject_meta(items, parent_key="concept_name"):
            """Tag each item with its parent concept, and the topic above it.
            Use parent_key to control which field gets the parent concept name.
            For prerequisites, we use '_parent_concept' to avoid overwriting
            the prerequisite's own 'concept_name' field."""
            if not isinstance(items, list): return items
            for item in items:
                if isinstance(item, dict):
                    item[parent_key] = concept_name
                    if topic_id is not None:
                        item["topic_id"] = topic_id
                        item["topic_name"] = topic_name
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

        rubric_block = concept_wrapper.get("assessment_rubrics")
        if isinstance(rubric_block, dict) and rubric_block.get("items"):
            rubric_block["concept_name"] = concept_name
            if topic_id is not None:
                rubric_block["topic_id"] = topic_id
                rubric_block["topic_name"] = topic_name
            agg_rubrics.append(rubric_block)


        for lo in concept_wrapper.get("learning_objectives", []):
            obj_text = lo.get("objective", "")
            if obj_text:
                all_lo.append(obj_text)
                    
    learning_objective = "\n".join(all_lo) if all_lo else ""
    
    # If every dimension came back empty the swarm did not actually extract
    # anything. Writing that row marks the chapter processed and hides the
    # failure behind a screen of null fields, so refuse it.
    if not any([agg_knowledge, agg_ability, agg_skill, agg_competency, agg_blooms,
                agg_dok, agg_prereqs, agg_misconceptions, agg_rwa, agg_pedagogy,
                agg_lo, agg_outcomes, agg_blueprint, agg_rubrics]):
        raise RuntimeError(
            f"Semantic intelligence for extraction {extraction_id} came back empty: "
            f"{len(concepts_list)} concept(s) were processed but every dimension is "
            f"blank, and {total_input_tokens} input / {total_output_tokens} output "
            f"tokens were billed. Nothing was saved. Check the backend log for the "
            f"underlying LLM error."
        )

    total_topics = len(concepts_list) # Still mapping to total_topics column
    full_json_str = json.dumps(assembled_json, ensure_ascii=False)
    llm_model = settings.active_llm_model

    # Pydantic enforces the shape of what the agents returned, but not that
    # every agent returned anything: flag concepts that came back hollow.
    hollow = sum(
        1 for c in concepts_list
        if not (c.get("knowledge_items") or c.get("abilities") or c.get("learning_outcomes"))
    )
    quality_flag = "good" if not hollow else f"partial ({hollow}/{len(concepts_list)} concepts empty)"
    attempted = assembled_json.get("concepts_attempted", len(concepts_list))
    # A run stopped by the spend ceiling is genuine data, but incomplete - say so
    # rather than letting it look like the chapter only had this many concepts.
    if assembled_json.get("budget_exceeded"):
        quality_flag = f"budget_capped ({len(concepts_list)}/{attempted} concepts)"
    # Same for a run the provider cut short. This IS worth saving: the concepts
    # below were paid for, and discarding them was what turned a mid-run
    # "insufficient balance" into a chapter that cost money and produced
    # nothing. The row stays re-runnable via force=true.
    if assembled_json.get("aborted"):
        quality_flag = f"aborted ({len(concepts_list)}/{attempted} concepts, provider unavailable)"
        logger.warning(
            "Semantic intelligence for extraction %s was cut short after %s/%s concepts: %s. "
            "Saving what was generated; re-run with force=true once the provider is usable.",
            extraction_id, len(concepts_list), attempted, assembled_json.get("abort_reason"),
        )
    
    # 4. Insert or update in semantic_intelligence table.
    #    The swarm above runs for minutes, so pooled connections have gone
    #    stale and this write opens a fresh one. A transient connect failure
    #    here would discard the entire (expensive) LLM result, so retry.
    last_db_error: OperationalError | None = None
    for attempt in range(_PERSIST_ATTEMPTS):
        try:
            with SessionLocal() as db:
                existing = db.execute(
                    text("SELECT id FROM semantic_intelligence WHERE extraction_id = :id"),
                    {"id": extraction_id}
                ).fetchone()
        
                params = {
                    "ext_id": extraction_id,
                    "inst_id": sub_institute_id,
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
                    "assessment_blueprint": json.dumps(agg_blueprint, ensure_ascii=False),
                    "assessment_rubrics": json.dumps(agg_rubrics, ensure_ascii=False)
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
                            assessment_rubrics=:assessment_rubrics,
                            sub_institute_id=:inst_id, updated_at=CURRENT_TIMESTAMP
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
                         real_world_applications, pedagogy, learning_objectives, learning_outcomes, assessment_blueprint,
                         assessment_rubrics)
                        VALUES
                        (:ext_id, :inst_id, :std_id, :sub_id, :ch_id, :sub_name, :std, :ch_num,
                         :lo, :topics, :full_json, :model, :in_tok, :out_tok, :qf,
                         :knowledge, :ability, :skill, :competency, :blooms_level, :dok, :prerequisites, :misconceptions,
                         :real_world_applications, :pedagogy, :learning_objectives, :learning_outcomes, :assessment_blueprint,
                         :assessment_rubrics)
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
        except OperationalError as exc:
            last_db_error = exc
            if attempt == _PERSIST_ATTEMPTS - 1:
                break
            delay = _PERSIST_BACKOFF_SEC * (2 ** attempt)
            logger.warning(
                "Semantic persistence attempt %s/%s for extraction %s failed (%s); retrying in %ss",
                attempt + 1, _PERSIST_ATTEMPTS, extraction_id, exc.orig, delay,
            )
            await asyncio.sleep(delay)

    raise RuntimeError(
        f"Semantic intelligence for extraction {extraction_id} was generated but could "
        f"not be saved after {_PERSIST_ATTEMPTS} attempts. The LLM output was lost; "
        f"re-run once the database is reachable. Last error: {last_db_error}"
    ) from last_db_error

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
