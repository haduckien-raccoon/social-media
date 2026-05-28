from __future__ import annotations

import html
import json
import re
import unicodedata
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import joblib
import numpy as np
import pandas as pd
from scipy.sparse import csr_matrix
from sklearn.base import BaseEstimator, TransformerMixin
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics import (
    accuracy_score,
    average_precision_score,
    classification_report,
    confusion_matrix,
    f1_score,
    precision_recall_fscore_support,
    roc_auc_score,
)
from sklearn.pipeline import FeatureUnion, Pipeline
from sklearn.preprocessing import MaxAbsScaler

try:
    from pyvi import ViTokenizer
except Exception:
    ViTokenizer = None

LABEL_MAP_DEFAULT = {0: 0, 1: 1, 2: 1, "0": 0, "1": 1, "2": 1}

# Không nên xóa stopwords cho bài toán toxic vì từ phủ định/ngữ cảnh có thể quan trọng.
EN_CONTRACTIONS = {
    "can't": "can not",
    "cannot": "can not",
    "won't": "will not",
    "n't": " not",
    "i'm": "i am",
    "you're": "you are",
    "he's": "he is",
    "she's": "she is",
    "it's": "it is",
    "we're": "we are",
    "they're": "they are",
    "i've": "i have",
    "you've": "you have",
    "we've": "we have",
    "they've": "they have",
    "i'll": "i will",
    "you'll": "you will",
    "we'll": "we will",
    "they'll": "they will",
    "i'd": "i would",
    "you'd": "you would",
    "we'd": "we would",
    "they'd": "they would",
}

VI_TEENCODE_MAP = {
    "ko": "không", "k": "không", "khong": "không", "khum": "không", "hok": "không", "hong": "không",
    "dc": "được", "đc": "được", "duoc": "được",
    "j": "gì", "gi": "gì",
    "mik": "mình", "mk": "mình", "m": "mày", "t": "tao",
    "bn": "bạn", "b": "bạn", "ny": "người_yêu",
    "vl": "__vi_toxic_slang__", "vcl": "__vi_toxic_slang__", "vkl": "__vi_toxic_slang__",
    "dm": "__vi_toxic_slang__", "đm": "__vi_toxic_slang__", "dmm": "__vi_toxic_slang__", "đmm": "__vi_toxic_slang__",
    "cc": "__vi_toxic_slang__", "cl": "__vi_toxic_slang__",
}

LEET_TABLE = str.maketrans({"0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "7": "t", "@": "a", "$": "s"})


def strip_vietnamese_accents(text: str) -> str:
    text = unicodedata.normalize("NFD", text)
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    text = text.replace("đ", "d").replace("Đ", "D")
    return unicodedata.normalize("NFC", text)


def reduce_flooding(text: str, keep: int = 2) -> str:
    # nguoooo -> nguoo; fuuuu -> fuu. Giữ 2 ký tự để model vẫn học được sắc thái nhấn mạnh.
    return re.sub(r"([A-Za-zÀ-ỹ])\1{" + str(keep) + r",}", lambda m: m.group(1) * keep, text)


def normalize_noise(text: Any) -> str:
    if pd.isna(text):
        return ""
    text = html.unescape(str(text))
    text = unicodedata.normalize("NFC", text)
    text = text.replace("\u200b", " ").replace("\ufeff", " ")
    text = re.sub(r"https?://\S+|www\.\S+", " URL ", text)
    text = re.sub(r"[\w\.-]+@[\w\.-]+", " EMAIL ", text)
    text = re.sub(r"@\w+", " USER ", text)
    text = re.sub(r"#(\w+)", r" \1 ", text)
    return text


def normalize_vietnamese(
    text: Any,
    tokenize: bool = True,
    remove_accents: bool = False,
    keep_toxic_placeholders: bool = True,
) -> str:
    text = normalize_noise(text).lower()
    text = reduce_flooding(text, keep=2)

    # Tách những trường hợp viết kiểu d.m, đ*m, d-m về token gần hơn.
    text = re.sub(r"[dđ][\W_]*[m]", " dm ", text)

    # Giữ ! ? vì hữu ích trong toxic; phần còn lại đưa về space.
    text = re.sub(r"[^0-9a-zA-ZÀ-ỹ_!?\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()

    tokens = []
    for tok in text.split():
        mapped = VI_TEENCODE_MAP.get(tok, tok)
        if mapped.startswith("__vi_toxic_slang__") and not keep_toxic_placeholders:
            mapped = tok
        tokens.append(mapped)
    text = " ".join(tokens)

    if remove_accents:
        text = strip_vietnamese_accents(text)

    if tokenize and ViTokenizer is not None and text:
        text = ViTokenizer.tokenize(text)

    text = re.sub(r"\s+", " ", text).strip()
    return text


def normalize_english(text: Any, deobfuscate: bool = True) -> str:
    text = normalize_noise(text).lower()
    text = reduce_flooding(text, keep=2)

    # Expand contractions trước khi remove punctuation.
    for k, v in EN_CONTRACTIONS.items():
        text = text.replace(k, v)

    # Chuẩn hóa một số kiểu né lọc: f.u.c.k -> f u c k; f*ck giữ char ngram bắt được.
    text = re.sub(r"([a-zA-Z])[\.\-_\*]+(?=[a-zA-Z])", r"\1", text)
    if deobfuscate:
        # Leetspeak nhẹ, không thay mọi số trong toàn câu bằng chữ nếu token có cả chữ và số.
        parts = []
        for tok in text.split():
            if re.search(r"[a-zA-Z]", tok) and re.search(r"[013457@$]", tok):
                parts.append(tok.translate(LEET_TABLE))
            else:
                parts.append(tok)
        text = " ".join(parts)

    text = re.sub(r"[^0-9a-zA-Z_!?\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def normalize_for_language(text: Any, language: str, mode: str = "word") -> str:
    language = language.lower()
    if language.startswith("vi"):
        if mode == "vi_accentless":
            return normalize_vietnamese(text, tokenize=False, remove_accents=True)
        if mode == "vi_syllable":
            return normalize_vietnamese(text, tokenize=False, remove_accents=False)
        return normalize_vietnamese(text, tokenize=True, remove_accents=False)
    if language.startswith("en"):
        return normalize_english(text, deobfuscate=True)
    return normalize_english(text, deobfuscate=True)


def load_lexicon(file_path: str | Path | None, language: str = "vi") -> set[str]:
    if not file_path:
        return set()
    file_path = Path(file_path)
    if not file_path.exists():
        print(f"⚠️ Không tìm thấy lexicon: {file_path}. Bỏ qua lexicon feature.")
        return set()

    try:
        if file_path.suffix.lower() == ".json":
            with file_path.open("r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                values = list(data.keys()) + [str(x) for v in data.values() if isinstance(v, list) for x in v]
            elif isinstance(data, list):
                values = data
            else:
                values = []
        else:
            values = file_path.read_text(encoding="utf-8").splitlines()

        lex = set()
        for v in values:
            v = str(v).strip()
            if not v:
                continue
            lex.add(normalize_for_language(v, language=language, mode="word" if language.startswith("en") else "vi_syllable"))
            if language.startswith("vi"):
                lex.add(normalize_for_language(v, language=language, mode="vi_accentless"))
        lex = {x for x in lex if x}
        print(f"✅ Loaded {len(lex)} lexicon terms from {file_path}")
        return lex
    except Exception as e:
        print(f"⚠️ Lỗi đọc lexicon {file_path}: {e}. Bỏ qua.")
        return set()


class LanguagePreprocessor(BaseEstimator, TransformerMixin):
    def __init__(self, language: str = "vi", mode: str = "word"):
        self.language = language
        self.mode = mode

    def fit(self, X: Sequence[Any], y: Optional[Sequence[int]] = None):
        return self

    def transform(self, X: Sequence[Any]) -> List[str]:
        return [normalize_for_language(x, language=self.language, mode=self.mode) for x in X]


class ToxicTextStats(BaseEstimator, TransformerMixin):
    def __init__(self, language: str = "vi", lexicon: Optional[set[str]] = None):
        self.language = language
        self.lexicon = lexicon or set()

    def fit(self, X: Sequence[Any], y: Optional[Sequence[int]] = None):
        return self

    def transform(self, X: Sequence[Any]) -> csr_matrix:
        rows = []
        for raw in X:
            raw_text = "" if pd.isna(raw) else str(raw)
            norm_word = normalize_for_language(raw_text, self.language, mode="word")
            norm_plain = normalize_for_language(raw_text, self.language, mode="vi_syllable" if self.language.startswith("vi") else "word")
            norm_accentless = strip_vietnamese_accents(norm_plain) if self.language.startswith("vi") else norm_plain
            tokens = norm_word.split()
            plain_tokens = norm_plain.split()

            char_len = len(raw_text)
            token_count = len(tokens)
            unique_ratio = len(set(tokens)) / max(token_count, 1)
            exclam_count = raw_text.count("!")
            question_count = raw_text.count("?")
            digit_count = sum(ch.isdigit() for ch in raw_text)
            upper_chars = sum(ch.isupper() for ch in raw_text)
            alpha_chars = sum(ch.isalpha() for ch in raw_text)
            uppercase_ratio = upper_chars / max(alpha_chars, 1)
            repeated_punct = len(re.findall(r"([!?])\1+", raw_text))
            repeated_chars = len(re.findall(r"([A-Za-zÀ-ỹ])\1{2,}", raw_text))
            url_count = len(re.findall(r"https?://|www\.", raw_text.lower()))
            user_mention_count = len(re.findall(r"@\w+", raw_text))

            # Lexicon hit: token-level + substring-level + accentless branch for Vietnamese.
            token_set = set(tokens) | set(plain_tokens)
            lex_token_hits = sum(1 for w in self.lexicon if w in token_set)
            lex_substring_hits = 0
            if self.lexicon:
                joined = " " + norm_plain + " "
                joined_acc = " " + norm_accentless + " "
                for w in self.lexicon:
                    if len(w) >= 3 and ((" " + w + " ") in joined or w in joined_acc):
                        lex_substring_hits += 1

            if self.language.startswith("vi"):
                slang_hits = sum(1 for t in norm_plain.split() if t == "__vi_toxic_slang__")
                accentless_ratio = sum(1 for ch in raw_text if ch in "ăâđêôơưáàảãạắằẳẵặấầẩẫậéèẻẽẹếềểễệíìỉĩịóòỏõọốồổỗộớờởỡợúùủũụứừửữựýỳỷỹỵ") / max(alpha_chars, 1)
                deobf_hits = slang_hits
            else:
                slang_hits = 0
                accentless_ratio = 0.0
                deobf = normalize_english(raw_text, deobfuscate=True)
                raw_norm = normalize_english(raw_text, deobfuscate=False)
                deobf_hits = int(deobf != raw_norm)

            rows.append([
                np.log1p(char_len),
                np.log1p(token_count),
                unique_ratio,
                np.log1p(exclam_count),
                np.log1p(question_count),
                np.log1p(digit_count),
                uppercase_ratio,
                np.log1p(repeated_punct),
                np.log1p(repeated_chars),
                np.log1p(url_count),
                np.log1p(user_mention_count),
                np.log1p(lex_token_hits),
                np.log1p(lex_substring_hits),
                np.log1p(slang_hits),
                accentless_ratio,
                np.log1p(deobf_hits),
            ])
        return csr_matrix(np.asarray(rows, dtype=np.float32))


def make_language_features(
    language: str,
    lexicon: Optional[set[str]] = None,
    word_max_features: int = 50000,
    char_max_features: int = 50000,
    aux_max_features: int = 25000,
    word_ngram_range: Tuple[int, int] = (1, 3),
    char_ngram_range: Tuple[int, int] = (2, 6),
    min_df: int = 2,
    max_df: float = 0.98,
) -> FeatureUnion:
    language = language.lower()

    word_pipe = Pipeline([
        ("prep", LanguagePreprocessor(language=language, mode="word")),
        ("tfidf", TfidfVectorizer(
            analyzer="word",
            ngram_range=word_ngram_range,
            max_features=word_max_features,
            min_df=min_df,
            max_df=max_df,
            sublinear_tf=True,
            token_pattern=r"(?u)\b\w+\b",
        )),
    ])

    char_pipe = Pipeline([
        ("prep", LanguagePreprocessor(language=language, mode="vi_syllable" if language.startswith("vi") else "word")),
        ("tfidf", TfidfVectorizer(
            analyzer="char_wb",
            ngram_range=char_ngram_range,
            max_features=char_max_features,
            min_df=min_df,
            max_df=max_df,
            sublinear_tf=True,
        )),
    ])

    transformers = [("word", word_pipe), ("char", char_pipe)]

    if language.startswith("vi"):
        # Nhánh syllable giữ cách viết gốc tiếng Việt, giúp bắt câu không tách từ tốt.
        syllable_pipe = Pipeline([
            ("prep", LanguagePreprocessor(language=language, mode="vi_syllable")),
            ("tfidf", TfidfVectorizer(
                analyzer="word",
                ngram_range=(1, 4),
                max_features=aux_max_features,
                min_df=min_df,
                max_df=max_df,
                sublinear_tf=True,
                token_pattern=r"(?u)\b\w+\b",
            )),
        ])
        # Nhánh không dấu giúp bắt dữ liệu người dùng gõ thiếu dấu.
        accentless_char_pipe = Pipeline([
            ("prep", LanguagePreprocessor(language=language, mode="vi_accentless")),
            ("tfidf", TfidfVectorizer(
                analyzer="char_wb",
                ngram_range=(3, 6),
                max_features=aux_max_features,
                min_df=min_df,
                max_df=max_df,
                sublinear_tf=True,
            )),
        ])
        transformers.extend([("syllable", syllable_pipe), ("accentless_char", accentless_char_pipe)])
    else:
        # Nhánh word dài hơn cho tiếng Anh để bắt cụm toxic nhiều từ.
        long_word_pipe = Pipeline([
            ("prep", LanguagePreprocessor(language=language, mode="word")),
            ("tfidf", TfidfVectorizer(
                analyzer="word",
                ngram_range=(2, 4),
                max_features=aux_max_features,
                min_df=min_df,
                max_df=max_df,
                sublinear_tf=True,
                token_pattern=r"(?u)\b\w+\b",
            )),
        ])
        transformers.append(("long_word", long_word_pipe))

    stats_pipe = Pipeline([
        ("stats", ToxicTextStats(language=language, lexicon=lexicon)),
        ("scale", MaxAbsScaler()),
    ])
    transformers.append(("stats", stats_pipe))

    return FeatureUnion(transformer_list=transformers, n_jobs=None)


def read_dataset(
    path: str | Path,
    language: str,
    text_candidates: Sequence[str],
    label_candidates: Sequence[str],
    label_map: Optional[dict] = None,
    sample_n: Optional[int] = None,
    random_state: int = 42,
) -> pd.DataFrame:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Không tìm thấy file: {path}")

    df = pd.read_csv(path)
    text_col = next((c for c in text_candidates if c in df.columns), None)
    label_col = next((c for c in label_candidates if c in df.columns), None)
    if text_col is None:
        raise ValueError(f"Không tìm thấy cột text trong {path}. Columns: {list(df.columns)}")
    if label_col is None:
        raise ValueError(f"Không tìm thấy cột label trong {path}. Columns: {list(df.columns)}")

    out = df[[text_col, label_col]].rename(columns={text_col: "text", label_col: "label"}).copy()
    out["text"] = out["text"].fillna("").astype(str)
    label_map = label_map if label_map is not None else LABEL_MAP_DEFAULT
    out["label"] = out["label"].map(label_map).fillna(out["label"])
    out["label"] = pd.to_numeric(out["label"], errors="coerce")
    out = out.dropna(subset=["label"])
    out["label"] = out["label"].astype(int)
    out = out[out["label"].isin([0, 1])]

    # Dedup theo normalized text để giảm duplicate leakage giữa split.
    dedup_mode = "vi_accentless" if language.startswith("vi") else "word"
    out["_dedup_text"] = out["text"].map(lambda x: normalize_for_language(x, language=language, mode=dedup_mode))
    out = out[out["_dedup_text"].str.len() > 0]
    out = out.drop_duplicates(subset=["_dedup_text", "label"]).drop(columns=["_dedup_text"])

    if sample_n is not None and len(out) > sample_n:
        # Stratified sample gần đúng.
        parts = []
        for label, g in out.groupby("label"):
            n = max(1, int(sample_n * len(g) / len(out)))
            parts.append(g.sample(n=min(n, len(g)), random_state=random_state))
        out = pd.concat(parts).sample(frac=1, random_state=random_state).reset_index(drop=True)

    out["language"] = language
    return out.reset_index(drop=True)


def get_positive_proba(model: Any, X: Sequence[str]) -> np.ndarray:
    if hasattr(model, "predict_proba"):
        return model.predict_proba(X)[:, 1]
    if hasattr(model, "decision_function"):
        scores = model.decision_function(X)
        return 1 / (1 + np.exp(-scores))
    raise TypeError("Model không hỗ trợ predict_proba hoặc decision_function")


def find_best_threshold(
    y_true: Sequence[int],
    y_proba: Sequence[float],
    metric: str = "f1_toxic",
    min_precision_toxic: Optional[float] = None,
    min_recall_toxic: Optional[float] = None,
) -> Tuple[float, pd.DataFrame]:
    y_true = np.asarray(y_true)
    y_proba = np.asarray(y_proba)
    rows = []
    for thr in np.round(np.linspace(0.03, 0.97, 189), 3):
        pred = (y_proba >= thr).astype(int)
        precision, recall, f1, support = precision_recall_fscore_support(y_true, pred, labels=[0, 1], zero_division=0)
        rows.append({
            "threshold": float(thr),
            "f1_macro": float(f1_score(y_true, pred, average="macro", zero_division=0)),
            "f1_toxic": float(f1[1]),
            "precision_toxic": float(precision[1]),
            "recall_toxic": float(recall[1]),
            "precision_safe": float(precision[0]),
            "recall_safe": float(recall[0]),
        })
    df = pd.DataFrame(rows)
    filtered = df.copy()
    if min_precision_toxic is not None:
        filtered = filtered[filtered["precision_toxic"] >= min_precision_toxic]
    if min_recall_toxic is not None:
        filtered = filtered[filtered["recall_toxic"] >= min_recall_toxic]
    if filtered.empty:
        filtered = df.copy()
    if metric not in filtered.columns:
        raise ValueError(f"Metric không hợp lệ: {metric}. Columns: {list(filtered.columns)}")
    best = filtered.sort_values([metric, "recall_toxic", "precision_toxic"], ascending=False).iloc[0]
    return float(best["threshold"]), df


def evaluate_binary(model: Any, X: Sequence[str], y_true: Sequence[int], threshold: float = 0.5) -> Dict[str, Any]:
    y_true = np.asarray(y_true)
    proba = get_positive_proba(model, X)
    pred = (proba >= threshold).astype(int)
    report = classification_report(y_true, pred, target_names=["safe", "toxic"], output_dict=True, zero_division=0)
    metrics = {
        "threshold": float(threshold),
        "accuracy": float(accuracy_score(y_true, pred)),
        "f1_macro": float(f1_score(y_true, pred, average="macro", zero_division=0)),
        "f1_toxic": float(f1_score(y_true, pred, pos_label=1, zero_division=0)),
        "precision_toxic": float(report["toxic"]["precision"]),
        "recall_toxic": float(report["toxic"]["recall"]),
        "classification_report": report,
        "confusion_matrix": confusion_matrix(y_true, pred).tolist(),
    }
    if len(np.unique(y_true)) == 2:
        metrics["roc_auc"] = float(roc_auc_score(y_true, proba))
        metrics["pr_auc"] = float(average_precision_score(y_true, proba))
    return metrics


def save_json(obj: Dict[str, Any], path: str | Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)


def save_model_package(model: Any, threshold: float, path: str | Path, metadata: Optional[Dict[str, Any]] = None) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    package = {"model": model, "threshold": float(threshold), "metadata": metadata or {}}
    joblib.dump(package, path, compress=3)


def load_model_package(path: str | Path) -> Dict[str, Any]:
    obj = joblib.load(path)
    if isinstance(obj, dict) and "model" in obj:
        return obj
    return {"model": obj, "threshold": 0.5, "metadata": {}}


def predict_texts(texts: Sequence[str], package_or_path: Any, threshold: Optional[float] = None) -> pd.DataFrame:
    package = load_model_package(package_or_path) if isinstance(package_or_path, (str, Path)) else package_or_path
    model = package["model"]
    thr = float(package.get("threshold", 0.5) if threshold is None else threshold)
    proba = get_positive_proba(model, texts)
    pred = (proba >= thr).astype(int)
    return pd.DataFrame({
        "text": list(texts),
        "label": pred.astype(int),
        "prob_safe": (1 - proba).astype(float),
        "prob_toxic": proba.astype(float),
        "threshold": thr,
    })
