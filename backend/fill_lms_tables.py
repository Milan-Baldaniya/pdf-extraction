import os
import json
import logging
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
import re

# Set up backend paths so we can import app modules
import sys
from pathlib import Path
sys.path.append(str(Path(__file__).resolve().parent))

from app.utils.config import settings
from app.semantic_intelligence.deepseek_client import call_deepseek

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

def _mariadb_url():
    from sqlalchemy.engine import URL
    return URL.create(
        "mysql+pymysql",
        username=settings.mariadb_user,
        password=settings.mariadb_password,
        host=settings.mariadb_host,
        port=settings.mariadb_port,
        database=settings.mariadb_db,
    )

def process_curriculum(db, extraction_row):
    """Use LLM to extract data from md_content and insert into target tables."""
    extraction_id = extraction_row.id
    md_content = extraction_row.md_content or ""
    
    if not md_content.strip():
        logger.warning(f"No markdown content for extraction_id {extraction_id}. Skipping.")
        return

    logger.info(f"Processing curriculum for extraction_id {extraction_id}...")

    prompt = f"""
You are an expert educational data extractor.
Analyze the following curriculum document text and extract the overall framework and marks, as well as the list of units.

Rules:
- "framework": e.g., "NCF-2023", "NCF-2005",  etc. (string)
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
    try:
        response = call_deepseek(prompt, system_prompt="You are an expert educational data extractor. Return ONLY a valid JSON object.", response_format={"type": "json_object"})
        data = response.get("data", {})
    except Exception as e:
        logger.error(f"Failed to get LLM response for extraction_id {extraction_id}: {e}")
        return

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
    
    # Insert into lms_curriculum
    insert_curr_sql = text("""
        INSERT INTO lms_curriculum 
        (extraction_id, subject_id, standard_id, syear, board, framework, total_marks, internal_marks, sub_institute_id, created_at, updated_at, curriculum_name)
        VALUES 
        (:extraction_id, :subject_id, :standard_id, :syear, :board, :framework, :total_marks, :internal_marks, :sub_institute_id, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, :curriculum_name)
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
        "subject_id": extraction_row.subject_id,
        "standard_id": extraction_row.standard_id,
        "syear": extraction_row.syear,
        "board": extraction_row.board,
        "framework": framework,
        "total_marks": total_marks,
        "internal_marks": internal_marks,
        "sub_institute_id": extraction_row.sub_institute_id,
        "curriculum_name": extraction_row.document_tittle
    })
    db.commit()

    # Get the inserted curriculum_id
    curr_id_row = db.execute(text("SELECT id FROM lms_curriculum WHERE extraction_id = :ext_id"), {"ext_id": extraction_id}).fetchone()
    curriculum_id = curr_id_row[0] if curr_id_row else None

    if not curriculum_id:
        logger.error(f"Failed to retrieve curriculum_id for extraction_id {extraction_id}")
        return

    # Safely upsert lms_units without deleting
    units = data.get("units", [])
    if units:
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
                db.execute(update_unit_sql, {
                    "id": existing_units[str_u_num],
                    "name": str(unit.get("name", "")),
                    "planned_periods": _safe_int(unit.get("planned_periods") or unit.get("planned_period")),
                    "total_marks": _safe_int(unit.get("total_marks")),
                    "extraction_id": extraction_id,
                    "unit_chapters": json.dumps(unit.get("unit_chapters", []))
                })
            else:
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
    
    logger.info(f"Successfully processed extraction_id {extraction_id}: created curriculum ID {curriculum_id} with {len(units)} units.")

def main():
    logger.info("Starting Curriculum Migration Script")
    engine = create_engine(_mariadb_url())
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    
    with SessionLocal() as db:
        
        # Select all curriculum extractions
        # You can add a WHERE clause here to avoid reprocessing if needed, e.g.
        # AND id NOT IN (SELECT extraction_id FROM lms_curriculum WHERE extraction_id IS NOT NULL)
        query = text("""
            SELECT id, document_tittle, subject_id, standard_id, syear, board, sub_institute_id, md_content 
            FROM document_extractions 
            WHERE LOWER(document_type) = 'curriculum'
            AND id NOT IN (SELECT extraction_id FROM lms_curriculum WHERE extraction_id IS NOT NULL)
        """)
        
        rows = db.execute(query).fetchall()
        logger.info(f"Found {len(rows)} unprocessed curriculum documents.")
        
        for row in rows:
            process_curriculum(db, row)

    logger.info("Migration completed.")

if __name__ == "__main__":
    main()
