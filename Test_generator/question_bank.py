"""
Загрузка JSON-учебников и отбор кандидатов для приложения.

Для режима «учебник»: нейросеть используется только чтобы выбрать номера из списка,
сами формулировки берутся только из JSON.
"""
from __future__ import annotations

import json
import re
import logging
import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator, Optional

logger = logging.getLogger(__name__)

_STOP = frozenset(
    """
    и в во на не с со к у о об от по за для при из как то а но же ли бы что это
    чтобы или все также только ещё еще их его ее её им
    древний древняя древнее древнего древней древние древних древним древними
    мир мира миру мире мировой история истории исторический историческая исторические
    """.split()
)
_TOPIC_GROUPS: dict[str, tuple[str, ...]] = {
    "rome": (
        "рим", "римск", "римлян", "итал", "латин", "этруск", "патриц", "плеб",
        "сенат", "консул", "трибун", "республик", "цезар", "август",
        "октавиан", "гладиатор", "колиз", "форум", "легион", "пуничес",
        "карфаген", "ганнибал", "пирр", "самнит", "понтифик", "вандал",
        "вестгот", "аттил", "принципат", "доминат",
    ),
    "greece": (
        "греци", "грец", "грек", "греческ", "эллад", "эллин", "афин", "спарт",
        "полис", "олимпи", "гомер", "ахилл", "перикл", "солон", "македон",
        "александр", "марафон", "саламин", "пелопоннес",
    ),
    "egypt": (
        "егип", "ниль", "фараон", "пирами", "сфинкс", "мум", "осирис",
        "исида", "амон", "иероглиф", "саркофаг",
    ),
    "mesopotamia": (
        "междуреч", "месопотам", "шумер", "вавилон", "ассир", "аккад",
        "тигр", "евфрат", "хаммурапи", "клинопис",
    ),
    "india": ("инди", "инд", "ганг", "варн", "будд", "ашок", "брахман"),
    "china": ("кита", "хуанхэ", "янцз", "конфуц", "цинь", "хань"),
    "persia": ("перс", "персид", "дарий", "ксеркс", "ахеменид"),
    "levant": (
        "палестин", "ханаан", "иуд", "иудей", "еврей", "израил", "иерусалим",
        "моисе", "давид", "соломон", "финик", "филистим",
    ),
    "primitive": (
        "первобыт", "каменн", "палеолит", "неолит", "мезолит", "родов",
        "охотник", "собират", "тотем", "общин",
    ),
}
_GROUP_EXCLUSIVE = tuple(_TOPIC_GROUPS)

_TOPIC_ALIASES: dict[str, tuple[str, ...]] = {
    "рим": _TOPIC_GROUPS["rome"],
    "римск": _TOPIC_GROUPS["rome"],
    "греци": _TOPIC_GROUPS["greece"],
    "грец": _TOPIC_GROUPS["greece"],
    "егип": _TOPIC_GROUPS["egypt"],
    "междуреч": _TOPIC_GROUPS["mesopotamia"],
    "месопотам": _TOPIC_GROUPS["mesopotamia"],
    "инди": _TOPIC_GROUPS["india"],
    "кита": _TOPIC_GROUPS["china"],
    "перс": _TOPIC_GROUPS["persia"],
    "палестин": _TOPIC_GROUPS["levant"],
    "иуд": _TOPIC_GROUPS["levant"],
    "еврей": _TOPIC_GROUPS["levant"],
    "первобыт": _TOPIC_GROUPS["primitive"],
}
_TOKEN_RE = re.compile(r"[\w\-]+", re.UNICODE)


def _tokens(text: str) -> list[str]:
    if not text:
        return []
    out: list[str] = []
    for m in _TOKEN_RE.finditer(text.lower()):
        t = m.group(0)
        if len(t) < 2 or t in _STOP:
            continue
        out.append(t)
    return out


def _token_set(text: str) -> set[str]:
    return set(_tokens(text))


def _contains_any(text_l: str, needles: tuple[str, ...]) -> bool:
    return any(k in text_l for k in needles)


def _topic_groups(text_l: str) -> set[str]:
    return {
        name
        for name, needles in _TOPIC_GROUPS.items()
        if _contains_any(text_l, needles)
    }


def _topic_search_terms(topic: str, extra: str) -> set[str]:
    terms = _token_set(topic) | _token_set(extra)
    lower = f"{topic}\n{extra}".lower()
    for key, aliases in _TOPIC_ALIASES.items():
        if key in lower:
            terms.update(aliases)
    return {t for t in terms if t not in _STOP}


def _matches_topic_guard(topic_l: str, extra_l: str, blob_l: str) -> bool:
    intents = _topic_groups(f"{topic_l}\n{extra_l}")
    if not intents:
        return True
    return any(_contains_any(blob_l, _TOPIC_GROUPS[g]) for g in intents)


def _geo_match_multiplier(topic_l: str, blob_l: str) -> float:
    """
    Снижает «утечку» между крупными темами (Левант vs Греция и т.д.), когда общие
    слова вроде «древняя» давали высокие баллы чужому разделу.
    Множители умножаются — обычно остаются 1.0.
    """
    if not topic_l or not blob_l:
        return 1.0
    mult = 1.0

    greek_intent = any(
        k in topic_l
        for k in (
            "греция",
            "греции",
            "греческ",
            "эллад",
            "грек",
            "геллен",
            "афины",
            "спарта",
            "полис",
        )
    )
    levant_blob = any(
        k in blob_l
        for k in (
            "палестин",
            "ханаан",
            "филистим",
            "еврейск",
            "иудей",
            "иудаизм",
            "моисе",
            "иерусалим",
        )
    )
    greek_blob = any(
        k in blob_l
        for k in (
            "грец",
            "эллад",
            "афинск",
            "спартан",
            "полис",
            "микен",
            "минойск",
            "кносск",
            "дорийск",
            "ионийск",
            "эгейск",
            "гомеров",
            "греческ",
            "афины",
            "спарте",
            "афинском",
            "эллада",
        )
    )

    if greek_intent and levant_blob and not greek_blob:
        mult *= 0.08

    levant_intent = any(k in topic_l for k in ("палестин", "ханаан", "иудей", "еврей"))
    if levant_intent and greek_blob and not levant_blob:
        mult *= 0.12

    intents = _topic_groups(topic_l)
    if intents:
        has_target_group = any(_contains_any(blob_l, _TOPIC_GROUPS[g]) for g in intents)
        if not has_target_group:
            mult *= 0.03
        else:
            other_hits = [
                g for g in _GROUP_EXCLUSIVE
                if g not in intents and _contains_any(blob_l, _TOPIC_GROUPS[g])
            ]
            if other_hits:
                mult *= 0.7

    return mult


def _clamp_diff(raw: str) -> int:
    s = (raw or "medium").strip().lower()
    if s.startswith("easy"):
        return 1
    if "hard" in s:
        return 3
    return 2


def question_difficulty_numeric(q_raw: dict) -> int:
    d = q_raw.get("difficulty") if isinstance(q_raw.get("difficulty"), dict) else {}
    return max(_clamp_diff(str(d.get("primary", "medium"))), _clamp_diff(str(d.get("secondary", "medium"))))


def bank_question_difficulty_mode(q_raw: dict) -> str:
    """easy | medium | hard по полю difficulty первичного текста."""
    n = question_difficulty_numeric(q_raw)
    return {1: "easy", 2: "medium", 3: "hard"}[max(1, min(3, n))]


def user_difficulty_cap(mode: str) -> int:
    m = (mode or "medium").strip().lower()
    if m == "easy":
        return 1
    if m == "hard":
        return 3
    return 2


def iter_bank_json_files(folder: Path) -> Iterator[Path]:
    for path in sorted(folder.glob("*.json")):
        if path.name.startswith("_"):
            continue
        if path.name.lower() == "manifest.json":
            continue
        # Объединённый файл без section в meta даёт один «фиктивный» раздел на все
        # вопросы и полностью дублирует фрагменты — только мешает ранжированию.
        if "merged" in path.name.lower():
            continue
        yield path


@dataclass(frozen=True)
class BankItem:
    raw: dict
    source_file: str
    section_title: str
    textbook_title: str

    def uid(self) -> str:
        qid = self.raw.get("id")
        if qid:
            return f"{self.source_file}::{qid}"
        return f"{self.source_file}::{hash((self.raw.get('question') or '')[:100])}"

    def search_blob(self) -> str:
        parts: list[str] = [self.section_title, self.textbook_title,
                            self.raw.get("question") or self.raw.get("text") or ""]
        tags = self.raw.get("tags")
        if isinstance(tags, dict):
            for key in ("themes", "concepts", "entities"):
                v = tags.get(key)
                if isinstance(v, list):
                    parts.append(" ".join(str(x) for x in v))
        return "\n".join(parts)


class QuestionBankIndex:
    def __init__(self, folder: str):
        self.folder = Path(folder)
        self.questions: list[BankItem] = []
        if not self.folder.is_dir():
            raise FileNotFoundError(f"Не папка: {self.folder}")
        for path in iter_bank_json_files(self.folder):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception as e:
                logger.warning("Пропуск %s: %s", path.name, e)
                continue
            meta = data.get("meta") if isinstance(data.get("meta"), dict) else {}
            section = (meta.get("section") or path.stem).strip()
            tb = (meta.get("textbook") or "").strip()
            qs = data.get("questions")
            if not isinstance(qs, list):
                continue
            for item in qs:
                if isinstance(item, dict):
                    self.questions.append(
                        BankItem(item, path.name, section, tb)
                    )
        if not self.questions:
            raise ValueError("В папке нет валидных вопросов (*.json).")

    def count(self) -> int:
        return len(self.questions)

    @staticmethod
    def score_item(bi: BankItem, topic: str, extra: str) -> float:
        blob_l = bi.search_blob().lower()
        combined = f"{topic}\n{extra}".strip().lower()
        if not combined:
            return 0.01
        score = 0.0
        topic_l = topic.lower().strip()
        sec_l = (bi.section_title or "").lower()
        if topic_l and len(topic_l) >= 6 and topic_l in sec_l:
            score += 12.0
        if topic_l and len(topic_l) >= 4 and sec_l in topic_l:
            score += 10.0
        src = bi.raw.get("source") if isinstance(bi.raw.get("source"), dict) else {}
        para = str(src.get("paragraph", "")).lower()
        for m in re.finditer(r"[§]\s*\d+", combined):
            if m.group(0).replace(" ", "") in para.replace(" ", ""):
                score += 8.0
        key_toks = _topic_search_terms(topic, extra)
        if not key_toks:
            return 1.0 + score
        hit = len(key_toks & _token_set(blob_l))
        score += float(hit)
        for t in key_toks:
            if len(t) >= 5 and t in blob_l:
                score += 0.35
        intents = _topic_groups(combined)
        for g in intents:
            if _contains_any(blob_l, _TOPIC_GROUPS[g]):
                score += 8.0
        score *= _geo_match_multiplier(topic_l, blob_l)
        return max(score, 0.01)


def filter_scored_items(
    index: QuestionBankIndex,
    topic: str,
    extra: str,
    difficulty_mode: str,
    pool_size: int,
    difficulty_cap_override: Optional[int] = None,
) -> list[tuple[float, BankItem]]:
    cap = (
        difficulty_cap_override
        if difficulty_cap_override is not None
        else user_difficulty_cap(difficulty_mode)
    )
    scored: list[tuple[float, BankItem]] = []
    topic_l = topic.lower().strip()
    extra_l = extra.lower().strip()
    for bi in index.questions:
        if question_difficulty_numeric(bi.raw) > cap:
            continue
        if not _matches_topic_guard(topic_l, extra_l, bi.search_blob().lower()):
            continue
        sc = QuestionBankIndex.score_item(bi, topic, extra)
        scored.append((sc, bi))
    scored.sort(key=lambda t: -t[0])
    return scored[: max(pool_size, 1)]


def source_line_from_raw(q: dict) -> str:
    src = q.get("source") if isinstance(q.get("source"), dict) else {}
    para = src.get("paragraph", "")
    page = src.get("page")
    bits: list[str] = []
    if para:
        bits.append(f"§{para}".replace("§§", "§"))
    if page is not None and str(page).strip() != "":
        bits.append(f"стр. {page}")
    return " · ".join(bits)


def formatted_source_page(raw: dict) -> str:
    """Строка источника для UI / валидации (желательно с цифрой)."""
    src = raw.get("source") if isinstance(raw.get("source"), dict) else {}
    page = src.get("page")
    para = src.get("paragraph")
    if page is not None and str(page).strip() != "":
        return f"стр. {page}"
    if para is not None and str(para).strip() != "":
        return str(para).strip()
    return "стр. не указана"


def normalized_paragraph_for_ui(raw_source: dict) -> str:
    """Текст для подписи «Параграф: …». Пустая строка, если параграфа нет."""
    if not isinstance(raw_source, dict):
        return ""
    para = raw_source.get("paragraph")
    if para is None:
        return ""
    s = _nfkc_spaces(str(para).strip())
    if not s:
        return ""
    if s.startswith("§"):
        return s.replace("§ §", "§").strip()
    if re.fullmatch(r"\d{1,3}", s):
        return f"§{s}"
    return s


def _nfkc_spaces(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def paragraph_hint_digits_from_section(section: str) -> str:
    """Подсказка номера блока («Введение — 3. …», «§ 12»); только цифры."""
    if not section or not isinstance(section, str):
        return ""
    s = section.strip()
    m = re.search(r"[—\-–]\s*(\d{1,2})\s*(?:[\.\)]|\s|$)", s)
    if m:
        return m.group(1)
    m2 = re.search(r"\b(?:§|параграф|п\.)\s*(\d{1,4})\b", s, re.I)
    if m2:
        return m2.group(1)
    return ""


def paragraph_label_for_bank_question(raw: dict, section_title: str = "") -> str:
    """Текст для бейджа «Параграф»: явное поле или номер из meta.section / раздела файла."""
    p = normalized_paragraph_for_ui(
        raw.get("source") if isinstance(raw.get("source"), dict) else {},
    )
    if p:
        return p
    meta = raw.get("meta") if isinstance(raw.get("meta"), dict) else {}
    sec_line = str(meta.get("section") or "").strip()
    hint = paragraph_hint_digits_from_section(sec_line)
    if not hint:
        hint = paragraph_hint_digits_from_section(section_title or "")
    if hint.isdigit() and len(hint) <= 4:
        return f"§{hint}"
    return ""

def is_well_formed_open(raw: dict) -> bool:
    txt = str(raw.get("question") or raw.get("text") or "").strip()
    if len(txt) < 10:
        return False
    ca = raw.get("correct_answer")
    if isinstance(ca, str) and ca.strip():
        return True
    cans = raw.get("correct_answers")
    return bool(isinstance(cans, list) and cans and str(cans[0]).strip())


def chronology_solution_sequence(raw: dict) -> list[str]:
    """Подписи событий в правильном порядке для chronology."""
    items = raw.get("items")
    if not isinstance(items, list):
        return []
    labels = [str(x).strip() for x in items if str(x).strip()]
    cans = raw.get("correct_answers")
    if isinstance(cans, list) and len(cans) >= 3:
        return [str(x).strip() for x in cans if str(x).strip()]
    co = raw.get("correct_order")
    if not isinstance(co, list):
        return []
    out: list[str] = []
    for idx in co:
        if isinstance(idx, int) and 0 <= idx < len(labels):
            out.append(labels[idx])
    return out


def is_well_formed_chronology(raw: dict) -> bool:
    items = raw.get("items")
    if not isinstance(items, list) or len(items) < 3:
        return False
    seq = chronology_solution_sequence(raw)
    return len(seq) >= 3


def is_well_formed_matching(raw: dict) -> bool:
    lp = raw.get("left_items")
    rp = raw.get("right_items")
    cp = raw.get("correct_pairs")
    if not isinstance(lp, list) or not isinstance(rp, list) or not isinstance(cp, list):
        return False
    if len(cp) < 2:
        return False
    lids: dict[str, str] = {}
    for x in lp:
        if isinstance(x, dict) and x.get("id") is not None:
            lids[str(x["id"])] = str(x.get("text", "")).strip()
    rids: dict[str, str] = {}
    for x in rp:
        if isinstance(x, dict) and x.get("id") is not None:
            rids[str(x["id"])] = str(x.get("text", "")).strip()
    for p in cp:
        if not isinstance(p, dict):
            return False
        lt = p.get("left")
        rt = p.get("right")
        if lt is None or rt is None:
            return False
        if str(lt) not in lids or str(rt) not in rids:
            return False
        if not lids[str(lt)] or not rids[str(rt)]:
            return False
    return True


UI_TO_BANK_TYPES = {
    "test": frozenset({"single_choice"}),
    "open": frozenset({"open"}),
    "match": frozenset({"matching", "match"}),
    "chronology": frozenset({"chronology"}),
}

# Для этих типов при отборе из учебника: смотрим весь отсортированный список (не обрезаем топ-N),
# и при нехватке кандидатов под выбранную сложность постепенно ослабляем потолок до «сложной».
_TYPED_BANK_RELAX = frozenset({"open", "match", "chronology"})


def bank_json_matches_ui(bi: BankItem, ui_question_type: str) -> bool:
    """Проверка типа JSON и минимальной целостности под формат UI."""
    t = str(bi.raw.get("type") or "").strip().lower()
    allowed = UI_TO_BANK_TYPES.get(ui_question_type, frozenset())
    if ui_question_type == "test":
        return t == "single_choice" and is_well_formed_mc(bi.raw)
    if t not in allowed:
        return False
    if ui_question_type == "open":
        return is_well_formed_open(bi.raw)
    if ui_question_type == "match":
        return is_well_formed_matching(bi.raw)
    if ui_question_type == "chronology":
        return is_well_formed_chronology(bi.raw)
    return False


def filter_scored_typed_items(
    index: QuestionBankIndex,
    topic: str,
    extra: str,
    difficulty_mode: str,
    pool_size: int,
    ui_question_type: str,
) -> list[tuple[float, BankItem]]:
    """Отфильтрованный по типу UI пул с тем же скорингом, что и filter_scored_items."""
    base_cap = user_difficulty_cap(difficulty_mode)

    if ui_question_type in _TYPED_BANK_RELAX:
        wide = len(index.questions)
        cap_chain = list(range(base_cap, 4))
        if not cap_chain:
            cap_chain = [3]
    else:
        wide = max(pool_size * 5, pool_size + 32)
        cap_chain = [base_cap]

    for cap in cap_chain:
        scored_all = filter_scored_items(
            index,
            topic,
            extra,
            difficulty_mode,
            pool_size=wide,
            difficulty_cap_override=cap,
        )
        out: list[tuple[float, BankItem]] = []
        for s, bi in scored_all:
            if bank_json_matches_ui(bi, ui_question_type):
                out.append((s, bi))
            if len(out) >= pool_size:
                break
        if out:
            return out[: max(pool_size, 1)]
    return []


def is_well_formed_mc(raw: dict) -> bool:
    if not isinstance(raw, dict):
        return False
    opts = raw.get("options")
    if not isinstance(opts, list):
        return False
    cleaned = [str(o).strip() for o in opts if str(o).strip()]
    if len(cleaned) != 4:
        return False
    cans = raw.get("correct_answers")
    if not isinstance(cans, list) or not cans:
        return False
    ca = str(cans[0]).strip()
    if not ca:
        return False
    return any(ca == o for o in cleaned)


def bank_folder_fingerprint(folder: str) -> str:
    """Устойчивый кэш-ключ по составу JSON в папке."""
    p = Path(folder)
    parts: list[str] = []
    for f in iter_bank_json_files(p):
        try:
            st = f.stat()
            parts.append(f"{f.name}:{st.st_mtime_ns}:{st.st_size}")
        except OSError:
            parts.append(f.name)
    blob = "|".join(parts)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:20]


def filter_scored_mc_items(
    index: QuestionBankIndex,
    topic: str,
    extra: str,
    difficulty_mode: str,
    pool_size: int,
) -> list[tuple[float, BankItem]]:
    """Как filter_scored_items, но только вопросы с 4 вариантами и верным ответом."""
    wide = max(pool_size * 4, pool_size + 16)
    scored = filter_scored_items(index, topic, extra, difficulty_mode, pool_size=wide)
    out = [(s, bi) for s, bi in scored if is_well_formed_mc(bi.raw)]
    return out[: max(pool_size, 1)]


def bank_item_to_lines(bi: BankItem, max_q: int = 400) -> tuple[str, str]:
    """Короткая строка для списка номеров + полный текст вопроса для контекста."""
    q = bi.raw
    text = (q.get("question") or q.get("text") or "").strip().replace("\n", " ")
    if len(text) > max_q:
        text = text[: max_q - 1] + "…"
    meta = source_line_from_raw(q)
    short = f"[{bi.section_title[:50]}] {meta} | {text}"
    opts = q.get("options") if isinstance(q.get("options"), list) else []
    opt_s = " | ".join(str(o) for o in opts[:6])
    cans = q.get("correct_answers")
    ca = ""
    if isinstance(cans, list) and cans:
        ca = str(cans[0]).strip()
    expl = (q.get("explanation") or "").strip().replace("\n", " ")
    if len(expl) > 350:
        expl = expl[:349] + "…"
    full = (
        f"Раздел: {bi.section_title}\n"
        f"Источник: {meta}\n"
        f"Вопрос: {(q.get('question') or q.get('text') or '').strip()}\n"
        f"Варианты: {opt_s}\n"
        f"Верно: {ca}\n"
        f"Пояснение: {expl}"
    )
    return short, full


def build_compact_pick_ledger(
    scored: list[tuple[float, BankItem]],
    max_items: int = 28,
    question_cap: int = 95,
    section_cap: int = 26,
) -> tuple[list[str], list[BankItem]]:
    """
    Короткие строки для LLM: только номер, кусок раздела и обрезанный текст вопроса.
    Нужно укладываться в n_ctx модели вместе с max_tokens ответа.
    """
    lines: list[str] = []
    items: list[BankItem] = []
    for _, bi in scored[:max_items]:
        raw = bi.raw
        t = (raw.get("question") or raw.get("text") or "").strip().replace("\n", " ")
        if len(t) > question_cap:
            t = t[: question_cap - 1] + "…"
        sec = (bi.section_title or "").strip()
        if len(sec) > section_cap:
            sec = sec[: section_cap - 1] + "…"
        items.append(bi)
        lines.append(f"{len(items)}. [{sec}] {t}")
    return lines, items


def build_rag_style_context(
    index: QuestionBankIndex,
    topic: str,
    extra: str,
    difficulty_mode: str,
    max_chars: int = 2800,
    pool: int = 40,
) -> str:
    """Сжатый текст из учебника (как замена чанкам RAG) для open/match/chronology."""
    scored = filter_scored_items(index, topic, extra, difficulty_mode, pool_size=pool)
    parts: list[str] = []
    n = 0
    for _, bi in scored:
        _, full = bank_item_to_lines(bi, max_q=600)
        meta = source_line_from_raw(bi.raw)
        chunk = f"[фрагмент {n + 1}, источник: {meta}]\n{full}"
        if sum(len(p) for p in parts) + len(chunk) > max_chars:
            break
        parts.append(chunk)
        n += 1
    return "\n\n".join(parts)


def validate_bank_folder(folder: str) -> tuple[bool, str]:
    p = Path(folder)
    if not p.is_dir():
        return False, "Укажите существующую папку."
    try:
        QuestionBankIndex(folder)
    except Exception as e:
        return False, str(e)
    return True, "OK"
