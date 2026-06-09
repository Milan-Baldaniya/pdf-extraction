import os

file_path = 'app/api/routes.py'
with open(file_path, 'r', encoding='utf-8') as f:
    content = f.read()

content = content.replace(
    'from app.services.curriculum_service import process_curriculum_by_id, get_all_curriculums, get_curriculum_data_by_extraction_id',
    'from app.services.curriculum_service import process_curriculum_by_id, get_all_curriculums, get_curriculum_data_by_extraction_id\nfrom app.services.chapter_service import process_chapter_by_id, get_chapter_data_by_extraction_id, get_all_chapters'
)

content = content.replace('async def list_curriculums', 'def list_curriculums')
content = content.replace('async def get_curriculum_result', 'def get_curriculum_result')

append_code = '''
@router.get(
    "/chapters",
    tags=["Chapter Processing"],
    summary="List all chapters in document_extractions",
)
def list_chapters() -> list[dict[str, Any]]:
    return get_all_chapters()

@router.post(
    "/chapters/{extraction_id}/process",
    tags=["Chapter Processing"],
    summary="Process a chapter using Gemini and populate chapter_master",
)
async def process_chapter(extraction_id: int) -> dict[str, Any]:
    try:
        result = await asyncio.to_thread(process_chapter_by_id, extraction_id)
        return result
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.exception("Failed to process chapter")
        raise HTTPException(status_code=500, detail=f"Processing failed: {exc}")

@router.get(
    "/chapters/{extraction_id}/result",
    tags=["Chapter Processing"],
    summary="Fetch the chapter_master data for a processed extraction",
)
def get_chapter_result(extraction_id: int) -> dict[str, Any]:
    try:
        data = get_chapter_data_by_extraction_id(extraction_id)
        if not data:
            raise HTTPException(status_code=404, detail="Chapter data not found")
        return data
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to fetch chapter result")
        raise HTTPException(status_code=500, detail=f"Fetch failed: {exc}")
'''

with open(file_path, 'w', encoding='utf-8') as f:
    f.write(content + '\n' + append_code)

print("routes.py updated successfully!")
