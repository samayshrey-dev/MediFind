import os
import re
import sys

# Base directory of the project
BASE_DIR = r"c:/Users/samay/MediAI"

# Patterns to replace (case‑insensitive)
PATTERNS = [r"MediAI", r"MediAI", r"MediAI", r"MediAI"]
REPLACEMENT = "MediAI"

# File extensions to process
TEXT_EXTENSIONS = {".py", ".html", ".js", ".css", ".md", ".txt", ".json"}

def should_skip_line(file_path: str, line: str) -> bool:
    # Skip import statements that reference the package name "MediAI"
    stripped = line.lstrip()
    if stripped.startswith("import ") or stripped.startswith("from "):
        # simple check for the word MediAI in import lines
        if "MediAI" in stripped.lower():
            return True
    return False

def replace_in_file(file_path: str) -> bool:
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except Exception as e:
        print(f"[skip] Unable to read {file_path}: {e}")
        return False

    changed = False
    new_lines = []
    for line in lines:
        if should_skip_line(file_path, line):
            new_lines.append(line)
            continue
        original = line
        for pattern in PATTERNS:
            # case‑insensitive replace preserving original case is not required; we just replace with the correct brand
            line = re.sub(pattern, REPLACEMENT, line, flags=re.IGNORECASE)
        if line != original:
            changed = True
        new_lines.append(line)

    if changed:
        try:
            with open(file_path, "w", encoding="utf-8") as f:
                f.writelines(new_lines)
            print(f"[updated] {file_path}")
        except Exception as e:
            print(f"[error] Writing {file_path}: {e}")
            return False
    return changed

def main():
    total_modified = 0
    for root, dirs, files in os.walk(BASE_DIR):
        for name in files:
            _, ext = os.path.splitext(name)
            if ext.lower() in TEXT_EXTENSIONS:
                full_path = os.path.join(root, name)
                if replace_in_file(full_path):
                    total_modified += 1
    print(f"Finished. Modified {total_modified} files.")

if __name__ == "__main__":
    main()
