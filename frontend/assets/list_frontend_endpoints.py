import os
import re

frontend_dir = r"c:\Users\hp\Desktop\vibe2ship\frontend"
endpoints = set()

for file in os.listdir(frontend_dir):
    if file.endswith(".html") or file.endswith(".js"):
        path = os.path.join(frontend_dir, file)
        try:
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
                matches = re.findall(r"http://127\.0\.0\.1:8000/api/\S+?['\"`]", content)
                for m in matches:
                    endpoints.add(m[:-1])
        except Exception as e:
            print(f"Error reading {file}: {e}")

print("Found endpoints in frontend:")
for ep in sorted(endpoints):
    print("-", ep)
