from app.db.mariadb import SessionLocal
from sqlalchemy import text

with SessionLocal() as db:
    try:
        res = db.execute(text("SELECT id, chapter_name FROM chapter_master WHERE id > 8500 AND extraction_id IS NOT NULL")).mappings().fetchall()
        for r in res:
            db.execute(text("DELETE FROM chapter_master WHERE id = :id"), {"id": r["id"]})
            print(f"Deleted duplicate {r['id']} for {r['chapter_name']}")
        db.commit()
    except Exception as e:
        print(e)
