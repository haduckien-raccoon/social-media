import re
import json
import unicodedata
import ahocorasick
import socket
import langid
import requests
import config.settings as settings

from apps.moderation.models import (
	ContentModerationLog,
	ModerationAction,
	ModerationSource,
	ModerationStatus
)

# ==========================================
# DATASET PATHS
# ==========================================

VI_BADWORDS_PATH = (
	"apps/moderation/datasets/vi_badwords.json"
)

EN_BADWORDS_PATH = (
	"apps/moderation/datasets/en_badwords.json"
)

# ==========================================
# LOAD BADWORDS
# ==========================================

def load_json_words(path):

	with open(
		path,
		"r",
		encoding="utf-8"
	) as f:

		return json.load(f)

# ==========================================
# NORMALIZE TEXT
# ==========================================

def normalize_text(text):

	text = str(text).lower()

	text = unicodedata.normalize(
		"NFKC",
		text
	)

	# remove special chars
	text = re.sub(
		r"[^a-zA-Z0-9À-ỹ\\s]",
		" ",
		text
	)

	# remove multiple spaces
	text = re.sub(
		r"\\s+",
		" ",
		text
	).strip()

	return text

# ==========================================
# LOAD WORDS
# ==========================================

print("[MODERATION] Loading badwords...")

vi_words = load_json_words(
	VI_BADWORDS_PATH
)

en_words = load_json_words(
	EN_BADWORDS_PATH
)

ALL_WORDS = set()

for word in vi_words + en_words:

	word = str(word).strip().lower()

	if len(word) >= 2:

		ALL_WORDS.add(word)

print(
	f"[MODERATION] Loaded "
	f"{len(ALL_WORDS)} badwords"
)

# ==========================================
# BUILD AHO-CORASICK
# ==========================================

AUTOMATON = ahocorasick.Automaton()

for idx, word in enumerate(ALL_WORDS):

	AUTOMATON.add_word(
		word,
		(idx, word)
	)

AUTOMATON.make_automaton()

print("[MODERATION] Automaton ready")

# ==========================================
# WORD BOUNDARY CHECK
# ==========================================

def is_word_boundary(text, start, end):

	left_ok = (
		start == 0
		or not text[start - 1].isalnum()
	)

	right_ok = (
		end >= len(text)
		or not text[end].isalnum()
	)

	return left_ok and right_ok

# ==========================================
# MAIN MODERATION
# ==========================================

def moderate_text(text):

	normalized = normalize_text(text)

	violations = set()

	for end_index, (_, word) in AUTOMATON.iter(normalized):

		start_index = (
			end_index - len(word) + 1
		)

		if not is_word_boundary(
			normalized,
			start_index,
			end_index + 1
		):
			continue

		violations.add(word)

	violations = sorted(list(violations))

	blocked = len(violations) > 0

	# simple risk score
	risk_score = round(
		min(len(violations) * 0.25, 1.0),
		2
	)

	return {
		"blocked": blocked,
		"violations": violations,
		"risk_score": risk_score,
		"normalized_text": normalized
	}

# ==========================================
# SAVE MODERATION LOG
# ==========================================

def save_moderation_log(
	*,
	actor,
	target_type,
	target_id,
	result,
	reason=""
):

	return ContentModerationLog.objects.create(

		actor=actor,

		target_type=target_type,

		target_id=target_id,

		action=ModerationAction.FLAG,

		status=ModerationStatus.FLAGGED,

		source=ModerationSource.REGEX,

		risk_score=result["risk_score"],

		matched_keywords=result["violations"],

		reason=reason,

		is_automatic=True
	)

def ai_help_report(text):
	#Lấy địa chỉ IP của server:
	url_server = settings.AI_SERVICE_URL
	#gửi đến cổng 8082 với đường link: http://<ip_server>:8082/predict
	url = f"{url_server}/predict"
	#dùng lang để phân tích thuộc tiếng việt, tiếng anh hay tiếng khác
	lang, _ = langid.classify(text)
	#tạo payload để gửi đi
	if lang == "vi":
		payload = {
			"text": text,
			"language": "vi"
		}
	elif lang == "en":
		payload = {
			"text": text,
			"language": "en"
		}
	else:
		#Trả về kết quả lỗi nếu không phải tiếng Việt hoặc tiếng Anh
		return {
			"error": "Unsupported language"
		}
	#Gửi yêu cầu POST đến AI service
	print(f"Sending text to AI service for analysis: {text}, Language: {lang}")
	try:
		response = requests.post(
			url,
			json=payload,
			timeout=5
		)
		response.raise_for_status()
		return response.json()
	except requests.RequestException as e:
		return {
			"error": str(e)
		}
	