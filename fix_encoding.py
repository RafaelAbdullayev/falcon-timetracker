import os

files_to_fix = ["app.py", "templates/index.html"]

for filepath in files_to_fix:
    if os.path.exists(filepath):
        try:
            with open(filepath, "r", encoding="cp1251") as f:
                content = f.read()
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(content)
            print(f"[OK] Fixed: {filepath}")
        except Exception as e:
            print(f"[ERROR] {filepath}: {e}")
    else:
        print(f"[NOT FOUND] {filepath}")