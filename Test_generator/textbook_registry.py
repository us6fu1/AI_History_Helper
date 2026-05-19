"""
Реестр банков вопросов (папки с JSON). Файл data/textbooks.json сохранён для совместимости.
"""
from __future__ import annotations

import json
import os
import re
from typing import Optional


class TextbookRegistry:
    APP_DIR = os.path.dirname(os.path.abspath(__file__))
    REPO_ROOT = os.path.dirname(APP_DIR)
    BUNDLED_BANKS_DIR = os.path.join(REPO_ROOT, "Materials", "Textbooks")
    REGISTRY_FILE = os.path.join(
        APP_DIR,
        "data",
        "textbooks.json",
    )

    def __init__(self):
        os.makedirs(os.path.dirname(self.REGISTRY_FILE), exist_ok=True)
        self._data: list[dict] = self._load()
        self._migrate_kinds()
        self._repair_or_discover_banks()

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
        if os.path.exists(self.REGISTRY_FILE):
            try:
                with open(self.REGISTRY_FILE, "r", encoding="utf-8") as f:
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

    def _repair_or_discover_banks(self) -> None:
        dirty = False
        repaired: list[dict] = []
        seen_paths: set[str] = set()

        for item in self._data:
            if item.get("kind") != "bank":
                continue
            fp = self._resolve_path(str(item.get("file") or ""))
            if not self._is_valid_bank_folder(fp):
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

            ap = os.path.abspath(str(item["file"]))
            key = os.path.normcase(ap)
            if key in seen_paths:
                dirty = True
                continue
            seen_paths.add(key)
            item = dict(item)
            item["file"] = ap
            repaired.append(item)

        for bank in self._discover_bundled_banks():
            key = os.path.normcase(os.path.abspath(bank["file"]))
            if key in seen_paths:
                continue
            seen_paths.add(key)
            repaired.append(bank)
            dirty = True

        if dirty or repaired != self._data:
            self._data = repaired
            self._save()

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
        self._repair_or_discover_banks()
        valid = [
            x for x in self._data
            if self._is_valid_bank_folder(self._resolve_path(str(x.get("file") or "")))
        ]
        if len(valid) != len(self._data):
            self._data = valid
            self._save()
        banks = [x for x in valid if x.get("kind") == "bank"]
        return sorted(banks, key=self._extract_class_number)

    @staticmethod
    def _extract_class_number(book: dict) -> tuple:
        name = book.get("name", "")
        match = re.match(r"^(\d+)\s*класс", name)
        if match:
            return (int(match.group(1)), name)
        return (999, name)

    def get_by_name(self, name: str) -> Optional[dict]:
        self._repair_or_discover_banks()
        for item in self._data:
            if item["name"] == name and item.get("kind") == "bank":
                fp = self._resolve_path(str(item.get("file") or ""))
                if self._is_valid_bank_folder(fp):
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
