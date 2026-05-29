import asyncio
import json
from pathlib import Path
import httpx

async def test_extraction():
    url = "http://localhost:8000/api/extract"
    pdf_url = "https://www.w3.org/WAI/ER/tests/xhtml/testfiles/resources/pdf/dummy.pdf"
    
    print(f"Testing extraction with {pdf_url}")
    
    async with httpx.AsyncClient(timeout=300) as client:
        response = await client.post(url, json={"pdf_url": pdf_url, "backend": "pipeline"})
        print(f"Status Code: {response.status_code}")
        print("Response JSON:")
        try:
            print(json.dumps(response.json(), indent=2))
        except Exception as e:
            print(f"Failed to parse JSON: {e}")
            print(response.text)

if __name__ == "__main__":
    asyncio.run(test_extraction())
