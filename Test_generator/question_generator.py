"""
Генерация и проверка вопросов: быстрый подбор из JSON-банка → валидация.

Кэш (опционально): HISTORY_TEST_GEN_CACHE=1 → data/gen_cache/ (или HISTORY_TEST_GEN_CACHE_DIR).
LLM-подбор включён по умолчанию: модель выбирает номера из короткого списка.
Переопределение: HISTORY_TEST_LLM_PICK=0 выключает LLM-подбор.
Сброс при смене учебника (JSON) или GGUF.
"""
from __future__ import annotations

import datetime
import os
import re
import json
import hashlib
import logging
from typing import Optional, Callable
from dataclasses import dataclass, field, asdict

from app_paths import user_data_dir

logger = logging.getLogger(__name__)


_QUESTION_TAIL_TYPES = frozenset({"chronology", "match", "open"})
_DIFF_SORT_KEY = {"easy": 0, "medium": 1, "hard": 2}
_TAIL_TYPE_ORDER = {"chronology": 0, "match": 1, "open": 2}

_FOUNDATION_TERMS = (
    "кто", "что такое", "как назы", "какой", "какая", "какое", "где", "когда",
    "кем был", "кто был", "царь", "князь", "император", "правитель",
    "фараон", "полководец", "город", "страна", "государство",
)
_ACTION_TERMS = (
    "что сделал", "чем заним", "основал", "создал", "построил", "завоевал",
    "победил", "провел", "провёл", "издал", "принял", "ввел", "ввёл",
    "реформа", "поход", "война", "сражение", "битва", "действие",
)
_MEANING_TERMS = (
    "почему", "зачем", "какую роль", "роль сыграл", "значение", "последств",
    "причин", "итог", "вывод", "повлиял", "объясняет", "связано",
    "отличие", "сравн", "докажи", "подтверди",
)


def _contains_any_term(text: str, terms: tuple[str, ...]) -> bool:
    return any(term in text for term in terms)


def _learning_stage(q: "Question") -> int:
    """0: базовое узнавание, 1: действия/события, 2: причины и значение."""
    blob = f"{q.text} {' '.join(q.options or [])}".lower()
    if _contains_any_term(blob, _MEANING_TERMS):
        return 2
    if _contains_any_term(blob, _ACTION_TERMS):
        return 1
    if _contains_any_term(blob, _FOUNDATION_TERMS):
        return 0
    return 1


def _first_int(text: str, default: int = 9999) -> int:
    m = re.search(r"\d+", text or "")
    return int(m.group(0)) if m else default


def _source_order(q: "Question") -> tuple[int, int]:
    return (
        _first_int(q.source_paragraph),
        _first_int(q.source_page),
    )


def _source_paragraph_order(q: "Question") -> int:
    return _first_int(q.source_paragraph)


def _source_page_order(q: "Question") -> int:
    return _first_int(q.source_page)


def _standalone_question_text(text: str, topic: str = "") -> str:
    """Убирает привязки к невидимому контексту учебника из текста вопроса."""
    s = re.sub(r"\s+", " ", (text or "").strip())
    topic_l = (topic or "").lower()

    if "древн" in topic_l and "егип" in topic_l:
        s = re.sub(
            r"Где возникла одна из древнейших цивилизаций, о которой ид[её]т речь\?",
            "Где возникла древнеегипетская цивилизация?",
            s,
            flags=re.I,
        )

    cleanup = (
        (r",?\s*о котор(?:ой|ом|ых)\s+ид[её]т\s+речь", ""),
        (r"\s+в\s+данном\s+тексте", ""),
        (r"\s+в\s+этом\s+тексте", ""),
        (r"\s+из\s+текста", ""),
        (r"\s+по\s+тексту\s+учебника", ""),
        (r"\s+по\s+учебнику", ""),
        (r"\s+согласно\s+учебнику", ""),
    )
    for pattern, repl in cleanup:
        s = re.sub(pattern, repl, s, flags=re.I)
    return re.sub(r"\s+", " ", s).strip()


def sort_questions_for_test(questions: list["Question"]) -> list["Question"]:
    """
    Сначала идут вопросы из меньшего параграфа/более ранней страницы.
    Внутри одного источника: базовые вопросы перед аналитическими; задания
    хронологии, сопоставления и открытые — после тестовых.
    """

    def _dr(q: "Question") -> int:
        return _DIFF_SORT_KEY.get((q.difficulty or "medium").strip().lower(), 1)

    def _tail_ord(q: "Question") -> int:
        qt = (q.question_type or "test").lower()
        return _TAIL_TYPE_ORDER.get(qt, 99)

    def _is_tail(q: "Question") -> int:
        return 1 if (q.question_type or "test").lower() in _QUESTION_TAIL_TYPES else 0

    def _within_source_order(q: "Question") -> tuple[int, int, int, str]:
        if _is_tail(q):
            return (1, _tail_ord(q), _dr(q), _normalize_for_sort(q.text))
        return (0, _learning_stage(q), _dr(q), _normalize_for_sort(q.text))

    return sorted(
        questions,
        key=lambda q: (
            _source_paragraph_order(q),
            _within_source_order(q),
            _source_page_order(q),
        ),
    )


def _normalize_for_sort(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"\s+", " ", text)
    return text


def _gen_cache_enabled() -> bool:
    v = os.environ.get("HISTORY_TEST_GEN_CACHE", "0").strip().lower()
    return v in ("1", "true", "yes", "on")


def _llm_pick_enabled(custom_prompt: str = "") -> bool:
    v = os.environ.get("HISTORY_TEST_LLM_PICK", "1").strip().lower()
    if v in ("0", "false", "no", "off"):
        return False
    return True


def _gen_cache_dir() -> str:
    custom = os.environ.get("HISTORY_TEST_GEN_CACHE_DIR", "").strip()
    if custom:
        return custom
    base = os.path.join(str(user_data_dir()), "gen_cache")
    os.makedirs(base, exist_ok=True)
    return base


def _file_fingerprint(path: str) -> tuple[str, float, int]:
    ap = os.path.abspath(path) if path else ""
    if not ap or not os.path.isfile(ap):
        return "", 0.0, 0
    try:
        st = os.stat(ap)
        return ap, float(st.st_mtime), int(st.st_size)
    except OSError:
        return ap, 0.0, 0


@dataclass
class Question:
    question_type: str
    text: str
    options: list[str] = field(default_factory=list)
    correct_answer: str = ""
    explanation: str = ""
    source_page: str = ""
    source_paragraph: str = ""
    difficulty: str = "medium"
    topic: str = ""
    bank_uid: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Question":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})



class QuestionGenerator:
    """Подбор вопросов из JSON-учебника через локальную GGUF-модель."""

    def __init__(self, model_runner):
        self.model = model_runner
        self._recent_bank_uids: dict[str, set[str]] = {}

    @staticmethod
    def _gen_cache_digest(payload: dict) -> str:
        blob = json.dumps(payload, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()

    def _make_gen_cache_key(
        self,
        topic: str,
        question_type: str,
        count: int,
        difficulty: str,
        custom_prompt: str,
        include_answers: bool,
        include_explanations: bool,
        bank_fingerprint: str = "",
    ) -> dict:
        mp, mm, ms = _file_fingerprint(getattr(self.model, "model_path", "") or "")
        return {
            "schema": 6,
            "topic": topic.strip().lower(),
            "question_type": question_type,
            "count": int(count),
            "difficulty": difficulty,
            "custom_prompt": custom_prompt.strip(),
            "include_answers": bool(include_answers),
            "include_explanations": bool(include_explanations),
            "model_path": mp,
            "model_mtime": mm,
            "model_size": ms,
            "bank_fingerprint": bank_fingerprint or "",
        }

    def _try_load_gen_cache(self, key: dict) -> Optional[list[Question]]:
        if not _gen_cache_enabled():
            return None
        digest = self._gen_cache_digest(key)
        path = os.path.join(_gen_cache_dir(), f"{digest}.json")
        if not os.path.isfile(path):
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if data.get("key_digest") != digest:
                return None
            raw = data.get("questions")
            if not isinstance(raw, list):
                return None
            out: list[Question] = []
            for item in raw:
                if isinstance(item, dict):
                    out.append(Question.from_dict(item))
            return out if out else None
        except Exception:
            return None

    def _save_gen_cache(self, key: dict, questions: list[Question]) -> None:
        if not _gen_cache_enabled() or not questions:
            return
        try:
            digest = self._gen_cache_digest(key)
            base = _gen_cache_dir()
            os.makedirs(base, exist_ok=True)
            path = os.path.join(base, f"{digest}.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "key_digest": digest,
                        "key": key,
                        "questions": [q.to_dict() for q in questions],
                    },
                    f,
                    ensure_ascii=False,
                    indent=2,
                )
        except Exception as e:
            logger.warning("Не удалось записать кэш генерации: %s", e)

    def generate(
        self,
        topic: str,
        question_type: str,
        count: int,
        difficulty: str = "medium",
        custom_prompt: str = "",
        include_answers: bool = True,
        include_explanations: bool = True,
        progress_callback: Optional[Callable[[str], None]] = None,
        bank_folder: Optional[str] = None,
    ) -> list[Question]:
        if not self.model.is_loaded:
            raise RuntimeError("Модель не загружена")

        from question_bank import bank_folder_fingerprint

        if not bank_folder:
            raise RuntimeError("Не выбран учебник (папка с JSON).")
        bf = os.path.abspath(bank_folder)
        if not os.path.isdir(bf):
            raise ValueError(f"Папка учебника не найдена: {bf}")
        bank_fp = bank_folder_fingerprint(bf)

        cache_key = None
        if _gen_cache_enabled():
            cache_key = self._make_gen_cache_key(
                topic=topic,
                question_type=question_type,
                count=count,
                difficulty=difficulty,
                custom_prompt=custom_prompt,
                include_answers=include_answers,
                include_explanations=include_explanations,
                bank_fingerprint=bank_fp,
            )
            cached = self._try_load_gen_cache(cache_key)
            if cached is not None:
                if progress_callback:
                    progress_callback(
                        "Загружено из локального кэша (те же параметры и файлы — без LLM)."
                    )
                return sort_questions_for_test(cached)

        target_count = max(1, int(count))

        if progress_callback:
            progress_callback("Генерация теста")
        questions = self._select_from_bank_via_llm(
            folder=bf,
            question_type=question_type,
            target_count=target_count,
            topic=topic,
            difficulty=difficulty,
            custom_prompt=custom_prompt,
            progress_callback=progress_callback,
        )

        if not include_answers:
            for q in questions:
                q.correct_answer = ""

        if not include_explanations:
            for q in questions:
                q.explanation = ""

        questions = sort_questions_for_test(questions[:target_count])

        diff_seq = self._build_difficulty_sequence(len(questions), difficulty)
        for i, q in enumerate(questions):
            q.difficulty = diff_seq[i]

        if progress_callback:
            progress_callback(
                f"Готово! Сгенерировано {len(questions)} вопросов из {target_count}."
            )

        if cache_key is not None:
            self._save_gen_cache(cache_key, questions)

        return questions

    def _question_from_bank_typed(
        self,
        bi,
        ui_type: str,
        topic: str,
        difficulty: str,
    ) -> Optional[Question]:
        """Собирает Question только из полей JSON учебника (без LLM)."""
        import random

        from question_bank import (
            BankItem,
            bank_question_difficulty_mode,
            chronology_solution_sequence,
            formatted_source_page,
            is_well_formed_mc,
            paragraph_label_for_bank_question,
        )

        if not isinstance(bi, BankItem):
            return None
        raw = bi.raw
        common_page = formatted_source_page(raw)
        para_ui = paragraph_label_for_bank_question(raw, bi.section_title)
        rank_d = bank_question_difficulty_mode(raw)

        if ui_type == "test":
            if not is_well_formed_mc(raw):
                return None
            opts = [str(o).strip() for o in raw.get("options", []) if str(o).strip()][:4]
            cans = raw.get("correct_answers")
            ca = str(cans[0]).strip() if isinstance(cans, list) and cans else ""
            q = Question(
                question_type="test",
                text=_standalone_question_text(
                    str(raw.get("question") or raw.get("text") or ""),
                    topic,
                ),
                options=opts,
                correct_answer=ca,
                explanation=str(raw.get("explanation") or "").strip(),
                source_page=common_page,
                source_paragraph=para_ui,
                difficulty=rank_d,
                topic=topic,
                bank_uid=bi.uid(),
            )
            self._shuffle_single_choice_options(q)
            return q

        if ui_type == "open":
            txt = _standalone_question_text(
                str(raw.get("question") or raw.get("text") or ""),
                topic,
            )
            ca = raw.get("correct_answer")
            if isinstance(ca, str) and ca.strip():
                ans = ca.strip()
            else:
                cans = raw.get("correct_answers")
                ans = str(cans[0]).strip() if isinstance(cans, list) and cans else ""
            if len(txt) < 10 or not ans:
                return None
            expl = str(raw.get("explanation") or "").strip()
            acc = raw.get("acceptable_answers")
            if isinstance(acc, list) and acc:
                tail = "; ".join(str(x) for x in acc[:5])
                if tail:
                    expl = (expl + "\n\nДопустимые формулировки: " + tail).strip()
            return Question(
                question_type="open",
                text=txt,
                options=[],
                correct_answer=ans,
                explanation=expl,
                source_page=common_page,
                source_paragraph=para_ui,
                difficulty=rank_d,
                topic=topic,
                bank_uid=bi.uid(),
            )

        if ui_type == "chronology":
            seq = chronology_solution_sequence(raw)
            pool = [str(x).strip() for x in (raw.get("items") or []) if str(x).strip()]
            if len(seq) < 3 or len(pool) < 3:
                return None
            rng = random.Random(abs(hash(bi.uid())) % (2**31))
            opts = pool[:]
            rng.shuffle(opts)
            return Question(
                question_type="chronology",
                text=_standalone_question_text(
                    str(raw.get("question") or raw.get("text") or ""),
                    topic,
                ),
                options=opts,
                correct_answer=" → ".join(seq),
                explanation=str(raw.get("explanation") or "").strip(),
                source_page=common_page,
                source_paragraph=para_ui,
                difficulty=rank_d,
                topic=topic,
                bank_uid=bi.uid(),
            )

        if ui_type == "match":
            lp = raw.get("left_items")
            rp = raw.get("right_items")
            cp = raw.get("correct_pairs")
            if not isinstance(lp, list) or not isinstance(rp, list) or not isinstance(cp, list):
                return None
            lids: dict[str, str] = {}
            for x in lp:
                if isinstance(x, dict) and x.get("id") is not None:
                    lids[str(x["id"])] = str(x.get("text", "")).strip()
            rids: dict[str, str] = {}
            for x in rp:
                if isinstance(x, dict) and x.get("id") is not None:
                    rids[str(x["id"])] = str(x.get("text", "")).strip()
            ordered_pairs: list[str] = []
            for p in cp:
                if not isinstance(p, dict):
                    continue
                ls = lids.get(str(p.get("left", "")))
                rs = rids.get(str(p.get("right", "")))
                if ls and rs:
                    ordered_pairs.append(f"{ls} → {rs}")
            if len(ordered_pairs) < 2:
                return None
            rng = random.Random(abs(hash(bi.uid())) % (2**31))
            opts = ordered_pairs[:]
            rng.shuffle(opts)
            return Question(
                question_type="match",
                text=_standalone_question_text(
                    str(raw.get("question") or raw.get("text") or ""),
                    topic,
                ),
                options=opts,
                correct_answer="; ".join(ordered_pairs),
                explanation=str(raw.get("explanation") or "").strip(),
                source_page=common_page,
                source_paragraph=para_ui,
                difficulty=rank_d,
                topic=topic,
                bank_uid=bi.uid(),
            )

        return None

    def _select_from_bank_via_llm(
        self,
        folder: str,
        question_type: str,
        topic: str,
        target_count: int,
        difficulty: str,
        custom_prompt: str,
        progress_callback: Optional[Callable[[str], None]] = None,
    ) -> list[Question]:
        from question_bank import (
            QuestionBankIndex,
            build_compact_pick_ledger,
            filter_scored_typed_items,
        )

        type_ru = {
            "test": "тесты (один верный ответ из 4 вариантов)",
            "open": "открытые вопросы",
            "match": "сопоставление",
            "chronology": "хронология (порядок событий)",
        }

        index = QuestionBankIndex(folder)
        pool = max(96, target_count * 12)
        scored = filter_scored_typed_items(
            index,
            topic,
            custom_prompt,
            difficulty,
            pool_size=pool,
            ui_question_type=question_type,
        )
        if not scored:
            if progress_callback:
                progress_callback(
                    f"В учебнике не найдено вопросов типа «{type_ru.get(question_type, question_type)}» "
                    "по теме — этот блок в тест не включается."
                )
            return []
        pick_n = min(target_count, len(scored))
        use_llm_pick = _llm_pick_enabled(custom_prompt)
        if use_llm_pick:
            max_led = min(len(scored), max(pick_n, min(max(12, pick_n * 3), 24)))
        else:
            max_led = min(len(scored), max(24, pick_n * 6), 56)
        lines, items = build_compact_pick_ledger(
            scored,
            max_items=max_led,
            question_cap=82,
            section_cap=30,
        )
        n_items = len(items)
        pick_n = min(target_count, n_items)
        score_by_index = {i: scored[i][0] for i in range(n_items)}
        best_score = max(score_by_index.values(), default=0.0)
        min_llm_score = max(4.0, best_score * 0.35) if best_score > 0 else 0.0

        select_key_payload = {
            "folder": os.path.abspath(folder),
            "topic": topic.strip().lower(),
            "type": question_type,
            "difficulty": difficulty,
            "custom_prompt": custom_prompt.strip().lower(),
        }
        select_key = hashlib.sha256(
            json.dumps(select_key_payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
        ).hexdigest()
        candidate_uids = [items[i].uid() for i in range(n_items)]
        recent = self._recent_bank_uids.setdefault(select_key, set())
        if sum(1 for uid in candidate_uids if uid not in recent) < pick_n:
            recent.clear()

        topic_s = topic.strip()
        if len(topic_s) > 220:
            topic_s = topic_s[:219] + "…"
        cp = custom_prompt.strip()
        if len(cp) > 400:
            cp = cp[:399] + "…"

        extra = ""
        if cp:
            extra = (
                "\nДополнительные инструкции (главный приоритет, важнее общей темы): "
                + cp
            )

        ledger_text = "\n".join(lines)
        user_prompt = (
            f"Тема: «{topic_s}». Тип: {type_ru.get(question_type, question_type)}.\n"
            f"Выбери ровно {pick_n} разных номеров из списка (1…{n_items}), релевантных теме. "
            "Если есть дополнительные инструкции, сначала выполняй их; не выбирай номера, которые им противоречат. "
            "Список уже отсортирован по релевантности: предпочитай верхние номера и не бери вопросы, которые лишь косвенно похожи на тему."
            " Нужна учебная лестница: сначала базовое узнавание персонажа, понятия, места или времени; затем действия и события; в конце причины, значение, последствия и выводы."
            f"{extra}\n"
            'Ответ только JSON: {"pick":[числа]}\n\n'
            f"{ledger_text}"
        )
        messages = [
            {"role": "system", "content": "Только JSON, без текста."},
            {"role": "user", "content": user_prompt},
        ]
        raw = ""
        out_cap = min(90, 16 + pick_n * 8)
        if use_llm_pick:
            if progress_callback:
                progress_callback("Умный подбор вопросов...")
            try:
                raw = self.model.generate_chat(
                    messages,
                    max_tokens=out_cap,
                    temperature=0.12,
                    response_format={"type": "json_object"},
                )
            except TypeError:
                try:
                    raw = self.model.generate_chat(
                        messages,
                        max_tokens=out_cap,
                        temperature=0.12,
                    )
                except Exception as e_chat:
                    logger.warning("Подбор из учебника: chat без формата не удался (%s)", e_chat)
                    raw = ""
            except Exception as e_chat:
                # Переполнение контекста или сбой бэкенда — берём номера по релевантности без LLM.
                logger.warning("Подбор из учебника: chat-LLM недоступен (%s)", e_chat)
                if progress_callback:
                    progress_callback("Генерация теста")
                raw = ""

        picked_idx: list[int] = []
        parsed = self.model.extract_json(raw)
        if isinstance(parsed, dict):
            arr = parsed.get("pick") or parsed.get("indices") or parsed.get("ids")
            if isinstance(arr, list):
                for x in arr:
                    try:
                        if isinstance(x, int):
                            xi = x
                        else:
                            s = str(x).strip().lstrip("№").lstrip("#")
                            xi = int(float(s.split()[0]))
                        if 1 <= xi <= n_items:
                            picked_idx.append(xi - 1)
                    except (ValueError, TypeError):
                        continue

        seen: set[int] = set()
        ordered_pick: list[int] = []
        for i in picked_idx:
            if score_by_index.get(i, 0.0) < min_llm_score:
                continue
            if i not in seen:
                seen.add(i)
                ordered_pick.append(i)
            if len(ordered_pick) >= pick_n:
                break

        if len(ordered_pick) < pick_n:
            for j in range(n_items):
                if j not in seen:
                    seen.add(j)
                    ordered_pick.append(j)
                if len(ordered_pick) >= pick_n:
                    break

        if progress_callback and len(picked_idx) < pick_n:
            progress_callback("Генерация теста")

        pick_n_eff = pick_n
        seen_txt: set[str] = set()
        final: list[Question] = []

        def _take(ji: int, *, allow_recent: bool = False) -> None:
            if len(final) >= pick_n_eff or ji < 0 or ji >= n_items:
                return
            uid = items[ji].uid()
            if not allow_recent and uid in recent:
                return
            q = self._question_from_bank_typed(items[ji], question_type, topic, difficulty)
            if not q:
                return
            k = self._normalize_text(q.text)
            if k in seen_txt:
                return
            seen_txt.add(k)
            final.append(q)

        for ji in ordered_pick:
            _take(ji)
            if len(final) >= pick_n_eff:
                break

        if len(final) < pick_n_eff:
            for j in range(n_items):
                _take(j)
                if len(final) >= pick_n_eff:
                    break

        if len(final) < pick_n_eff:
            for ji in ordered_pick:
                _take(ji, allow_recent=True)
                if len(final) >= pick_n_eff:
                    break

        if len(final) < pick_n_eff:
            for j in range(n_items):
                _take(j, allow_recent=True)
                if len(final) >= pick_n_eff:
                    break

        if question_type == "test":
            final = self._ensure_test_progression(
                final,
                items,
                topic=topic,
                difficulty=difficulty,
                recent=recent,
            )

        if not final:
            if progress_callback:
                progress_callback(
                    "Не удалось собрать вопросы из учебника для этого типа — блок пропускается."
                )
            return []

        recent.update(q.bank_uid for q in final if q.bank_uid)
        if len(recent) > max(120, target_count * 12):
            keep = set(candidate_uids[-max(1, target_count):])
            recent.intersection_update(keep)

        return final[:pick_n_eff]

    def _ensure_test_progression(
        self,
        final: list[Question],
        candidate_items: list,
        *,
        topic: str,
        difficulty: str,
        recent: set[str],
    ) -> list[Question]:
        """Добавляет в тест базовую учебную лестницу, если в кандидатах есть подходящие вопросы."""
        if len(final) < 3:
            return final

        def _stage_counts() -> dict[int, int]:
            out: dict[int, int] = {}
            for q in final:
                st = _learning_stage(q)
                out[st] = out.get(st, 0) + 1
            return out

        used_uids = {q.bank_uid for q in final if q.bank_uid}
        used_texts = {self._normalize_text(q.text) for q in final if q.text}
        counts = _stage_counts()

        for wanted_stage in (0, 1, 2):
            if counts.get(wanted_stage, 0) > 0:
                continue

            replacement: Optional[Question] = None
            for bi in candidate_items:
                uid = bi.uid()
                if uid in used_uids or uid in recent:
                    continue
                q = self._question_from_bank_typed(bi, "test", topic, difficulty)
                if not q or _learning_stage(q) != wanted_stage:
                    continue
                text_key = self._normalize_text(q.text)
                if not text_key or text_key in used_texts:
                    continue
                replacement = q
                break

            if replacement is None:
                continue

            replace_idx: Optional[int] = None
            counts = _stage_counts()
            for i in range(len(final) - 1, -1, -1):
                st = _learning_stage(final[i])
                if st != wanted_stage and counts.get(st, 0) > 1:
                    replace_idx = i
                    break

            if replace_idx is None:
                continue

            old = final[replace_idx]
            if old.bank_uid:
                used_uids.discard(old.bank_uid)
            if old.text:
                used_texts.discard(self._normalize_text(old.text))

            final[replace_idx] = replacement
            if replacement.bank_uid:
                used_uids.add(replacement.bank_uid)
            used_texts.add(self._normalize_text(replacement.text))
            counts = _stage_counts()

        return final

    def _shuffle_single_choice_options(self, q: Question) -> None:
        """Перемешивает варианты теста; correct_answer остаётся той же строкой из списка."""
        import random

        opts = q.options
        if len(opts) < 2:
            return
        ca = (q.correct_answer or "").strip()
        if not ca:
            return
        ca_n = self._normalize_text(ca)
        canon: Optional[str] = None
        for opt in opts:
            if ca_n == self._normalize_text(opt):
                canon = opt
                break
        if canon is None:
            return
        shuffled = opts[:]
        random.shuffle(shuffled)
        q.options = shuffled
        for o in shuffled:
            if self._normalize_text(o) == self._normalize_text(canon):
                q.correct_answer = o
                return
        q.correct_answer = canon

    @staticmethod
    def _build_difficulty_sequence(count: int, base: str) -> list[str]:
        """Возвращает возрастающую последовательность сложностей."""
        if count <= 0:
            return []

        if base == "easy":
            tiers = ["easy", "easy", "medium"]
        elif base == "hard":
            tiers = ["medium", "hard", "hard"]
        else:
            tiers = ["easy", "medium", "hard"]

        result = []
        for i in range(count):
            frac = i / max(1, count - 1)
            tier_idx = min(2, int(round(frac * 2)))
            result.append(tiers[tier_idx])
        return result

    @staticmethod
    def _normalize_text(text: str) -> str:
        """Нормализует текст для сравнения."""
        text = text.lower().strip()
        text = re.sub(r"\s+", " ", text)
        text = re.sub(r"[^\w\s]", "", text)
        return text


class TestStorage:
    """Сохраняет и загружает сгенерированные тесты."""

    STORAGE_FILE = os.path.join(
        str(user_data_dir()), "tests_history.json"
    )

    def __init__(self):
        os.makedirs(os.path.dirname(self.STORAGE_FILE), exist_ok=True)
        self._tests: list[dict] = self._load()

    def _load(self) -> list[dict]:
        if os.path.exists(self.STORAGE_FILE):
            try:
                with open(self.STORAGE_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                return []
        return []

    def _save(self):
        with open(self.STORAGE_FILE, "w", encoding="utf-8") as f:
            json.dump(self._tests, f, ensure_ascii=False, indent=2)

    def save_test(
        self,
        topic: str,
        textbook_name: str,
        questions: list[Question],
        variant_num: int = 1,
        question_type: str = "test",
    ) -> str:
        """Сохраняет тест. Возвращает ID теста."""
        questions = sort_questions_for_test(questions)
        test_id = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        record = {
            "id": test_id,
            "topic": topic,
            "textbook": textbook_name,
            "date": datetime.datetime.now().strftime("%d.%m.%Y"),
            "time": datetime.datetime.now().strftime("%H:%M"),
            "question_type": question_type,
            "variant": variant_num,
            "count": len(questions),
            "questions": [q.to_dict() for q in questions],
        }
        self._tests.insert(0, record)
        self._tests = self._tests[:100]
        self._save()
        return test_id

    def save_generation_session(
        self,
        topic: str,
        textbook_name: str,
        batches: list[tuple[int, list[Question]]],
        question_type: str = "test",
    ) -> str:
        """
        Сохраняет одну сессию генерации из нескольких вариантов одной записью
        («одна история» с несколькими вариантами).
        При одном батче вызывает save_test.
        """
        if not batches:
            return ""

        batches = sorted(
            [
                (int(vn), sort_questions_for_test(list(qs)))
                for vn, qs in batches
                if qs
            ],
            key=lambda t: t[0],
        )
        if not batches:
            return ""

        if len(batches) == 1:
            vn, qs = batches[0]
            return self.save_test(topic, textbook_name, qs, vn, question_type)

        test_id = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        now_d = datetime.datetime.now().strftime("%d.%m.%Y")
        now_t = datetime.datetime.now().strftime("%H:%M")

        variants_payload: list[dict] = []
        total_cnt = 0
        for vn, qs in batches:
            dumped = [q.to_dict() for q in qs]
            variants_payload.append({"variant": vn, "count": len(dumped), "questions": dumped})
            total_cnt += len(dumped)

        flat_first_list = variants_payload[0]["questions"]

        record = {
            "id": test_id,
            "topic": topic,
            "textbook": textbook_name,
            "date": now_d,
            "time": now_t,
            "question_type": question_type,
            "variant": batches[0][0],
            "multi_variant": True,
            "variant_count": len(batches),
            "variants": variants_payload,
            # Дубль первого варианта для старых скриптов, ожидающих questions:
            "count": total_cnt,
            "questions": flat_first_list,
        }
        self._tests.insert(0, record)
        self._tests = self._tests[:100]
        self._save()
        return test_id

    def get_recent(self, limit: int = 10) -> list[dict]:
        return self._tests[:limit]

    def get_by_id(self, test_id: str) -> Optional[dict]:
        for t in self._tests:
            if t["id"] == test_id:
                return t
        return None

    def get_all(self) -> list[dict]:
        return self._tests

    def delete(self, test_id: str):
        self._tests = [t for t in self._tests if t["id"] != test_id]
        self._save()


def normalized_test_variants(record: dict) -> list[tuple[int, list[dict]]]:
    """Плоские варианты из записи истории (одно- или многовариантное)."""
    if not isinstance(record, dict):
        return []
    if record.get("multi_variant") and isinstance(record.get("variants"), list):
        out: list[tuple[int, list[dict]]] = []
        for v in record["variants"]:
            if not isinstance(v, dict):
                continue
            vn = int(v.get("variant") or len(out) + 1)
            qs = v.get("questions")
            if isinstance(qs, list) and qs:
                out.append((vn, qs))
        if out:
            return out
    vn = int(record.get("variant") or 1)
    qs = record.get("questions")
    return [(vn, qs if isinstance(qs, list) else [])]
