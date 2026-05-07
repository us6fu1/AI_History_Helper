"""
Реестр банков вопросов (папки с JSON). Файл data/textbooks.json сохранён для совместимости.
"""
from __future__ import annotations

import json
import os
import re
from typing import Optional


class TextbookRegistry:
    REGISTRY_FILE = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "data",
        "textbooks.json",
    )

    def __init__(self):
        os.makedirs(os.path.dirname(self.REGISTRY_FILE), exist_ok=True)
        self._data: list[dict] = self._load()
        self._migrate_kinds()

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
        valid = [x for x in self._data if os.path.exists(x["file"])]
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
        for item in self._data:
            if item["name"] == name and item.get("kind") == "bank":
                fp = item.get("file", "")
                if fp and os.path.exists(fp) and os.path.isdir(fp):
                    return item
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
