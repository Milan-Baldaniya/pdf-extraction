import json
from app.db.mariadb import SessionLocal, init_mariadb
from sqlalchemy import text

init_mariadb()
db = SessionLocal()

chapters = db.execute(text("SELECT id, chapter_name FROM chapter_master WHERE standard_id = 42 AND unit_id IS NULL")).fetchall()
units = db.execute(text("SELECT id, name FROM lms_units WHERE curriculum_id = 93")).fetchall()

for cm_id, cname in chapters:
    for u_id, uname in units:
        if cname.lower() in uname.lower() or uname.lower() in cname.lower():
            db.execute(text("UPDATE chapter_master SET unit_id = :uid WHERE id = :cmid"), {"uid": u_id, "cmid": cm_id})
            print(f"Mapped {cname} to unit {uname}")
            break

db.commit()
print("Done")
