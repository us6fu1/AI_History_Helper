# -*- coding: utf-8 -*-
"""
Ассистент редактирования уже собранного теста: локальная LLM планирует действия,
подбор замены — из JSON-учебника к текущей теме с исключением уже использованных позиций.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Callable, Optional

from question_bank import QuestionBankIndex, filter_scored_typed_items

logger = logging.getLogger(__name__)


def _clamp_idx(n: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, n))


def summarize_test_for_llm(questions: list[Any]) -> str:
    """Компактное описание теста для промпта (номер, тип, текст)."""
    lines: list[str] = []
    for i, q in enumerate(questions, start=1):
        d = q.to_dict() if hasattr(q, "to_dict") else dict(q)
        qt = (d.get("question_type") or "test").lower()
        txt = (d.get("text") or "").strip().replace("\r\n", "\n")
        if len(txt) > 380:
            txt = txt[:379] + "…"
        lines.append(f"{i}. [{qt}] {txt}")
    return "\n".join(lines)


def _extract_json_obj(model, raw: str) -> Optional[dict[str, Any]]:
    if not raw:
        return None
    parsed = model.extract_json(raw)
    return parsed if isinstance(parsed, dict) else None


def llm_plan_operations(
    model,
    *,
    outline: str,
    topic: str,
    user_message: str,
    n_questions: int,
) -> tuple[str, list[dict[str, Any]]]:
    """
    Возвращает (reply, operations). operations — список объектов
    с полями type, question_index (1-based).
    """
    sys_prompt = (
        "Ты редактор школьных тестов. Тебе дали список вопросов с номерами и просьбу учителя.\n"
        "Верни только JSON-объект без markdown:\n"
        '{"assistant_reply":"краткий ответ учителю на русском","operations":[]}\n'
        "В operations допускается только элемент:\n"
        '{"type":"replace_similar","question_index": целое — номер вопроса из списка (1…N)}\n'
        "Если просьбу нельзя выполнить как замену вопроса — оставь operations пустым и объясни в assistant_reply.\n"
        "Можно указать несколько замен, если пользователь явно просит несколько номеров.\n"
        f"В тесте ровно {n_questions} вопросов."
    )
    user_blob = (
        f"Тема теста: «{topic.strip()}».\n\n"
        f"ТЕКУЩИЙ ТЕСТ:\n{outline}\n\n"
        f"ПРОСЬБА УЧИТЕЛЯ:\n{user_message.strip()}"
    )
    messages = [
        {"role": "system", "content": sys_prompt},
        {"role": "user", "content": user_blob},
    ]
    raw = ""
    try:
        raw = model.generate_chat(
            messages,
            max_tokens=700,
            temperature=0.25,
            response_format={"type": "json_object"},
        )
    except TypeError:
        raw = model.generate_chat(messages, max_tokens=700, temperature=0.25)
    except Exception as e:
        logger.warning("Ассистент: план недоступен (%s)", e)
        return ("Не удалось обратиться к модели для плана.", [])

    parsed = _extract_json_obj(model, raw)
    if not parsed:
        reply = (raw or "").strip()[:600] or "Модель вернула неJSON-ответ."
        return (reply, [])

    reply = str(parsed.get("assistant_reply") or parsed.get("reply") or "").strip()
    if not reply:
        reply = "Готово."

    ops_raw = parsed.get("operations")
    if not isinstance(ops_raw, list):
        # Устаревшие / альтернативные поля
        alt = parsed.get("actions")
        ops_raw = alt if isinstance(alt, list) else []

    operations: list[dict[str, Any]] = []
    for op in ops_raw:
        if not isinstance(op, dict):
            continue
        t = str(op.get("type") or "").lower().strip()
        if t in ("replace_similar", "replace", "заменить"):
            idx = op.get("question_index", op.get("index", op.get("номер")))
            try:
                qi = int(idx)
            except (TypeError, ValueError):
                continue
            qi = _clamp_idx(qi, 1, n_questions)
            operations.append({"type": "replace_similar", "question_index": qi})

    # Дедуп одинаковых индексов, сохраняем порядок
    seen: set[int] = set()
    uniq: list[dict[str, Any]] = []
    for op in operations:
        qi = op.get("question_index")
        if isinstance(qi, int) and qi not in seen:
            seen.add(qi)
            uniq.append(op)

    return (reply, uniq)


def llm_pick_candidate_rank(
    model,
    *,
    topic: str,
    user_message: str,
    old_question_text: str,
    candidate_lines: list[str],
) -> int:
    """
    Выбирает 1-based номер строки-кандидата. При ошибке — 1 (лучший по рангу).
    """
    if len(candidate_lines) <= 1:
        return 1

    blob = "\n".join(candidate_lines)
    sys_p = (
        "Выбери ОДИН номер строки списка (1 … M), которая лучше всего подходит для замены "
        "старого вопроса: похожая тематика раздела, но другая формулировка. "
        "Только JSON: {\"pick\": число}"
    )
    old_sh = old_question_text.strip().replace("\r\n", " ")
    if len(old_sh) > 400:
        old_sh = old_sh[:399] + "…"

    usr = (
        f"Тема: «{topic.strip()}».\nЗапрос учителя: {user_message.strip()}\n\n"
        f"Старый вопрос (вырезаем из теста):\n{old_sh}\n\n"
        "Кандидаты из учебника:\n"
        f"{blob}\n\n"
        'Ответь только одним JSON-объектом: {"pick": <целое от 1 до M>}.'
    )
    messages = [
        {"role": "system", "content": sys_p},
        {"role": "user", "content": usr},
    ]
    raw = ""
    try:
        raw = model.generate_chat(
            messages,
            max_tokens=80,
            temperature=0.2,
            response_format={"type": "json_object"},
        )
    except TypeError:
        raw = model.generate_chat(messages, max_tokens=80, temperature=0.2)

    parsed = _extract_json_obj(model, raw)
    pick = 1
    if isinstance(parsed, dict):
        for key in ("pick", "choice", "index"):
            v = parsed.get(key)
            if v is None:
                continue
            try:
                pick = int(v)
                break
            except (TypeError, ValueError):
                continue

    return _clamp_idx(pick, 1, len(candidate_lines))


def collect_exclusions(questions: list[Any], skip_index_1based: Optional[int]) -> tuple[set[str], set[str]]:
    """Множества bank_uid и нормалей текста (кроме заменяемого вопроса)."""
    from question_generator import QuestionGenerator

    uids: set[str] = set()
    norms: set[str] = set()
    for i, q in enumerate(questions, start=1):
        if skip_index_1based is not None and i == skip_index_1based:
            continue
        d = q.to_dict() if hasattr(q, "to_dict") else dict(q)
        uid = str(d.get("bank_uid") or "").strip()
        if uid:
            uids.add(uid)
        norms.add(QuestionGenerator._normalize_text(str(d.get("text") or "")))
    norms.discard("")
    return uids, norms


def replace_one_from_bank(
    generator: Any,
    model: Any,
    *,
    questions: list[Any],
    replace_index_1based: int,
    topic: str,
    difficulty: str,
    bank_folder: str,
    user_message: str,
    norm_text_fn: Callable[[str], str],
    build_question_fn: Callable[..., Any],
) -> tuple[bool, str]:
    """
    Заменяет вопрос с индексом replace_index_1based новым из учебника того же типа.
    Изменяет список questions на месте.
    """
    idx = replace_index_1based
    if not (1 <= idx <= len(questions)):
        return (False, f"Номер вне диапазона 1–{len(questions)}.")

    cur = questions[idx - 1]
    d_cur = cur.to_dict() if hasattr(cur, "to_dict") else dict(cur)
    ui_type = (d_cur.get("question_type") or "test").lower()

    ex_uids, ex_norms = collect_exclusions(questions, idx)
    old_txt = str(d_cur.get("text") or "")
    old_norm = norm_text_fn(old_txt)
    ex_norms.discard(old_norm)

    pool = max(128, len(questions) * 16)
    try:
        index = QuestionBankIndex(bank_folder)
    except Exception as e:
        return (False, f"Не удалось открыть учебник: {e}")

    scored = filter_scored_typed_items(
        index,
        topic,
        user_message.strip() or topic,
        difficulty,
        pool_size=pool,
        ui_question_type=ui_type,
    )
    if not scored:
        return (False, f"Нет записей типа «{ui_type}» в учебнике по этой теме.")

    picks: list[tuple[float, Any]] = []
    for sc, bi in scored:
        uid = bi.uid()
        if uid in ex_uids:
            continue
        nq = build_question_fn(bi, ui_type, topic, difficulty)
        if not nq:
            continue
        nd = nq.to_dict() if hasattr(nq, "to_dict") else {}
        tn = norm_text_fn(str(nd.get("text") or ""))
        if not tn or tn in ex_norms:
            continue
        picks.append((sc, nq))

    if not picks:
        return (False, "Не найден другой подходящий вопрос в учебнике (все уже в тесте или не проходят фильтр).")

    def _stable_pick_key(item: tuple[float, Any]) -> tuple[float, str, str]:
        sc, nq = item
        nd = nq.to_dict() if hasattr(nq, "to_dict") else {}
        text_key = norm_text_fn(str(nd.get("text") or ""))
        uid_key = str(nd.get("bank_uid") or "")
        return (-sc, text_key, uid_key)

    picks.sort(key=_stable_pick_key)

    max_show = min(16, len(picks))
    top = picks[:max_show]

    cand_lines = []
    for j, (_, nq_) in enumerate(top, start=1):
        dq = nq_.to_dict() if hasattr(nq_, "to_dict") else {}
        stem = str(dq.get("text") or "").strip().replace("\r\n", " ")
        if len(stem) > 220:
            stem = stem[:219] + "…"
        src = dq.get("source_page") or ""
        suf = f" ({src})" if src else ""
        cand_lines.append(f"{j}. {stem}{suf}")

    pick_rank = llm_pick_candidate_rank(
        model,
        topic=topic,
        user_message=user_message,
        old_question_text=old_txt,
        candidate_lines=cand_lines,
    )
    replacement = top[_clamp_idx(pick_rank, 1, len(top)) - 1][1]

    questions[idx - 1] = replacement
    return (True, f"Вопрос {idx} заменён позицией {pick_rank} из отобранных кандидатов.")


def run_test_assistant_turn(
    generator: Any,
    model: Any,
    *,
    questions: list[Any],
    topic: str,
    difficulty: str,
    bank_folder: Optional[str],
    user_message: str,
) -> tuple[str, list[Any]]:
    """
    Одна «итерация» ассистента: план действий через LLM, затем применение замен из учебника.
    Возвращает (сообщение для пользователя, тот же список questions с правками).
    """
    user_message = user_message.strip()
    if not user_message:
        return ("Введите запрос для ассистента.", questions)

    n = len(questions)
    if n == 0:
        return ("В тесте нет вопросов.", questions)

    outline = summarize_test_for_llm(questions)

    reply, operations = llm_plan_operations(
        model,
        outline=outline,
        topic=topic,
        user_message=user_message,
        n_questions=n,
    )

    if not operations:
        if not reply:
            reply = "Операции не выполнены."
        return (reply, questions)

    tail_notes: list[str] = []

    if not bank_folder or not str(bank_folder).strip():
        tail_notes.append(
            "Подбор замены из учебника возможен только если тест связан с папкой учебника. "
            "Сгенерируйте тест, выбрав учебник в разделе «Учебники», или откройте такой тест из истории."
        )
        return (reply + ("\n\n" + "\n".join(tail_notes) if tail_notes else ""), questions)

    bank_folder = str(bank_folder).strip()

    for op in operations:
        if op.get("type") != "replace_similar":
            continue
        qi = op.get("question_index")
        if not isinstance(qi, int):
            continue
        ok, note = replace_one_from_bank(
            generator,
            model,
            questions=questions,
            replace_index_1based=qi,
            topic=topic,
            difficulty=difficulty or "medium",
            bank_folder=bank_folder,
            user_message=user_message,
            norm_text_fn=generator._normalize_text,
            build_question_fn=generator._question_from_bank_typed,
        )
        tail_notes.append(note)
        if not ok:
            logger.info("Ассистент: замена не удалась: %s", note)

    full = reply
    if tail_notes:
        full = full + "\n\n" + "\n".join(tail_notes)

    return (full.strip(), questions)
