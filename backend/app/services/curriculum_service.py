import logging
import json
from sqlalchemy import text
from app.db.mariadb import SessionLocal
from app.semantic_intelligence.deepseek_client import call_deepseek
from app.services.chapter_period_service import (
    store_llm_chapter_periods,
    sync_chapter_periods_for_curriculum,
)

logger = logging.getLogger(__name__)


def _sync_periods(curriculum_id, db):
    """Push unit period allocations onto chapter_master; never fail Process."""
    if not curriculum_id:
        return {}
    try:
        return sync_chapter_periods_for_curriculum(curriculum_id, db=db)
    except Exception as exc:
        logger.warning("Chapter period sync failed for curriculum %s: %s", curriculum_id, exc)
        return {"status": "failed", "error": str(exc)}


def _period_stats(result):
    """Counts only -- the per-chapter rows travel in extracted_data instead."""
    return {k: v for k, v in (result or {}).items() if k != "assignments"}

def process_curriculum_by_id(extraction_id: int, force: bool = False):
    """Process a curriculum extraction and insert to lms_curriculum and lms_units."""
    with SessionLocal() as db:
        row = db.execute(text("SELECT * FROM document_extractions WHERE id = :id"), {"id": extraction_id}).fetchone()
        if not row:
            raise ValueError(f"Extraction ID {extraction_id} not found.")

        md_content = row.md_content or ""
        if not md_content.strip():
            raise ValueError(f"No markdown content for extraction ID {extraction_id}.")

        # Check if already processed and skip to save tokens
        existing = db.execute(text("SELECT id FROM lms_curriculum WHERE extraction_id = :id"), {"id": extraction_id}).fetchone()
        if existing and not force:
            # The extraction is reused, but the chapter period mapping still
            # runs: it costs no tokens and chapters extracted since the last
            # Process would otherwise never pick up their allocation.
            return {
                "status": "already_processed",
                "action": "skipped",
                "curriculum_id": existing[0],
                "message": "Curriculum already processed. Skipped to save LLM tokens.",
                "chapter_periods": _period_stats(_sync_periods(existing[0], db)),
                "curriculum_data": get_curriculum_data_by_extraction_id(extraction_id)
            }

        prompt = f"""
You are an expert educational data extractor.
Analyze the following curriculum document text and extract the overall framework and marks, as well as the list of units.
IMPORTANT: The document may be in an Indian language (like Sanskrit, Hindi, etc.) or English. Please accurately comprehend the text and extract the units, chapters, and marks in their ORIGINAL language (e.g. Devanagari script for Sanskrit). Treat major sections, themes, or domains (like 'खण्ड' / Khanda, "Work with Life Forms") as units if traditional units are not explicitly listed. Do NOT translate the content to English.

Rules:
- "framework": e.g., "NCF-2023" etc. (string)
- "total_marks": overall marks for the curriculum (integer, usually 100 or 80). Set to null if not explicitly found.
- "internal_marks": internal assessment marks (integer, usually 20). Set to null if not explicitly found.
- "units": A list of objects representing the chapters/units/sections/themes in the curriculum.
   For each unit:
     - "unit_number": integer (e.g. 1, 2). Convert roman or regional numerals to integers. If missing, just assign an incrementing integer based on order.
     - "name": The original name of the unit/section/theme in its native language (string).
     - "planned_periods": integer representing periods or hours allocated. Extract just the number. Set to null if not found.
     - "total_marks": integer marks allocated to this unit (e.g. 25). Set to null if not found.
     - "unit_chapters": A list of strings containing the names of all the chapters/sub-topics/outlines belonging to this unit in their original language. CRITICAL: If traditional chapters are not listed, look for 'Examples' or specific vocations/topics under the theme (e.g., 'Rooftop Gardening', 'Precision Farming', 'Construction', 'Apparel') and extract them as chapters. Return empty list if no chapters/topics/examples are found.
- "chapter_periods": A list of every CHAPTER that has its own period/hour allocation stated anywhere in the document, separate from the unit totals above. Many syllabi state these per chapter (e.g. a heading or row reading "Tissues No. of Periods: 13", "Motion - 13 periods", "Cell (12 Hours)").
   For each:
     - "chapter_name": the chapter's name exactly as written, in its original language (string)
     - "no_of_periods": the number of periods/hours allocated to THAT chapter (integer)
   Only include a chapter when the document states a number for the chapter itself. Do NOT copy a unit's total onto its chapters, do NOT divide or estimate, and return an empty list if the document only allocates time per unit.
- "curricular_goals": A list of Curricular Goals or Objectives (e.g., उद्देश्यानि, शिक्षणोद्देश्यानि, CG-1, CG-2) found in the text. Retain descriptions in the original language. If no explicit goals are found, try to extract general objectives mentioned in the introductory text.
   For each goal:
     - "code": The code of the goal, e.g. "CG 1" or "CG-1" (string). Generate a code like "CG-1" if missing.
     - "description": The textual description of the goal/objective in its original language (string)
     - "competencies": A list of competencies or skills (e.g., कौशलानि, C-1.1, C-1.2) that fall under this goal.
       For each competency:
         - "code": The code of the competency, e.g. "C 1.1" or "C-1.1" (string). Generate a code like "COMP-1" if missing.
         - "description": The textual description of the competency/skill in its original language (string)
- "chapter_learning_outcomes": A list of objects representing detailed chapter-wise competencies and learning outcomes defined throughout the document (especially under each chapter section/table).
   For each chapter:
     - "chapter_name": Core title of the chapter as written in section headings (string)
     - "competency_outcomes": List of competency-to-learning-outcome mappings for that chapter.
       For each mapping:
         - "competency_code": Competency code(s) (e.g. "C-3.1", "C-4.2 and C-5.2", "C-8.2")
         - "learning_outcomes": List of granular learning outcome statements listed under that competency for this chapter.

Markdown Content:
{md_content}

Return exactly a valid JSON object matching this schema:
{{
  "framework": str,
  "total_marks": int,
  "internal_marks": int,
  "units": [
    {{
      "unit_number": int,
      "name": str,
      "planned_periods": int,
      "total_marks": int,
      "unit_chapters": [str]
    }}
  ],
  "chapter_periods": [
    {{
      "chapter_name": str,
      "no_of_periods": int
    }}
  ],
  "curricular_goals": [
    {{
      "code": str,
      "description": str,
      "competencies": [
        {{
          "code": str,
          "description": str
        }}
      ]
    }}
  ],
  "chapter_learning_outcomes": [
    {{
      "chapter_name": str,
      "competency_outcomes": [
        {{
          "competency_code": str,
          "learning_outcomes": [str]
        }}
      ]
    }}
  ]
}}
"""
        try:
            response = call_deepseek(prompt, system_prompt="You are a helpful assistant. Return ONLY a JSON object.", response_format={"type": "json_object"})
            data = response.get("data", {})
        except Exception as e:
            logger.warning(f"LLM call failed for extraction {extraction_id}: {e}. Structural fallback will be used.")
            data = {}

        framework = data.get("framework")

        def _safe_int(val):
            if val is None:
                return None
            if isinstance(val, int):
                return val
            import re
            match = re.search(r'\d+', str(val))
            if match:
                return int(match.group())
            return None

        total_marks = _safe_int(data.get("total_marks"))
        internal_marks = _safe_int(data.get("internal_marks"))

        grade_id = None
        if row.standard_id:
            grade_row = db.execute(text("SELECT grade_id FROM standard WHERE id = :st_id"), {"st_id": row.standard_id}).fetchone()
            if grade_row:
                grade_id = grade_row[0]

        insert_curr_sql = text("""
            INSERT INTO lms_curriculum 
            (extraction_id, subject_id, standard_id, grade_id, syear, board, framework, total_marks, internal_marks, sub_institute_id, curriculum_name, created_at, updated_at)
            VALUES 
            (:extraction_id, :subject_id, :standard_id, :grade_id, :syear, :board, :framework, :total_marks, :internal_marks, :sub_institute_id, :curriculum_name, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            ON DUPLICATE KEY UPDATE
            extraction_id = VALUES(extraction_id),
            grade_id = VALUES(grade_id),
            framework = VALUES(framework),
            total_marks = VALUES(total_marks),
            internal_marks = VALUES(internal_marks),
            curriculum_name = VALUES(curriculum_name),
            updated_at = CURRENT_TIMESTAMP
        """)

        db.execute(insert_curr_sql, {
            "extraction_id": extraction_id,
            "subject_id": row.subject_id,
            "standard_id": row.standard_id,
            "grade_id": grade_id,
            "syear": row.syear,
            "board": row.board,
            "framework": framework,
            "total_marks": total_marks,
            "internal_marks": internal_marks,
            "sub_institute_id": row.sub_institute_id,
            "curriculum_name": row.document_tittle
        })
        db.commit()

        # Fetch the ID (whether inserted or updated)
        curr_id_row = db.execute(text("SELECT id FROM lms_curriculum WHERE extraction_id = :ext_id"), {"ext_id": extraction_id}).fetchone()
        curriculum_id = curr_id_row[0] if curr_id_row else None

        units = data.get("units", [])
        if units and curriculum_id:
            # We will NOT delete any data. Instead, we safely UPDATE existing units or INSERT new ones.
            # First, fetch existing units for this curriculum
            existing_units_rows = db.execute(
                text("SELECT id, unit_number FROM lms_units WHERE curriculum_id = :cid"), 
                {"cid": curriculum_id}
            ).fetchall()
            existing_units = {str(row[1]): row[0] for row in existing_units_rows}

            insert_unit_sql = text("""
                INSERT INTO lms_units 
                (unit_number, curriculum_id, extraction_id, name, planned_periods, total_marks, unit_chapters, created_at, updated_at)
                VALUES 
                (:unit_number, :curriculum_id, :extraction_id, :name, :planned_periods, :total_marks, :unit_chapters, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """)
            
            update_unit_sql = text("""
                UPDATE lms_units 
                SET name = :name,
                    planned_periods = :planned_periods,
                    total_marks = :total_marks,
                    extraction_id = :extraction_id,
                    unit_chapters = :unit_chapters,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = :id
            """)

            for idx, unit in enumerate(units):
                u_num = _safe_int(unit.get("unit_number")) or (idx + 1)
                str_u_num = str(u_num)
                
                if str_u_num in existing_units:
                    # Update existing unit safely
                    db.execute(update_unit_sql, {
                        "id": existing_units[str_u_num],
                        "name": str(unit.get("name", "")),
                        "planned_periods": _safe_int(unit.get("planned_periods") or unit.get("planned_period")),
                        "total_marks": _safe_int(unit.get("total_marks")),
                        "extraction_id": extraction_id,
                        "unit_chapters": json.dumps(unit.get("unit_chapters", []), ensure_ascii=False)
                    })
                else:
                    # Insert new unit safely
                    db.execute(insert_unit_sql, {
                        "unit_number": u_num,
                        "curriculum_id": curriculum_id,
                        "extraction_id": extraction_id,
                        "name": str(unit.get("name", "")),
                        "planned_periods": _safe_int(unit.get("planned_periods") or unit.get("planned_period")),
                        "total_marks": _safe_int(unit.get("total_marks")),
                        "unit_chapters": json.dumps(unit.get("unit_chapters", []), ensure_ascii=False)
                    })
            db.commit()

        # Step 3: Parse and insert curricular goals, competencies, and chapter-wise learning outcomes
        curricular_goals = data.get("curricular_goals", [])
        chapter_learning_outcomes = data.get("chapter_learning_outcomes", [])
        
        # If LLM omitted outcomes or failed, run structural fallback parser
        if not curricular_goals or not chapter_learning_outcomes:
            fb_goals, fb_chapter_los = parse_curriculum_md_fallback(md_content)
            if not curricular_goals:
                curricular_goals = fb_goals
            if not chapter_learning_outcomes:
                chapter_learning_outcomes = fb_chapter_los

        if curriculum_id:
            save_learning_outcomes(
                db=db,
                curriculum_id=curriculum_id,
                extraction_id=extraction_id,
                standard_id=row.standard_id,
                subject_id=row.subject_id,
                curricular_goals=curricular_goals,
                chapter_learning_outcomes=chapter_learning_outcomes
            )

        # Step 4: Fetch exactly what we just inserted so the response format matches perfectly
        outcomes = db.execute(
            text("SELECT * FROM lms_learning_outcomes WHERE curriculum_id = :cid ORDER BY id ASC"), 
            {"cid": curriculum_id}
        ).mappings().fetchall()

        # Overwrite the LLM data with the standardized DB response for the frontend
        data["learning_outcomes"] = [dict(o) for o in outcomes]

        # Step 5: Keep any per-chapter period counts the LLM found, then fill
        # chapter_master.no_of_periods. The sync re-reads the document's own
        # headings first and only falls back to these.
        try:
            store_llm_chapter_periods(db, curriculum_id, data.get("chapter_periods"))
        except Exception as exc:
            logger.warning("Could not store LLM chapter periods for %s: %s", curriculum_id, exc)
            db.rollback()

        chapter_periods = _sync_periods(curriculum_id, db)
        # Mirrored into extracted_data so the frontend renders the mapping the
        # same way whether it just processed or is only viewing.
        data["chapter_periods"] = chapter_periods.get("assignments", [])

        return {
            "status": "success",
            "curriculum_id": curriculum_id,
            "chapter_periods": _period_stats(chapter_periods),
            "extracted_data": data
        }

def get_all_curriculums():
    with SessionLocal() as db:
        query = text("""
            SELECT d.id, d.document_tittle, d.subject_name, d.standard, d.syear, d.board, d.created_at,
                   EXISTS(SELECT 1 FROM lms_curriculum c WHERE c.extraction_id = d.id) as is_processed
            FROM document_extractions d
            WHERE LOWER(d.document_type) = 'curriculum'
            ORDER BY d.id DESC
        """)
        rows = db.execute(query).mappings().fetchall()
        return [dict(row) for row in rows]

def get_curriculum_data_by_extraction_id(extraction_id: int):
    with SessionLocal() as db:
        curr = db.execute(text("SELECT * FROM lms_curriculum WHERE extraction_id = :id"), {"id": extraction_id}).mappings().fetchone()
        if not curr:
            return None
        
        units = db.execute(text("SELECT * FROM lms_units WHERE curriculum_id = :cid ORDER BY unit_number ASC"), {"cid": curr["id"]}).mappings().fetchall()
        
        outcomes = db.execute(text("SELECT * FROM lms_learning_outcomes WHERE curriculum_id = :cid ORDER BY id ASC"), {"cid": curr["id"]}).mappings().fetchall()

        # Chapter-wise periods this curriculum produced, straight from chapter_master.
        try:
            chapter_periods = [dict(r) for r in db.execute(text("""
                SELECT cm.id AS chapter_master_id, cm.chapter_name, cm.no_of_periods,
                       u.id AS unit_id, u.unit_number, u.name AS unit_name,
                       u.planned_periods AS unit_planned_periods
                FROM chapter_master cm
                JOIN lms_units u ON u.id = cm.unit_id
                WHERE u.curriculum_id = :cid
                ORDER BY u.unit_number ASC, cm.sort_order IS NULL, cm.sort_order ASC, cm.id ASC
            """), {"cid": curr["id"]}).mappings().fetchall()]
        except Exception as exc:
            # no_of_periods is added on the first Process; a database that has
            # not run one yet should still return the rest of the curriculum.
            logger.warning("Could not read chapter periods for curriculum %s: %s", curr["id"], exc)
            chapter_periods = []

        # Format the data to perfectly match what the frontend expects in "extracted_data"
        return {
            "curriculum_id": curr["id"],
            "extracted_data": {
                "framework": curr["framework"],
                "total_marks": curr["total_marks"],
                "internal_marks": curr["internal_marks"],
                "units": [dict(u) for u in units],
                "chapter_periods": chapter_periods,
                "learning_outcomes": [dict(o) for o in outcomes]
            }
        }


def parse_curriculum_md_fallback(md_content: str):
    """Fallback structural parser for CGs, Cs, and chapter-wise tables in md_content."""
    import re, html
    
    pos_start = md_content.find("## Page 2")
    pos_end = md_content.find("COURSE STRUCTURE")
    cg_text = md_content[pos_start:pos_end] if (pos_start != -1 and pos_end != -1) else md_content

    cg_matches = list(re.finditer(r'(CG\s*\d+)\s*[–-]\s*(.*?)(?=\s*CG\s*\d+|$)', cg_text, re.DOTALL))
    curricular_goals = []

    for m in cg_matches:
        code = m.group(1).strip()
        body = m.group(2).strip()
        c_pos = re.search(r'C\s*\d+\.\d+', body)
        desc = body[:c_pos.start()].strip().strip('–-').strip() if c_pos else body.split('\n')[0].strip()

        comps = []
        comp_matches = list(re.finditer(r'(C\s*\d+\.\d+)\s*[–-]?\s*(.*?)(?=\s*C\s*\d+\.\d+|\s*CG\s*\d+|$)', body, re.DOTALL))
        for cm in comp_matches:
            comps.append({"code": cm.group(1).strip(), "description": ' '.join(cm.group(2).split()).strip()})

        curricular_goals.append({"code": code, "description": desc, "competencies": comps})

    def clean_html(raw):
        return ' '.join(html.unescape(re.sub(r'<[^>]+>', ' ', raw)).split()).strip()

    chapter_sections = re.split(r'\n(?=#\s+)', md_content)
    chapter_los = []

    for sec in chapter_sections:
        head_match = re.match(r'#\s+([^\n]+)', sec)
        if not head_match: continue
        header = head_match.group(1).strip()
        if any(ignore in header.upper() for ignore in ['PRACTICALS', 'PRESCRIBED', 'COURSE STRUCTURE', 'SCIENCE SUBJECT CODE']):
            continue

        chap_title = re.sub(r'No\.\s*of\s*Periods.*', '', header, flags=re.IGNORECASE).strip()
        tr_matches = re.findall(r'<tr[^>]*>(.*?)</tr>', sec, re.DOTALL | re.IGNORECASE)
        comp_outcomes = []
        
        for tr in tr_matches:
            td_texts = [clean_html(td) for td in re.findall(r'<td[^>]*>(.*?)</td>', tr, re.DOTALL | re.IGNORECASE)]
            if len(td_texts) < 2: continue
            
            comp_found, lo_text = None, None
            for i, text_val in enumerate(td_texts):
                if re.findall(r'C\s*[-–]?\s*\d+\.\d+', text_val):
                    comp_found = text_val
                    lo_text = ' '.join(td_texts[i+1:])
                    break
            
            if comp_found and lo_text and not ('Learning Outcomes' in lo_text and len(lo_text) < 30):
                raw_outcomes = re.split(r'(?=\b(?:Differentiate|Describe|Explain|Demonstrate|Prepare|Identify|Cite|Apply|Discuss|Recognise|Pose|Exhibit|Carry out|Analyse|Formulate|Accurately|Represent|Communicate|Relate|Establish|Illustrate|Classify|Distinguish|Use|Handle|Draw|Display|Correlate|Poses|Calculate|Interpret|State|Name|Write|Derive)\b)', lo_text)
                cleaned_los = [lo.strip() for lo in raw_outcomes if len(lo.strip()) > 5]
                if cleaned_los:
                    comp_outcomes.append({"competency_code": comp_found, "learning_outcomes": cleaned_los})
        
        if comp_outcomes:
            chapter_los.append({"chapter_name": chap_title, "competency_outcomes": comp_outcomes})

    return curricular_goals, chapter_los


def save_learning_outcomes(db, curriculum_id: int, extraction_id: int, standard_id: int, subject_id: int, curricular_goals: list, chapter_learning_outcomes: list):
    """Save Curricular Goals, Competencies, and Chapter Learning Outcomes to lms_learning_outcomes."""
    import re
    db.execute(text("DELETE FROM lms_learning_outcomes WHERE curriculum_id = :cid"), {"cid": curriculum_id})
    db.commit()

    chaps_in_db = db.execute(text("""
        SELECT cm.id, cm.chapter_name
        FROM chapter_master cm
        JOIN lms_units u ON u.id = cm.unit_id
        WHERE u.curriculum_id = :cid
    """), {"cid": curriculum_id}).fetchall()

    db_chap_map = {}
    for c_id, c_name in chaps_in_db:
        db_chap_map[c_name.lower()] = c_id
        first_word = c_name.split(':')[0].split()[0].lower()
        if first_word not in db_chap_map:
            db_chap_map[first_word] = c_id

    insert_outcome_sql = text("""
        INSERT INTO lms_learning_outcomes 
        (curriculum_id, extraction_id, standard_id, subject_id, chapter_id, parent_id, code, type, description, created_at, updated_at)
        VALUES 
        (:curriculum_id, :extraction_id, :standard_id, :subject_id, :chapter_id, :parent_id, :code, :type, :description, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
    """)

    seen_codes = set()
    def get_unique_code(base_code, prefix="CG"):
        code = str(base_code).strip().replace('–', '-').replace(' ', '')
        if not code or code in seen_codes:
            idx = 1
            while True:
                new_code = f"{prefix}-{idx}"
                if new_code not in seen_codes:
                    code = new_code
                    break
                idx += 1
        seen_codes.add(code)
        return code

    comp_code_map = {}

    for cg in curricular_goals:
        cg_code = get_unique_code(cg.get("code", ""), "CG")
        res_cg = db.execute(insert_outcome_sql, {
            "curriculum_id": curriculum_id,
            "extraction_id": extraction_id,
            "standard_id": standard_id,
            "subject_id": subject_id,
            "chapter_id": 0,
            "parent_id": None,
            "code": cg_code,
            "type": "goal",
            "description": cg.get("description", "")
        })
        cg_id = res_cg.lastrowid

        for comp in cg.get("competencies", []):
            comp_code = get_unique_code(comp.get("code", ""), "COMP")
            res_comp = db.execute(insert_outcome_sql, {
                "curriculum_id": curriculum_id,
                "extraction_id": extraction_id,
                "standard_id": standard_id,
                "subject_id": subject_id,
                "chapter_id": 0,
                "parent_id": cg_id,
                "code": comp_code,
                "type": "competency",
                "description": comp.get("description", "")
            })
            comp_id = res_comp.lastrowid
            norm_code = comp_code.lower().replace(' ', '').replace('-', '')
            comp_code_map[norm_code] = comp_id
            comp_code_map[comp_code.lower()] = comp_id

    for ch_item in chapter_learning_outcomes:
        raw_name = ch_item.get("chapter_name", "").lower()
        target_chap_id = 0
        for db_name, cid in db_chap_map.items():
            if db_name in raw_name or raw_name in db_name:
                target_chap_id = cid
                break
        
        for mapping in ch_item.get("competency_outcomes", []):
            comp_raw_code = mapping.get("competency_code", "")
            parsed_codes = re.findall(r'C\s*[-–]?\s*\d+\.\d+', comp_raw_code)
            if not parsed_codes:
                parsed_codes = [comp_raw_code]

            for c_code in parsed_codes:
                norm_c = c_code.lower().replace(' ', '').replace('-', '').replace('–', '')
                parent_comp_id = comp_code_map.get(norm_c) or comp_code_map.get(c_code.lower())
                
                if not parent_comp_id:
                    cg_prefix = norm_c[:2] if len(norm_c) >= 2 else "c1"
                    parent_comp_id = next((v for k, v in comp_code_map.items() if k.startswith(cg_prefix)), list(comp_code_map.values())[0] if comp_code_map else None)

                for idx, lo_desc in enumerate(mapping.get("learning_outcomes", [])):
                    clean_code_base = c_code.upper().replace(' ', '').replace('–', '-')
                    lo_code = get_unique_code(f"{clean_code_base}-LO-{idx+1}", "LO")
                    
                    db.execute(insert_outcome_sql, {
                        "curriculum_id": curriculum_id,
                        "extraction_id": extraction_id,
                        "standard_id": standard_id,
                        "subject_id": subject_id,
                        "chapter_id": target_chap_id,
                        "parent_id": parent_comp_id,
                        "code": lo_code,
                        "type": "learning_outcome",
                        "description": lo_desc
                    })

    db.commit()

