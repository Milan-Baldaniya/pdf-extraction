import re

with open(r'c:\Users\MILAN\Downloads\pdf extraction\backend\app\semantic_intelligence\agents.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Fix Agent 1 call
content = re.sub(
    r'self\._generate_with_fallback\(\s*self\.client_1,\s*self\.keys_1,\s*prompt,\s*text_slice,\s*Agent1CognitiveOutput\s*\)',
    'self._generate_with_fallback(self.client_1, self.keys_1, "idx_1", prompt, text_slice, Agent1CognitiveOutput)',
    content
)

# Fix Agent 2 call
content = re.sub(
    r'self\._generate_with_fallback\(\s*self\.client_2,\s*self\.keys_2,\s*prompt,\s*text_slice,\s*Agent2PedagogyOutput\s*\)',
    'self._generate_with_fallback(self.client_2, self.keys_2, "idx_2", prompt, text_slice, Agent2PedagogyOutput)',
    content
)

# Fix Agent 3 call
content = re.sub(
    r'self\._generate_with_fallback\(\s*self\.client_3,\s*self\.keys_3,\s*prompt,\s*text_slice,\s*Agent3AssessmentOutput\s*\)',
    'self._generate_with_fallback(self.client_3, self.keys_3, "idx_3", prompt, text_slice, Agent3AssessmentOutput)',
    content
)

with open(r'c:\Users\MILAN\Downloads\pdf extraction\backend\app\semantic_intelligence\agents.py', 'w', encoding='utf-8') as f:
    f.write(content)
print("done")
