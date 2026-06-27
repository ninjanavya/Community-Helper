import os

frontend_dir = r"c:\Users\hp\Desktop\vibe2ship\frontend"
results = []

for file in os.listdir(frontend_dir):
    if file.endswith(".html") or file.endswith(".js"):
        path = os.path.join(frontend_dir, file)
        try:
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
                for kw in ["insight", "resource", "allocation", "escalate"]:
                    if kw in content.lower():
                        results.append(f"{file} contains '{kw}'")
        except Exception as e:
            print(f"Error reading {file}: {e}")

for r in set(results):
    print(r)
