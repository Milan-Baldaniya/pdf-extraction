from app.db.supabase_client import supabase

res = supabase.table("chapter_semantic_intelligence").select("*").limit(1).execute()
if res.data:
    print("Keys in phase 2 record:")
    print(res.data[0].keys())
else:
    print("No data")
