import asyncio
import sys
import json
sys.path.insert(0, ".")
from app.db.mariadb import init_mariadb, SessionLocal
from sqlalchemy import text
from app.lesson_intelligence.micro_planner import generate_micro_plan_for_period

async def main():
    init_mariadb()
    
    # Get the first period ID for plan 1
    db = SessionLocal()
    row = db.execute(text("SELECT id FROM lms_lesson_plan_periods WHERE lms_intelligence_lesson_plans_id=1 ORDER BY scheduled_date LIMIT 1")).fetchone()
    db.close()
    
    period_id = row[0]
    print(f"Testing Micro Plan for period_id={period_id}...")
    
    result = await generate_micro_plan_for_period(period_id)
    print(json.dumps(result, indent=2))
    
    db = SessionLocal()
    updated = db.execute(text("SELECT blooms_level, learning_objectives, plan_json FROM lms_lesson_plan_periods WHERE id=:pid"), {"pid": period_id}).mappings().fetchone()
    db.close()
    
    print("\n--- DB Result ---")
    print("Blooms:", updated["blooms_level"])
    print("Objectives:", updated["learning_objectives"])
    print("Plan JSON:\n", json.dumps(json.loads(updated["plan_json"]), indent=2))

if __name__ == "__main__":
    asyncio.run(main())
