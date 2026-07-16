import logging
import json
from sqlalchemy import text
from app.db.mariadb import SessionLocal
from app.semantic_intelligence.deepseek_client import call_deepseek

logger = logging.getLogger(__name__)

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
            return {
                "status": "already_processed",
                "action": "skipped",
                "curriculum_id": existing[0],
                "message": "Curriculum already processed. Skipped to save LLM tokens.",
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
- "curricular_goals": A list of Curricular Goals or Objectives (e.g., उद्देश्यानि, शिक्षणोद्देश्यानि, CG-1, CG-2) found in the text. Retain descriptions in the original language. If no explicit goals are found, try to extract general objectives mentioned in the introductory text.
   For each goal:
     - "code": The code of the goal, e.g. "CG 1" or "CG-1" (string). Generate a code like "CG-1" if missing.
     - "description": The textual description of the goal/objective in its original language (string)
     - "competencies": A list of competencies or skills (e.g., कौशलानि, C-1.1, C-1.2) that fall under this goal.
       For each competency:
         - "code": The code of the competency, e.g. "C 1.1" or "C-1.1" (string). Generate a code like "COMP-1" if missing.
         - "description": The textual description of the competency/skill in its original language (string)

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
  ]
}}
"""
        response = call_deepseek(prompt, system_prompt="You are a helpful assistant. Return ONLY a JSON object.", response_format={"type": "json_object"})
        data = response.get("data", {})

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

        insert_curr_sql = text("""
            INSERT INTO lms_curriculum 
            (extraction_id, subject_id, standard_id, syear, board, framework, total_marks, internal_marks, sub_institute_id, curriculum_name, created_at, updated_at)
            VALUES 
            (:extraction_id, :subject_id, :standard_id, :syear, :board, :framework, :total_marks, :internal_marks, :sub_institute_id, :curriculum_name, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            ON DUPLICATE KEY UPDATE
            extraction_id = VALUES(extraction_id),
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
                        "unit_chapters": json.dumps(unit.get("unit_chapters", []))
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
                        "unit_chapters": json.dumps(unit.get("unit_chapters", []))
                    })
            db.commit()

        # Step 3: Parse and insert curricular goals and competencies
        curricular_goals = data.get("curricular_goals", [])
        if curricular_goals and curriculum_id:
            # Clean up old outcomes for this curriculum to prevent duplicates
            db.execute(
                text("DELETE FROM lms_learning_outcomes WHERE curriculum_id = :cid"),
                {"cid": curriculum_id}
            )
            db.commit()

            insert_outcome_sql = text("""
                INSERT INTO lms_learning_outcomes 
                (curriculum_id, extraction_id, standard_id, subject_id, parent_id, code, type, description, created_at, updated_at)
                VALUES 
                (:curriculum_id, :extraction_id, :standard_id, :subject_id, :parent_id, :code, :type, :description, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """)
            seen_codes = set()
            def get_unique_code(base_code, prefix="CG"):
                code = str(base_code).strip()
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

            for cg in curricular_goals:
                # Insert the Curricular Goal
                cg_code = get_unique_code(cg.get("code", ""), "CG")
                res_cg = db.execute(insert_outcome_sql, {
                    "curriculum_id": curriculum_id,
                    "extraction_id": extraction_id,
                    "standard_id": row.standard_id,
                    "subject_id": row.subject_id,
                    "parent_id": None,
                    "code": cg_code,
                    "type": "Curricular Goal",
                    "description": cg.get("description", "")
                })
                
                # Fetch the ID of the inserted goal directly from cursor's lastrowid
                cg_id = res_cg.lastrowid
                
                # Insert its Competencies
                for comp in cg.get("competencies", []):
                    comp_code = get_unique_code(comp.get("code", ""), "COMP")
                    db.execute(insert_outcome_sql, {
                        "curriculum_id": curriculum_id,
                        "extraction_id": extraction_id,
                        "standard_id": row.standard_id,
                        "subject_id": row.subject_id,
                        "parent_id": cg_id,
                        "code": comp_code,
                        "type": "Competency",
                        "description": comp.get("description", "")
                    })
            db.commit()

        # Step 4: Fetch exactly what we just inserted so the response format matches perfectly
        outcomes = db.execute(
            text("SELECT * FROM lms_learning_outcomes WHERE curriculum_id = :cid ORDER BY id ASC"), 
            {"cid": curriculum_id}
        ).mappings().fetchall()

        # Overwrite the LLM data with the standardized DB response for the frontend
        data["learning_outcomes"] = [dict(o) for o in outcomes]

        return {
            "status": "success",
            "curriculum_id": curriculum_id,
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
        
        # Format the data to perfectly match what the frontend expects in "extracted_data"
        return {
            "curriculum_id": curr["id"],
            "extracted_data": {
                "framework": curr["framework"],
                "total_marks": curr["total_marks"],
                "internal_marks": curr["internal_marks"],
                "units": [dict(u) for u in units],
                "learning_outcomes": [dict(o) for o in outcomes]
            }
        }
