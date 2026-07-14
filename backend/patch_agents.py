"""
DEPRECATED: This script was a one-time migration tool that patched agents.py
for Gemini multi-key rotation. The project has since migrated to DeepSeek.
agents.py now uses deepseek_client.py natively — do NOT run this script.
"""
import sys
print("ERROR: This script is DEPRECATED. agents.py already uses DeepSeek. No action needed.")
sys.exit(1)

import re

with open(r'c:\Users\MILAN\Downloads\pdf extraction\backend\app\semantic_intelligence\agents.py', 'r', encoding='utf-8') as f:
    content = f.read()

# 1. Update the __init__ logic
new_init = '''    def __init__(self):
        # Reload keys dynamically so live edits to .env take effect immediately
        from dotenv import load_dotenv
        import os
        load_dotenv(override=True)
        
        self.keys_1 = [os.getenv("GEMINI_API_KEY_AGENT_1")] + [os.getenv(f"GEMINI_API_KEY_AGENT_1.{i}") for i in range(1, 6)]
        self.keys_1 = [k for k in self.keys_1 if k]
        self.idx_1 = 0
        
        self.keys_2 = [os.getenv("GEMINI_API_KEY_AGENT_2")] + [os.getenv(f"GEMINI_API_KEY_AGENT_2.{i}") for i in range(1, 6)]
        self.keys_2 = [k for k in self.keys_2 if k]
        self.idx_2 = 0
        
        self.keys_3 = [os.getenv("GEMINI_API_KEY_AGENT_3")] + [os.getenv(f"GEMINI_API_KEY_AGENT_3.{i}") for i in range(1, 6)]
        self.keys_3 = [k for k in self.keys_3 if k]
        self.idx_3 = 0
        
        self.key_last_used = {}

        # Ensure high reasoning capable models are used for the deep intelligence layers
        self.client_1 = genai.GenerativeModel("gemini-2.5-flash")
        self.client_2 = genai.GenerativeModel("gemini-2.5-flash")
        self.client_3 = genai.GenerativeModel("gemini-2.5-flash")'''

content = re.sub(r'    def __init__\(self\):.*?self\.client_3 = genai\.GenerativeModel\("gemini-2\.5-flash"\)', new_init, content, flags=re.DOTALL)

# 2. Add _get_next_key logic and update _generate_with_fallback
new_gen = '''    async def _get_next_key(self, keys_list: List[str], idx_attr: str) -> str:
        if not keys_list:
            return None
        import time
        import asyncio
        
        idx = getattr(self, idx_attr)
        key = keys_list[idx]
        setattr(self, idx_attr, (idx + 1) % len(keys_list))
        
        # Enforce 60s cooldown for each API key use
        last_used = self.key_last_used.get(key, 0)
        elapsed = time.time() - last_used
        if elapsed < 60:
            wait_time = 60 - elapsed
            print(f"  [COOLDOWN] Key ...{key[-4:]} in cooldown. Waiting {wait_time:.1f}s...")
            await asyncio.sleep(wait_time)
            
        self.key_last_used[key] = time.time()
        return key

    async def _generate_with_fallback(self, client, keys: List[str], idx_attr: str, prompt: str, text_slice: str, schema: BaseModel) -> dict:
        import time
        import asyncio
        from google.api_core.exceptions import ResourceExhausted, InternalServerError
        
        last_error = None
        max_retries = 3
        
        key = await self._get_next_key(keys, idx_attr)
        if not key:
            print("  [CRITICAL WARNING] No API keys available for this agent!")
            return {}
            
        genai.configure(api_key=key)
        print(f"  [API] Trying with key ending in ...{key[-4:]}")
        
        for attempt in range(max_retries):
            try:
                response = await client.generate_content_async(
                    contents=[prompt, text_slice],
                    generation_config=self._get_generation_config(schema)
                )
                return json.loads(response.text)
            except Exception as e:
                last_error = e
                err_str = str(e)
                print(f"  [WARNING] API Error on key ...{key[-4:]} (Attempt {attempt+1}/{max_retries}): {err_str}")
                
                if "403" in err_str or "API key not valid" in err_str or "401" in err_str:
                    break
                elif "429" in err_str or "quota" in err_str.lower() or isinstance(e, ResourceExhausted):
                    if attempt < max_retries - 1:
                        print(f"  [API] Rate limit hit. Pausing 60 seconds to reset RPM limit...")
                        await asyncio.sleep(60)
                    else:
                        break
                else:
                    await asyncio.sleep(2)
                    
        print(f"  [CRITICAL WARNING] Returning empty object due to persistent failure. Last error: {last_error}")
        return {}'''

content = re.sub(r'    async def _generate_with_fallback\(self, client, keys: List\[str\], prompt: str, text_slice: str, schema: BaseModel\) -> dict:.*?        return \{\}', new_gen, content, flags=re.DOTALL)

# 3. Update the calls to _generate_with_fallback
content = content.replace(
    'return await self._generate_with_fallback(self.client_1, self.keys_1, prompt, text_slice, Agent1CognitiveOutput)',
    'return await self._generate_with_fallback(self.client_1, self.keys_1, "idx_1", prompt, text_slice, Agent1CognitiveOutput)'
)
content = content.replace(
    'return await self._generate_with_fallback(self.client_2, self.keys_2, prompt, text_slice, Agent2PedagogyOutput)',
    'return await self._generate_with_fallback(self.client_2, self.keys_2, "idx_2", prompt, text_slice, Agent2PedagogyOutput)'
)
content = content.replace(
    'return await self._generate_with_fallback(self.client_3, self.keys_3, prompt, text_slice, Agent3AssessmentOutput)',
    'return await self._generate_with_fallback(self.client_3, self.keys_3, "idx_3", prompt, text_slice, Agent3AssessmentOutput)'
)

with open(r'c:\Users\MILAN\Downloads\pdf extraction\backend\app\semantic_intelligence\agents.py', 'w', encoding='utf-8') as f:
    f.write(content)

print("Updated agents.py")
