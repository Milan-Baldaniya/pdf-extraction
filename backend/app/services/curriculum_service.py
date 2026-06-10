import logging
import json
from sqlalchemy import text
from app.db.mariadb import SessionLocal
from app.semantic_intelligence.gemini_client import call_gemini

logger = logging.getLogger(__name__)

def process_curriculum_by_id(extraction_id: int):
    """Process a curriculum extraction and insert to lms_curriculum and lms_units."""
    with SessionLocal() as db:
        row = db.execute(text("SELECT * FROM document_extractions WHERE id = :id"), {"id": extraction_id}).fetchone()
        if not row:
            raise ValueError(f"Extraction ID {extraction_id} not found.")

        md_content = row.md_content or ""
        if not md_content.strip():
            raise ValueError(f"No markdown content for extraction ID {extraction_id}.")

        # Check if already processed (we will Upsert instead of returning early)
        existing = db.execute(text("SELECT id FROM lms_curriculum WHERE extraction_id = :id"), {"id": extraction_id}).fetchone()
        is_update = existing is not None

        prompt = f"""
You are an expert educational data extractor.
Analyze the following curriculum document text and extract the overall framework and marks, as well as the list of units.

Rules:
- "framework": e.g., "NCF-2023" etc. (string)
- "total_marks": overall marks for the curriculum (integer, usually 100 or 80)
- "internal_marks": internal assessment marks (integer, usually 20)
- "units": A list of objects representing the chapters/units in the curriculum.
   For each unit:
     - "unit_number": integer (e.g. 1, 2). Convert roman numerals like "I" to 1.
     - "name": name of the unit/theme (string)
     - "planned_periods": integer representing periods or hours allocated (e.g., 50). Extract just the number.
     - "total_marks": integer marks allocated to this unit (e.g. 25)
     - "unit_chapters": A list of strings containing the names of all the chapters belonging to this unit. E.g. ["Chemical Reactions", "Acids, Bases and Salts"]. Return empty list if no chapters are found.

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
  ]
}}
"""
        response = call_gemini(prompt)
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

        return {
            "status": "updated" if is_update else "success",
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
        
        # Format the data to perfectly match what the frontend expects in "extracted_data"
        return {
            "curriculum_id": curr["id"],
            "extracted_data": {
                "framework": curr["framework"],
                "total_marks": curr["total_marks"],
                "internal_marks": curr["internal_marks"],
                "units": [dict(u) for u in units]
            }
        }
