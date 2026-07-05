"""Keyword extraction for the per-keyword FTS fallback.

Port of OpenClaw's ``extractKeywords`` (packages/memory-host-sdk/src/host/
query-expansion.ts) for the default ``unicode61`` FTS tokenizer. The stop-word
sets are generated verbatim from the upstream source.
"""

from __future__ import annotations

import re
import unicodedata

STOP_WORDS_EN = frozenset(
    (
        "a", "an", "the", "this", "that", "these", "those", "i", "me", "my", "we", "our",
        "you", "your", "he", "she", "it", "they", "them", "is", "are", "was", "were", "be",
        "been", "being", "have", "has", "had", "do", "does", "did", "will", "would", "could",
        "should", "can", "may", "might", "in", "on", "at", "to", "for", "of", "with", "by",
        "from", "about", "into", "through", "during", "before", "after", "above", "below",
        "between", "under", "over", "and", "or", "but", "if", "then", "because", "as", "while",
        "when", "where", "what", "which", "who", "how", "why", "yesterday", "today",
        "tomorrow", "earlier", "later", "recently", "before", "ago", "just", "now", "thing",
        "things", "stuff", "something", "anything", "everything", "nothing", "please", "help",
        "find", "show", "get", "tell", "give",
    )
)

STOP_WORDS_ES = frozenset(
    (
        "el", "la", "los", "las", "un", "una", "unos", "unas", "este", "esta", "ese", "esa",
        "yo", "me", "mi", "nosotros", "nosotras", "tu", "tus", "usted", "ustedes", "ellos",
        "ellas", "de", "del", "a", "en", "con", "por", "para", "sobre", "entre", "y", "o",
        "pero", "si", "porque", "como", "es", "son", "fue", "fueron", "ser", "estar", "haber",
        "tener", "hacer", "ayer", "hoy", "mañana", "antes", "despues", "después", "ahora",
        "recientemente", "que", "qué", "cómo", "cuando", "cuándo", "donde", "dónde", "porqué",
        "favor", "ayuda",
    )
)

STOP_WORDS_PT = frozenset(
    (
        "o", "a", "os", "as", "um", "uma", "uns", "umas", "este", "esta", "esse", "essa", "eu",
        "me", "meu", "minha", "nos", "nós", "você", "vocês", "ele", "ela", "eles", "elas",
        "de", "do", "da", "em", "com", "por", "para", "sobre", "entre", "e", "ou", "mas", "se",
        "porque", "como", "é", "são", "foi", "foram", "ser", "estar", "ter", "fazer", "ontem",
        "hoje", "amanhã", "antes", "depois", "agora", "recentemente", "que", "quê", "quando",
        "onde", "porquê", "favor", "ajuda",
    )
)

STOP_WORDS_AR = frozenset(
    (
        "ال", "و", "أو", "لكن", "ثم", "بل", "أنا", "نحن", "هو", "هي", "هم", "هذا", "هذه",
        "ذلك", "تلك", "هنا", "هناك", "من", "إلى", "الى", "في", "على", "عن", "مع", "بين", "ل",
        "ب", "ك", "كان", "كانت", "يكون", "تكون", "صار", "أصبح", "يمكن", "ممكن", "بالأمس",
        "امس", "اليوم", "غدا", "الآن", "قبل", "بعد", "مؤخرا", "لماذا", "كيف", "ماذا", "متى",
        "أين", "هل", "من فضلك", "فضلا", "ساعد",
    )
)

STOP_WORDS_KO = frozenset(
    (
        "은", "는", "이", "가", "을", "를", "의", "에", "에서", "로", "으로", "와", "과", "도", "만", "까지",
        "부터", "한테", "에게", "께", "처럼", "같이", "보다", "마다", "밖에", "대로", "나", "나는", "내가", "나를", "너",
        "우리", "저", "저희", "그", "그녀", "그들", "이것", "저것", "그것", "여기", "저기", "거기", "있다", "없다", "하다",
        "되다", "이다", "아니다", "보다", "주다", "오다", "가다", "것", "거", "등", "수", "때", "곳", "중", "분", "잘",
        "더", "또", "매우", "정말", "아주", "많이", "너무", "좀", "그리고", "하지만", "그래서", "그런데", "그러나", "또는",
        "그러면", "왜", "어떻게", "뭐", "언제", "어디", "누구", "무엇", "어떤", "어제", "오늘", "내일", "최근", "지금",
        "아까", "나중", "전에", "제발", "부탁",
    )
)

STOP_WORDS_JA = frozenset(
    (
        "これ", "それ", "あれ", "この", "その", "あの", "ここ", "そこ", "あそこ", "する", "した", "して", "です", "ます",
        "いる", "ある", "なる", "できる", "の", "こと", "もの", "ため", "そして", "しかし", "また", "でも", "から", "まで",
        "より", "だけ", "なぜ", "どう", "何", "いつ", "どこ", "誰", "どれ", "昨日", "今日", "明日", "最近", "今", "さっき",
        "前", "後",
    )
)

STOP_WORDS_ZH = frozenset(
    (
        "我", "我们", "你", "你们", "他", "她", "它", "他们", "这", "那", "这个", "那个", "这些", "那些", "的", "了",
        "着", "过", "得", "地", "吗", "呢", "吧", "啊", "呀", "嘛", "啦", "是", "有", "在", "被", "把", "给",
        "让", "用", "到", "去", "来", "做", "说", "看", "找", "想", "要", "能", "会", "可以", "和", "与", "或",
        "但", "但是", "因为", "所以", "如果", "虽然", "而", "也", "都", "就", "还", "又", "再", "才", "只", "之前",
        "以前", "之后", "以后", "刚才", "现在", "昨天", "今天", "明天", "最近", "东西", "事情", "事", "什么", "哪个",
        "哪些", "怎么", "为什么", "多少", "请", "帮", "帮忙", "告诉",
    )
)

_HIRAGANA_KATAKANA_RE = re.compile("[぀-ヿ]")
_JAPANESE_PART_RE = re.compile(
    "[a-z0-9_]+|[゠-ヿー]+|[一-鿿]+|[぀-ゟ]{2,}"
)
_KANJI_ONLY_RE = re.compile("^[一-鿿]+$")
_CJK_RE = re.compile("[一-鿿]")
_HANGUL_RE = re.compile("[가-힯ㄱ-ㅣ]")
_HANGUL_SYLLABLE_RE = re.compile("[가-힯]")
_ASCII_ALPHA_RE = re.compile(r"^[a-zA-Z]+$")
_ASCII_DIGITS_RE = re.compile(r"^[0-9]+$")
_ASCII_WORD_RE = re.compile(r"^[a-z0-9_]+$", re.IGNORECASE)

# Longest-first so compound particles win over their single-syllable suffixes.
_KO_TRAILING_PARTICLES = sorted(
    (
        "에서", "으로", "에게", "한테", "처럼", "같이", "보다", "까지", "부터", "마다",
        "밖에", "대로", "은", "는", "이", "가", "을", "를", "의", "에", "로", "와",
        "과", "도", "만",
    ),
    key=len,
    reverse=True,
)


def is_query_stop_word_token(token: str) -> bool:
    """True for low-value conversational tokens that should not drive FTS matching."""
    return (
        token in STOP_WORDS_EN
        or token in STOP_WORDS_ES
        or token in STOP_WORDS_PT
        or token in STOP_WORDS_AR
        or token in STOP_WORDS_ZH
        or token in STOP_WORDS_KO
        or token in STOP_WORDS_JA
    )


def _is_valid_keyword(token: str) -> bool:
    if not token:
        return False
    # Skip very short English words (likely stop words or fragments).
    if _ASCII_ALPHA_RE.match(token) and len(token) < 3:
        return False
    # Skip pure numbers (not useful for semantic search).
    if _ASCII_DIGITS_RE.match(token):
        return False
    # Skip tokens that are all punctuation or symbols.
    if all(unicodedata.category(char)[0] in {"P", "S"} for char in token):
        return False
    return True


def _split_segments(text: str) -> list[str]:
    # Mirrors the upstream /[\s\p{P}]+/u split: whitespace and any Unicode
    # punctuation (including connector punctuation such as "_") separate
    # segments.
    segments: list[str] = []
    current: list[str] = []
    for char in text:
        if char.isspace() or unicodedata.category(char).startswith("P"):
            if current:
                segments.append("".join(current))
                current = []
            continue
        current.append(char)
    if current:
        segments.append("".join(current))
    return segments


def _strip_korean_trailing_particle(token: str) -> str | None:
    for particle in _KO_TRAILING_PARTICLES:
        if len(token) > len(particle) and token.endswith(particle):
            return token[: -len(particle)]
    return None


def _is_useful_korean_stem(stem: str) -> bool:
    # Prevent bogus one-syllable stems from words like "논의" -> "논".
    if _HANGUL_SYLLABLE_RE.search(stem):
        return len(stem) >= 2
    # Keep stripped ASCII stems for mixed tokens like "API를" -> "api".
    return bool(_ASCII_WORD_RE.match(stem))


def _tokenize(text: str) -> list[str]:
    """Tokenizer handling English, Chinese, Korean, and Japanese text.

    For Chinese, characters are split into unigrams plus bigrams since there is
    no proper segmenter. For English, text splits on whitespace and punctuation.
    """
    tokens: list[str] = []
    normalized = text.strip().lower() if isinstance(text, str) else ""

    for segment in _split_segments(normalized):
        if _HIRAGANA_KATAKANA_RE.search(segment):
            # Japanese text often mixes scripts (kanji/kana/ASCII) without
            # spaces. Extract script-specific chunks so technical terms like
            # "API" / "バグ" are retained.
            for part in _JAPANESE_PART_RE.findall(segment):
                if _KANJI_ONLY_RE.match(part):
                    tokens.append(part)
                    tokens.extend(part[i : i + 2] for i in range(len(part) - 1))
                else:
                    tokens.append(part)
        elif _CJK_RE.search(segment):
            # Chinese: unigrams plus bigrams for phrase matching.
            chars = [char for char in segment if _CJK_RE.match(char)]
            tokens.extend(chars)
            tokens.extend(chars[i] + chars[i + 1] for i in range(len(chars) - 1))
        elif _HANGUL_RE.search(segment):
            # For Korean (Hangul syllables and jamo), keep the word as-is
            # unless it is effectively a stop word once trailing particles are
            # removed.
            stem = _strip_korean_trailing_particle(segment)
            stem_is_stop_word = stem is not None and stem in STOP_WORDS_KO
            if segment not in STOP_WORDS_KO and not stem_is_stop_word:
                tokens.append(segment)
            # Also emit particle-stripped stems when they are useful keywords.
            if stem and stem not in STOP_WORDS_KO and _is_useful_korean_stem(stem):
                tokens.append(stem)
        else:
            tokens.append(segment)

    return tokens


def extract_keywords(query: str) -> list[str]:
    """Extract keywords from a conversational query for FTS search.

    Examples:
    - "that thing we discussed about the API" -> ["discussed", "api"]
    - "之前讨论的那个方案" -> ["之", "讨", "论", ...bigrams...]
    - "what was the solution for the bug" -> ["solution", "bug"]
    """
    keywords: list[str] = []
    seen: set[str] = set()
    for token in _tokenize(query):
        if is_query_stop_word_token(token):
            continue
        if not _is_valid_keyword(token):
            continue
        if token in seen:
            continue
        seen.add(token)
        keywords.append(token)
    return keywords
