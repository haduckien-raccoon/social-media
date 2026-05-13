import json

# ==========================================
# FILE PATHS
# ==========================================

SOURCE_JSON = "words.json"

SOURCE_TXT = "en.txt"

OUTPUT_FILE = "en_badwords.json"

# ==========================================
# LOAD SOURCE 1
# ==========================================

with open(
    SOURCE_JSON,
    "r",
    encoding="utf-8"
) as f:

    json_words = json.load(f)

# ==========================================
# LOAD SOURCE 2
# ==========================================

with open(
    SOURCE_TXT,
    "r",
    encoding="utf-8"
) as f:

    txt_words = [
        line.strip().lower()
        for line in f
        if line.strip()
    ]

# ==========================================
# MERGE + REMOVE DUPLICATES
# ==========================================

all_words = set()

for word in json_words:

    word = str(word).strip().lower()

    if word:
        all_words.add(word)

for word in txt_words:

    word = str(word).strip().lower()

    if word:
        all_words.add(word)

# ==========================================
# SORT
# ==========================================

final_words = sorted(all_words)

# ==========================================
# SAVE JSON
# ==========================================

with open(
    OUTPUT_FILE,
    "w",
    encoding="utf-8"
) as f:

    json.dump(
        final_words,
        f,
        ensure_ascii=False,
        indent=4
    )

# ==========================================
# DONE
# ==========================================

print(f"[DONE] Total words: {len(final_words)}")

print(f"[DONE] Saved: {OUTPUT_FILE}")