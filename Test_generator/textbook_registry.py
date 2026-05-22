"""
Реестр учебников: рабочие JSON-банки и PDF-учебники для отображения.
Файл data/textbooks.json сохранён для совместимости.
"""
from __future__ import annotations

import json
import os
import re
from typing import Optional

from app_paths import app_resource_dir, repo_resource_dir, user_data_dir


class TextbookRegistry:
    APP_DIR = str(app_resource_dir())
    REPO_ROOT = str(repo_resource_dir())
    BUNDLED_BANKS_DIR = os.path.join(REPO_ROOT, "Materials", "Вопросы")
    REGISTRY_FILE = os.path.join(
        str(user_data_dir()),
        "textbooks.json",
    )
    TEMPLATE_REGISTRY_FILE = os.path.join(APP_DIR, "data", "textbooks.json")

    def __init__(self):
        os.makedirs(os.path.dirname(self.REGISTRY_FILE), exist_ok=True)
        self._data: list[dict] = self._load()
        self._migrate_kinds()
        self._repair_or_discover_resources()

    def _migrate_kinds(self) -> None:
        dirty = False
        for item in self._data:
            if "kind" in item:
                continue
            fp = item.get("file", "")
            item["kind"] = "bank" if fp and os.path.isdir(fp) else "textbook"
            dirty = True
        if dirty:
            self._save()

    def _load(self) -> list[dict]:
        source = self.REGISTRY_FILE
        if not os.path.exists(source) and os.path.exists(self.TEMPLATE_REGISTRY_FILE):
            source = self.TEMPLATE_REGISTRY_FILE
        if os.path.exists(source):
            try:
                with open(source, "r", encoding="utf-8-sig") as f:
                    return json.load(f)
            except Exception:
                return []
        return []

    def _save(self) -> None:
        with open(self.REGISTRY_FILE, "w", encoding="utf-8") as f:
            json.dump(self._data, f, ensure_ascii=False, indent=2)

    @classmethod
    def _resolve_path(cls, folder: str) -> str:
        if not folder:
            return ""
        if os.path.isabs(folder):
            return folder
        return os.path.abspath(os.path.join(cls.REPO_ROOT, folder))

    @staticmethod
    def _is_valid_bank_folder(folder: str) -> bool:
        if not folder or not os.path.isdir(folder):
            return False
        try:
            from question_bank import validate_bank_folder

            ok, _ = validate_bank_folder(folder)
            return ok
        except Exception:
            return False

    def _discover_bundled_banks(self) -> list[dict]:
        root = self.BUNDLED_BANKS_DIR
        if not os.path.isdir(root):
            return []

        banks: list[dict] = []
        for name in sorted(os.listdir(root)):
            folder = os.path.join(root, name)
            if not self._is_valid_bank_folder(folder):
                continue
            banks.append({"name": name, "file": os.path.abspath(folder), "kind": "bank"})
        return banks

    def _discover_bundled_pdfs(self) -> list[dict]:
        root = self.BUNDLED_BANKS_DIR
        if not os.path.isdir(root):
            return []

        pdfs: list[dict] = []
        for name in sorted(os.listdir(root)):
            path = os.path.join(root, name)
            if not os.path.isfile(path) or not name.lower().endswith(".pdf"):
                continue
            display = os.path.splitext(name)[0].strip()
            pdfs.append({"name": display, "file": os.path.abspath(path), "kind": "pdf"})
        return pdfs

    def _find_relocated_bank(self, item: dict) -> str:
        old_path = str(item.get("file") or "")
        old_base = os.path.basename(os.path.normpath(old_path)) if old_path else ""
        item_name = str(item.get("name") or "")

        for bank in self._discover_bundled_banks():
            folder = bank["file"]
            base = os.path.basename(os.path.normpath(folder))
            if old_base and base == old_base:
                return folder
            if item_name and bank["name"] == item_name:
                return folder
        return ""

    def _repair_or_discover_resources(self) -> None:
        dirty = False
        repaired: list[dict] = []
        seen_paths: set[str] = set()

        for item in self._data:
            if item.get("kind") not in ("bank", "pdf"):
                continue
            fp = self._resolve_path(str(item.get("file") or ""))
            kind = item.get("kind")
            is_valid = (
                self._is_valid_bank_folder(fp)
                if kind == "bank"
                else os.path.isfile(fp) and fp.lower().endswith(".pdf")
            )
            if not is_valid and kind == "bank":
                relocated = self._find_relocated_bank(item)
                if not relocated:
                    dirty = True
                    continue
                item = dict(item)
                item["file"] = relocated
                item["kind"] = "bank"
                if not item.get("name"):
                    item["name"] = os.path.basename(os.path.normpath(relocated))
                dirty = True
            elif not is_valid:
                dirty = True
                continue

            ap = os.path.abspath(str(item["file"]))
            key = os.path.normcase(ap)
            if key in seen_paths:
                dirty = True
                continue
            seen_paths.add(key)
            item = dict(item)
            item["file"] = ap
            repaired.append(item)

        for discovered in self._discover_bundled_banks() + self._discover_bundled_pdfs():
            key = os.path.normcase(os.path.abspath(discovered["file"]))
            if key in seen_paths:
                continue
            seen_paths.add(key)
            repaired.append(discovered)
            dirty = True

        bank_display_keys = {
            self._display_key(item)
            for item in repaired
            if item.get("kind") == "bank"
        }
        if bank_display_keys:
            filtered: list[dict] = []
            for item in repaired:
                if item.get("kind") == "pdf" and self._display_key(item) in bank_display_keys:
                    dirty = True
                    continue
                filtered.append(item)
            repaired = filtered

        deduped_by_display: dict[tuple[str, str], dict] = {}
        for item in repaired:
            key = (str(item.get("kind") or ""), self._display_key(item))
            previous = deduped_by_display.get(key)
            if previous is None:
                deduped_by_display[key] = item
                continue
            dirty = True
            if self._resource_priority(item) < self._resource_priority(previous):
                deduped_by_display[key] = item
        repaired = list(deduped_by_display.values())

        if dirty or repaired != self._data:
            self._data = repaired
            self._save()

    @staticmethod
    def _display_key(item: dict) -> str:
        name = str(item.get("name") or "").strip()
        fp = str(item.get("file") or "")
        if not name and fp:
            base = os.path.basename(os.path.normpath(fp))
            name = os.path.splitext(base)[0] if item.get("kind") == "pdf" else base
        return os.path.normcase(" ".join(name.replace("\u202f", " ").split())).lower()

    @classmethod
    def _resource_priority(cls, item: dict) -> tuple[int, int, str]:
        fp = os.path.abspath(str(item.get("file") or ""))
        bundled = min(
            cls._path_distance(fp, cls.REPO_ROOT),
            cls._path_distance(fp, cls.APP_DIR),
        )
        kind_order = 0 if item.get("kind") == "bank" else 1
        return (bundled, kind_order, fp)

    @staticmethod
    def _path_distance(path: str, root: str) -> int:
        try:
            common = os.path.commonpath([os.path.abspath(path), os.path.abspath(root)])
        except ValueError:
            return 1
        return 0 if os.path.normcase(common) == os.path.normcase(os.path.abspath(root)) else 1

    def add_bank(self, name: str, folder: str) -> bool:
        from question_bank import validate_bank_folder

        if not os.path.isdir(folder):
            return False
        ok, _ = validate_bank_folder(folder)
        if not ok:
            return False
        ap = os.path.abspath(folder)
        for item in self._data:
            if os.path.abspath(item["file"]) == ap:
                return False
        self._data.append({"name": name, "file": ap, "kind": "bank"})
        self._save()
        return True

    def remove(self, name: str) -> None:
        self._data = [x for x in self._data if x["name"] != name]
        self._save()

    def get_all(self) -> list[dict]:
        self._repair_or_discover_resources()
        valid = [
            x for x in self._data
            if self._is_valid_resource(x)
        ]
        if len(valid) != len(self._data):
            self._data = valid
            self._save()
        return sorted(valid, key=self._extract_class_number)

    def _is_valid_resource(self, item: dict) -> bool:
        fp = self._resolve_path(str(item.get("file") or ""))
        if item.get("kind") == "bank":
            return self._is_valid_bank_folder(fp)
        if item.get("kind") == "pdf":
            return os.path.isfile(fp) and fp.lower().endswith(".pdf")
        return False

    @staticmethod
    def _extract_class_number(book: dict) -> tuple:
        name = book.get("name", "")
        match = re.match(r"^(\d+)\s*класс", name)
        if match:
            kind_order = 0 if book.get("kind") == "bank" else 1
            return (int(match.group(1)), kind_order, name)
        return (999, 9, name)

    def get_by_name(self, name: str) -> Optional[dict]:
        self._repair_or_discover_resources()
        for item in self._data:
            if item["name"] == name and item.get("kind") in ("bank", "pdf"):
                fp = self._resolve_path(str(item.get("file") or ""))
                if self._is_valid_resource(item):
                    out = dict(item)
                    out["file"] = os.path.abspath(fp)
                    return out
        return None

    def save_last_textbook_path(self, path: str) -> None:
        config_file = os.path.join(os.path.dirname(self.REGISTRY_FILE), "config.json")
        try:
            cfg = {}
            if os.path.exists(config_file):
                with open(config_file, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
            cfg["last_textbook"] = path
            with open(config_file, "w", encoding="utf-8") as f:
                json.dump(cfg, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def get_last_textbook_path(self) -> Optional[str]:
        config_file = os.path.join(os.path.dirname(self.REGISTRY_FILE), "config.json")
        try:
            if os.path.exists(config_file):
                with open(config_file, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
                path = cfg.get("last_textbook")
                if path and os.path.exists(path):
                    return path
        except Exception:
            pass
        return None
