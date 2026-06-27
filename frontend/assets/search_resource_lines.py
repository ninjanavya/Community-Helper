import os

frontend_dir = r"c:\Users\hp\Desktop\vibe2ship\frontend"

for file in ["manager.html", "admin.html"]:
    path = os.path.join(frontend_dir, file)
    if os.path.exists(path):
        print(f"\n=== Lines in {file} containing 'resource' ===")
        with open(path, "r", encoding="utf-8") as f:
            for idx, line in enumerate(f, 1):
                if "resource" in line.lower():
                    print(f"{idx}: {line.strip()}")
