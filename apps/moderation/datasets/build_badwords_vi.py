import re
import json
import pandas as pd
from collections import Counter

# ==========================================
# CONFIG
# ==========================================

CSV_PATH = "train.csv"

STOPWORDS_PATH = "vietnamese-stopwords.txt"

OUTPUT_FILE = "vi_badwords.json"

MIN_TOXIC_FREQ = 5

MIN_SCORE = 3.0

# ==========================================
# LOAD DATASET
# ==========================================

print("[INFO] Loading dataset...")

df = pd.read_csv(CSV_PATH)

print(df.head())

# ==========================================
# LOAD STOPWORDS
# ==========================================

def load_stopwords(path):

    with open(path, "r", encoding="utf-8") as f:

        return set(
            line.strip().lower()
            for line in f
            if line.strip()
        )

STOPWORDS = load_stopwords(STOPWORDS_PATH)

print(f"[INFO] Stopwords loaded: {len(STOPWORDS)}")

# ==========================================
# NORMALIZE TEXT
# ==========================================

def normalize_text(text):

    text = str(text).lower()

    # remove urls
    text = re.sub(r"http\\S+", " ", text)

    # remove special chars
    text = re.sub(
        r"[^a-zA-Z0-9À-ỹ\\s]",
        " ",
        text
    )

    # remove multiple spaces
    text = re.sub(r"\\s+", " ", text).strip()

    return text

# ==========================================
# BUILD COUNTERS
# ==========================================

toxic_counter = Counter()
clean_counter = Counter()

# ==========================================
# PROCESS TOXIC COMMENTS
# ==========================================

print("[INFO] Processing toxic comments...")

toxic_df = df[df["label_id"] != 0]

for comment in toxic_df["free_text"]:

    text = normalize_text(comment)

    words = text.split()

    for word in words:

        if len(word) < 2:
            continue

        if word.isdigit():
            continue

        if word in STOPWORDS:
            continue

        toxic_counter[word] += 1

# ==========================================
# PROCESS CLEAN COMMENTS
# ==========================================

print("[INFO] Processing clean comments...")

clean_df = df[df["label_id"] == 0]

for comment in clean_df["free_text"]:

    text = normalize_text(comment)

    words = text.split()

    for word in words:

        if len(word) < 2:
            continue

        if word.isdigit():
            continue

        if word in STOPWORDS:
            continue

        clean_counter[word] += 1

# ==========================================
# CALCULATE TOXIC SCORE
# ==========================================

print("[INFO] Calculating toxic scores...")

badwords = []

for word, toxic_freq in toxic_counter.items():

    clean_freq = clean_counter.get(word, 0)

    # toxic ratio
    score = toxic_freq / (clean_freq + 1)

    # filter strong toxic words
    if (
        toxic_freq >= MIN_TOXIC_FREQ
        and score >= MIN_SCORE
    ):

        badwords.append({
            "word": word,
            "toxic_freq": toxic_freq,
            "clean_freq": clean_freq,
            "score": round(score, 2)
        })

# ==========================================
# SORT
# ==========================================

badwords = sorted(
    badwords,
    key=lambda x: x["score"],
    reverse=True
)

# ==========================================
# EXPORT ONLY WORDS
# ==========================================

export_words = [
    item["word"]
    for item in badwords
]

# ==========================================
# SAVE JSON
# ==========================================

with open(
    OUTPUT_FILE,
    "w",
    encoding="utf-8"
) as f:

    json.dump(
        export_words,
        f,
        ensure_ascii=False,
        indent=4
    )

print(f"[DONE] Saved: {OUTPUT_FILE}")

# ==========================================
# SHOW TOP RESULTS
# ==========================================

print("\n===== TOP TOXIC WORDS =====")

for item in badwords[:100]:

    print(
        f"{item['word']:<20} "
        f"toxic={item['toxic_freq']:<5} "
        f"clean={item['clean_freq']:<5} "
        f"score={item['score']}"
    )