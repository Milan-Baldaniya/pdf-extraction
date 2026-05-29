from app.db.supabase_client import supabase

try:
    res = supabase.table("teaching_intelligence").delete().match({
        "chapter_id": 1,
        "language": "english",
        "teaching_style": "engaging",
        "difficulty_level": "grade_level",
        "prompt_version": 1
    }).execute()
    print("Delete success:", res.data)
except Exception as e:
    print("Delete error:", type(e), str(e))
