"""Build a question-bank folder from a user PDF via the loaded local LLM."""
from __future__ import annotations

import datetime as _dt
import json
import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional, Any

from app_paths import user_data_dir


ProgressCallback = Optional[Callable[[str], None]]

_MAX_CHUNK_CHARS = int(os.environ.get("AI_HISTORY_HELPER_PDF_CHUNK_CHARS", "6500"))
_QUESTIONS_PER_CHUNK = int(os.environ.get("AI_HISTORY_HELPER_PDF_QUESTIONS_PER_CHUNK", "20"))


@dataclass(frozen=True)
class PdfTextPage:
    page: int
    text: str


@dataclass(frozen=True)
class PdfChunk:
    index: int
    pages: tuple[int, ...]
    text: str

    @property
    def page_label(self) -> str:
        if not self.pages:
            return ""
        if len(self.pages) == 1:
            return str(self.pages[0])
        return f"{self.pages[0]}-{self.pages[-1]}"


def generated_textbooks_dir() -> Path:
    base = user_data_dir() / "generated_textbooks"
    base.mkdir(parents=True, exist_ok=True)
    return base


def safe_folder_name(name: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', " ", name or "").strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned[:120].rstrip(". ") or "PDF учебник"


def unique_folder(base_dir: Path, preferred_name: str) -> Path:
    stem = safe_folder_name(preferred_name)
    candidate = base_dir / stem
    if not candidate.exists():
        return candidate
    for i in range(2, 1000):
        candidate = base_dir / f"{stem} ({i})"
        if not candidate.exists():
            return candidate
    raise FileExistsError(f"Не удалось подобрать имя папки для «{stem}».")


def extract_pdf_pages(pdf_path: str) -> list[PdfTextPage]:
    path = Path(pdf_path)
    if not path.is_file():
        raise FileNotFoundError(f"PDF-файл не найден: {pdf_path}")
    if path.suffix.lower() != ".pdf":
        raise ValueError("Выберите файл PDF.")

    errors: list[str] = []

    try:
        from pypdf import PdfReader  # type: ignore

        reader = PdfReader(str(path))
        pages: list[PdfTextPage] = []
        for i, page in enumerate(reader.pages, start=1):
            text = page.extract_text() or ""
            text = normalize_text(text)
            if text:
                pages.append(PdfTextPage(i, text))
        if pages:
            return pages
    except Exception as e:
        errors.append(f"pypdf: {e}")

    try:
        import fitz  # type: ignore

        pages = []
        with fitz.open(str(path)) as doc:
            for i, page in enumerate(doc, start=1):
                text = normalize_text(page.get_text("text") or "")
                if text:
                    pages.append(PdfTextPage(i, text))
        if pages:
            return pages
    except Exception as e:
        errors.append(f"PyMuPDF: {e}")

    detail = "; ".join(errors) if errors else "текст не найден"
    raise RuntimeError(
        "Не удалось извлечь текст из PDF. Если это скан без текстового слоя, "
        f"сначала распознайте его OCR. Детали: {detail}"
    )


def normalize_text(text: str) -> str:
    text = text.replace("\x00", " ")
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def make_chunks(pages: list[PdfTextPage], max_chars: int = _MAX_CHUNK_CHARS) -> list[PdfChunk]:
    chunks: list[PdfChunk] = []
    cur_parts: list[str] = []
    cur_pages: list[int] = []
    cur_len = 0

    def flush() -> None:
        nonlocal cur_parts, cur_pages, cur_len
        if not cur_parts:
            return
        chunks.append(
            PdfChunk(
                index=len(chunks) + 1,
                pages=tuple(cur_pages),
                text="\n\n".join(cur_parts).strip(),
            )
        )
        cur_parts = []
        cur_pages = []
        cur_len = 0

    for page in pages:
        page_block = f"[Страница {page.page}]\n{page.text}"
        if cur_parts and cur_len + len(page_block) > max_chars:
            flush()

        if len(page_block) <= max_chars:
            cur_parts.append(page_block)
            cur_pages.append(page.page)
            cur_len += len(page_block)
            continue

        # Very long extracted pages are split by paragraphs, preserving the page number.
        paragraphs = [p.strip() for p in re.split(r"\n\s*\n", page.text) if p.strip()]
        piece = f"[Страница {page.page}]"
        for para in paragraphs:
            extra = "\n" + para
            if len(piece) + len(extra) > max_chars and piece.strip() != f"[Страница {page.page}]":
                if cur_parts:
                    flush()
                chunks.append(
                    PdfChunk(
                        index=len(chunks) + 1,
                        pages=(page.page,),
                        text=piece.strip(),
                    )
                )
                piece = f"[Страница {page.page}]\n{para}"
            else:
                piece += extra
        if piece.strip() != f"[Страница {page.page}]":
            if cur_parts:
                flush()
            chunks.append(
                PdfChunk(
                    index=len(chunks) + 1,
                    pages=(page.page,),
                    text=piece.strip(),
                )
            )

    flush()
    return chunks


def build_question_bank_from_pdf(
    pdf_path: str,
    textbook_name: str,
    model_runner,
    output_root: Optional[str] = None,
    progress_callback: ProgressCallback = None,
) -> str:
    if not getattr(model_runner, "is_loaded", False):
        raise RuntimeError("Сначала загрузите модель в разделе «Настройки модели».")

    if progress_callback:
        progress_callback("Читаю PDF и извлекаю текст…")
    pages = extract_pdf_pages(pdf_path)
    chunks = make_chunks(pages)
    if not chunks:
        raise RuntimeError("В PDF не найден текст для генерации вопросов.")

    root = Path(output_root) if output_root else generated_textbooks_dir()
    root.mkdir(parents=True, exist_ok=True)
    out_dir = unique_folder(root, textbook_name)
    out_dir.mkdir(parents=True, exist_ok=False)

    try:
        try:
            shutil.copy2(pdf_path, out_dir / Path(pdf_path).name)
        except Exception:
            pass

        manifest_files: list[dict[str, Any]] = []
        merged_questions: list[dict[str, Any]] = []

        for chunk in chunks:
            if progress_callback:
                progress_callback(
                    f"Создаю вопросы: часть {chunk.index} из {len(chunks)} "
                    f"(стр. {chunk.page_label})…"
                )
            questions, section_title = generate_questions_for_chunk(
                model_runner=model_runner,
                textbook_name=textbook_name,
                chunk=chunk,
                target_count=_QUESTIONS_PER_CHUNK,
            )
            if not questions:
                continue

            filename = f"section-{chunk.index:03d}.json"
            payload = {
                "meta": {
                    "textbook": textbook_name,
                    "section": section_title or f"PDF: страницы {chunk.page_label}",
                    "note": (
                        "Вопросы автоматически созданы локальной моделью по загруженному PDF. "
                        "Проверьте формулировки перед использованием на уроке."
                    ),
                },
                "questions": questions,
            }
            write_json(out_dir / filename, payload)
            manifest_files.append(
                {
                    "file": filename,
                    "section": payload["meta"]["section"],
                    "pages": chunk.page_label,
                    "questions": len(questions),
                }
            )
            merged_questions.extend(questions)

        if not merged_questions:
            raise RuntimeError(
                "Модель не смогла создать валидные вопросы по PDF. "
                "Попробуйте другой PDF или модель с большим контекстом."
            )

        write_json(
            out_dir / "manifest.json",
            {
                "textbook": textbook_name,
                "source_pdf": str(Path(pdf_path).name),
                "created_at": _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "total_files": len(manifest_files),
                "total_questions": len(merged_questions),
                "files": manifest_files,
            },
        )
        write_json(
            out_dir / "questions_merged.json",
            {
                "meta": {
                    "textbook": textbook_name,
                    "section": "Все вопросы",
                    "note": "Объединённая копия; приложение использует отдельные section-*.json.",
                },
                "questions": merged_questions,
            },
        )

        if progress_callback:
            progress_callback(
                f"Готово: создано {len(merged_questions)} вопросов в {len(manifest_files)} файлах."
            )
        return str(out_dir)
    except Exception:
        try:
            shutil.rmtree(out_dir)
        except Exception:
            pass
        raise


def write_json(path: Path, data: dict[str, Any]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def generate_questions_for_chunk(
    model_runner,
    textbook_name: str,
    chunk: PdfChunk,
    target_count: int,
) -> tuple[list[dict[str, Any]], str]:
    min_page = min(chunk.pages) if chunk.pages else 1
    max_page = max(chunk.pages) if chunk.pages else min_page
    target_count = max(6, min(24, int(target_count)))

    system = (
        "Ты составляешь банк вопросов по школьному учебнику. "
        "Используй только факты из предоставленного фрагмента PDF. "
        "Верни только валидный JSON без Markdown."
    )
    user = f"""
Название учебника: {textbook_name}
Фрагмент PDF: страницы {chunk.page_label}

Нужно создать до {target_count} учебных вопросов в формате банка приложения.
Смешай типы:
- single_choice: 4 варианта, один верный;
- open: открытый вопрос с correct_answer;
- matching: left_items/right_items/correct_pairs;
- chronology: items/correct_order/correct_answers.

Обязательная JSON-схема ответа:
{{
  "section": "короткое название темы фрагмента",
  "questions": [
    {{
      "type": "single_choice|open|matching|chronology",
      "question": "текст вопроса",
      "options": ["только для single_choice, ровно 4 варианта"],
      "correct_answers": ["верный ответ или список верных элементов"],
      "correct_answer": "для open можно строкой",
      "left_items": [{{"id":"L1","text":"..."}}],
      "right_items": [{{"id":"R1","text":"..."}}],
      "correct_pairs": [{{"left":"L1","right":"R1"}}],
      "items": ["событие 1", "событие 2", "событие 3"],
      "correct_order": [0, 1, 2],
      "explanation": "краткое объяснение по тексту",
      "source": {{"paragraph":"", "page": число от {min_page} до {max_page}}},
      "difficulty": {{"primary":"easy|medium|hard", "secondary":"easy|medium|hard"}},
      "tags": {{
        "entities": [],
        "concepts": [],
        "processes": [],
        "periods": [],
        "skills": ["knowledge"],
        "geography": [],
        "difficulty": "easy|medium|hard",
        "question_type": "single_choice|open|matching|chronology",
        "grade": [],
        "source": "{textbook_name}",
        "themes": []
      }}
    }}
  ]
}}

Не добавляй вопросы, если ответ нельзя подтвердить данным фрагментом.

Текст фрагмента:
{chunk.text}
""".strip()

    raw = model_runner.generate_chat_stream(
        [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        max_tokens=4200,
        temperature=0.18,
        response_format={"type": "json_object"},
        stop_after_questions=target_count,
    )
    parsed = model_runner.extract_json(raw)
    if not isinstance(parsed, dict):
        return [], f"PDF: страницы {chunk.page_label}"

    section = str(parsed.get("section") or "").strip()
    raw_questions = parsed.get("questions")
    if not isinstance(raw_questions, list):
        return [], section or f"PDF: страницы {chunk.page_label}"

    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in raw_questions:
        q = normalize_question(item, textbook_name, chunk, len(normalized) + 1)
        if not q:
            continue
        key = normalize_key(q.get("question", ""))
        if not key or key in seen:
            continue
        seen.add(key)
        normalized.append(q)
        if len(normalized) >= target_count:
            break

    return normalized, section or f"PDF: страницы {chunk.page_label}"


def normalize_question(
    item: Any,
    textbook_name: str,
    chunk: PdfChunk,
    number: int,
) -> Optional[dict[str, Any]]:
    if not isinstance(item, dict):
        return None
    q_type = str(item.get("type") or item.get("question_type") or "").strip().lower()
    if q_type == "multiple_choice":
        q_type = "single_choice"
    if q_type not in {"single_choice", "open", "matching", "chronology"}:
        return None

    question = str(item.get("question") or item.get("text") or "").strip()
    if len(question) < 12:
        return None

    source = item.get("source") if isinstance(item.get("source"), dict) else {}
    page = coerce_page(source.get("page"), chunk)
    difficulty = normalize_difficulty(item.get("difficulty"))
    tags = normalize_tags(item.get("tags"), textbook_name, q_type, difficulty["primary"])

    out: dict[str, Any] = {
        "id": f"pdf-{chunk.index:03d}-{number:03d}",
        "type": q_type,
        "question": question,
        "explanation": str(item.get("explanation") or "").strip(),
        "source": {
            "paragraph": str(source.get("paragraph") or "").strip(),
            "page": page,
        },
        "difficulty": difficulty,
        "tags": tags,
    }

    if q_type == "single_choice":
        options = [str(x).strip() for x in item.get("options", []) if str(x).strip()]
        options = dedupe_keep_order(options)
        correct_answers = item.get("correct_answers")
        correct = ""
        if isinstance(correct_answers, list) and correct_answers:
            correct = str(correct_answers[0]).strip()
        if not correct:
            correct = str(item.get("correct_answer") or "").strip()
        if len(options) != 4 or not correct:
            return None
        if correct not in options:
            match = next((o for o in options if normalize_key(o) == normalize_key(correct)), "")
            if match:
                correct = match
            else:
                return None
        out["options"] = options
        out["correct_answers"] = [correct]
        return out

    if q_type == "open":
        correct = str(item.get("correct_answer") or "").strip()
        if not correct:
            cas = item.get("correct_answers")
            if isinstance(cas, list) and cas:
                correct = str(cas[0]).strip()
        if not correct:
            return None
        out["correct_answer"] = correct
        acc = item.get("acceptable_answers")
        if isinstance(acc, list):
            cleaned = [str(x).strip() for x in acc if str(x).strip()]
            if cleaned:
                out["acceptable_answers"] = cleaned[:8]
        return out

    if q_type == "matching":
        left = normalize_id_text_list(item.get("left_items"), "L")
        right = normalize_id_text_list(item.get("right_items"), "R")
        pairs = item.get("correct_pairs")
        if not isinstance(pairs, list) or len(left) < 2 or len(right) < 2:
            return None
        left_ids = {x["id"] for x in left}
        right_ids = {x["id"] for x in right}
        good_pairs: list[dict[str, str]] = []
        for pair in pairs:
            if not isinstance(pair, dict):
                continue
            l_id = str(pair.get("left") or "").strip()
            r_id = str(pair.get("right") or "").strip()
            if l_id in left_ids and r_id in right_ids:
                good_pairs.append({"left": l_id, "right": r_id})
        if len(good_pairs) < 2:
            return None
        out["left_items"] = left
        out["right_items"] = right
        out["correct_pairs"] = good_pairs
        return out

    items = [str(x).strip() for x in item.get("items", []) if str(x).strip()]
    items = dedupe_keep_order(items)
    order = item.get("correct_order")
    if not isinstance(order, list):
        return None
    clean_order: list[int] = []
    for x in order:
        try:
            ix = int(x)
        except (TypeError, ValueError):
            continue
        if 0 <= ix < len(items) and ix not in clean_order:
            clean_order.append(ix)
    if len(items) < 3 or len(clean_order) < 3:
        return None
    out["items"] = items
    out["correct_order"] = clean_order
    out["correct_answers"] = [items[i] for i in clean_order]
    return out


def coerce_page(raw: Any, chunk: PdfChunk) -> int:
    fallback = min(chunk.pages) if chunk.pages else 1
    try:
        page = int(str(raw).strip())
    except (TypeError, ValueError):
        return fallback
    if chunk.pages and page not in chunk.pages:
        return fallback
    return page


def normalize_difficulty(raw: Any) -> dict[str, str]:
    if not isinstance(raw, dict):
        return {"primary": "medium", "secondary": "medium"}

    def one(value: Any) -> str:
        s = str(value or "").strip().lower()
        if s in {"easy", "medium", "hard"}:
            return s
        if "лег" in s:
            return "easy"
        if "слож" in s or "hard" in s:
            return "hard"
        return "medium"

    return {
        "primary": one(raw.get("primary")),
        "secondary": one(raw.get("secondary")),
    }


def normalize_tags(raw: Any, textbook_name: str, q_type: str, difficulty: str) -> dict[str, Any]:
    src = raw if isinstance(raw, dict) else {}

    def list_field(name: str) -> list[str]:
        value = src.get(name)
        if not isinstance(value, list):
            return []
        return [str(x).strip() for x in value if str(x).strip()][:12]

    return {
        "entities": list_field("entities"),
        "concepts": list_field("concepts"),
        "processes": list_field("processes"),
        "periods": list_field("periods"),
        "skills": list_field("skills") or ["knowledge"],
        "geography": list_field("geography"),
        "difficulty": difficulty,
        "question_type": q_type,
        "grade": src.get("grade") if isinstance(src.get("grade"), list) else [],
        "source": str(src.get("source") or textbook_name),
        "themes": list_field("themes"),
    }


def normalize_id_text_list(raw: Any, prefix: str) -> list[dict[str, str]]:
    if not isinstance(raw, list):
        return []
    out: list[dict[str, str]] = []
    used: set[str] = set()
    for i, item in enumerate(raw, start=1):
        if isinstance(item, dict):
            text = str(item.get("text") or "").strip()
            item_id = str(item.get("id") or f"{prefix}{i}").strip()
        else:
            text = str(item).strip()
            item_id = f"{prefix}{i}"
        if not text:
            continue
        if not re.fullmatch(rf"{prefix}\d+", item_id):
            item_id = f"{prefix}{i}"
        while item_id in used:
            item_id = f"{prefix}{len(used) + 1}"
        used.add(item_id)
        out.append({"id": item_id, "text": text})
    return out[:8]


def dedupe_keep_order(values: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        key = normalize_key(value)
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(value)
    return out


def normalize_key(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"[^\wа-яё0-9 ]+", "", text, flags=re.I)
    return text
