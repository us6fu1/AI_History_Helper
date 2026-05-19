"""
Загрузка и вызов локальной GGUF-модели (llama-cpp-python).
По умолчанию авто: CPU-потоки подбираются по ядрам, NVIDIA GPU включается при подходящей сборке.
"""
import os
import sys
import json
import re
import time
import logging
import subprocess
from pathlib import Path
from typing import Optional, Callable

from app_paths import user_data_dir

logger = logging.getLogger(__name__)

# Размер контекста по умолчанию (llama.cpp / GGUF): промпт + ответ.
DEFAULT_N_CTX = 8000
AUTO_N_GPU_LAYERS = -2


def detect_logical_cores() -> int:
    """Логические ядра CPU (включая HyperThreading/SMT)."""
    return os.cpu_count() or 4


def detect_physical_cores() -> int:
    """
    Возвращает число физических ядер CPU.
    Без psutil: пробуем платформо-зависимые источники, иначе делим
    логические ядра на 2 (типичная эвристика для SMT/HyperThreading).
    """
    # 1) psutil — если вдруг поставлен
    try:
        import psutil  # type: ignore
        n = psutil.cpu_count(logical=False)
        if n and n > 0:
            return int(n)
    except Exception:
        pass

    # 2) Linux: /proc/cpuinfo (cpu cores * physical id)
    if sys.platform.startswith("linux"):
        try:
            with open("/proc/cpuinfo", "r") as f:
                cores_per_pkg: dict[str, int] = {}
                cur_pkg = "0"
                for line in f:
                    if line.startswith("physical id"):
                        cur_pkg = line.split(":")[1].strip()
                    elif line.startswith("cpu cores"):
                        cores_per_pkg[cur_pkg] = int(line.split(":")[1].strip())
                if cores_per_pkg:
                    return sum(cores_per_pkg.values())
        except Exception:
            pass

    # 3) Windows: WMIC (deprecated, но в Win10/11 ещё работает)
    if sys.platform == "win32":
        try:
            import subprocess
            out = subprocess.check_output(
                ["wmic", "cpu", "get", "NumberOfCores", "/value"],
                stderr=subprocess.DEVNULL, timeout=2,
            ).decode("ascii", errors="ignore")
            total = 0
            for line in out.splitlines():
                line = line.strip()
                if line.startswith("NumberOfCores="):
                    try:
                        total += int(line.split("=", 1)[1])
                    except ValueError:
                        pass
            if total > 0:
                return total
        except Exception:
            pass

    # 4) Fallback: логические ядра / 2 (если их > 4), иначе как есть
    logical = os.cpu_count() or 4
    return max(1, logical // 2 if logical > 4 else logical)


def choose_auto_cpu_threads() -> int:
    """
    Автоподбор потоков генерации для llama.cpp.
    Обычно лучшие результаты дают физические ядра; для 1-2-ядерных CPU
    логические потоки помогают не просесть по скорости.
    """
    physical = detect_physical_cores()
    logical = detect_logical_cores()
    if os.environ.get("HISTORY_TEST_USE_LOGICAL", "0") == "1":
        return max(1, logical)
    if physical <= 2:
        return max(1, logical)
    return max(1, physical)


def detect_total_ram_gb() -> Optional[float]:
    """Общий объём оперативной памяти устройства в гигабайтах."""
    try:
        import psutil  # type: ignore

        total = getattr(psutil.virtual_memory(), "total", 0)
        if total:
            return float(total) / (1024 ** 3)
    except Exception:
        pass

    if sys.platform == "win32":
        try:
            import ctypes

            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("sullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            stat = MEMORYSTATUSEX()
            stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)):
                return float(stat.ullTotalPhys) / (1024 ** 3)
        except Exception:
            pass

    try:
        pages = os.sysconf("SC_PHYS_PAGES")
        page_size = os.sysconf("SC_PAGE_SIZE")
        if pages and page_size:
            return float(pages * page_size) / (1024 ** 3)
    except Exception:
        pass

    return None


def choose_auto_context_tokens() -> int:
    """
    Автоподбор размера контекста по RAM.
    Чем меньше память, тем меньше контекст, чтобы модель стабильнее грузилась.
    """
    env_ctx = os.environ.get("HISTORY_TEST_N_CTX")
    if env_ctx is not None and str(env_ctx).strip():
        try:
            return max(2048, min(8192, int(str(env_ctx).strip())))
        except ValueError:
            pass

    ram_gb = detect_total_ram_gb()
    if ram_gb is None:
        return DEFAULT_N_CTX
    if ram_gb < 8:
        return 4096
    if ram_gb < 12:
        return 6144
    if ram_gb < 24:
        return 8000
    return 8192


def _run_short_command(args: list[str], timeout: float = 2.0) -> str:
    try:
        return subprocess.check_output(
            args,
            stderr=subprocess.DEVNULL,
            timeout=timeout,
        ).decode("utf-8", errors="ignore")
    except Exception:
        return ""


def detect_nvidia_gpus() -> list[str]:
    """Возвращает найденные NVIDIA GPU без обязательных внешних зависимостей."""
    names: list[str] = []

    out = _run_short_command(
        ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
        timeout=2.0,
    )
    for line in out.splitlines():
        name = line.strip()
        if not name:
            continue
        if "nvidia" not in name.lower():
            name = f"NVIDIA {name}"
        names.append(name)

    if sys.platform == "win32":
        out = _run_short_command(
            ["wmic", "path", "win32_VideoController", "get", "name", "/value"],
            timeout=2.0,
        )
        for line in out.splitlines():
            line = line.strip()
            if line.lower().startswith("name="):
                names.append(line.split("=", 1)[1].strip())

        if not names:
            out = _run_short_command(
                [
                    "powershell",
                    "-NoProfile",
                    "-Command",
                    "Get-CimInstance Win32_VideoController | Select-Object -ExpandProperty Name",
                ],
                timeout=3.0,
            )
            names.extend(line.strip() for line in out.splitlines() if line.strip())

    nvidia_names = []
    seen = set()
    for name in names:
        if "nvidia" not in name.lower():
            continue
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        nvidia_names.append(name)
    return nvidia_names


def llama_supports_gpu_offload() -> bool:
    """
    Проверяет, собран ли установленный llama-cpp-python с поддержкой GPU-offload.
    Наличие видеокарты само по себе недостаточно: CPU-wheel не сможет выгружать слои.
    """
    try:
        from llama_cpp import llama_cpp as llama_backend  # type: ignore

        fn = getattr(llama_backend, "llama_supports_gpu_offload", None)
        if callable(fn):
            return bool(fn())
    except Exception:
        pass
    return False


def choose_auto_gpu_layers() -> int:
    """
    Автоматический выбор GPU-слоёв.
    - NVIDIA + GPU-сборка llama-cpp-python: -1, то есть все возможные слои на GPU.
    - Иначе: 0, стабильный CPU-режим.
    """
    if os.environ.get("HISTORY_TEST_AUTO_GPU", "1") == "0":
        return 0
    if detect_nvidia_gpus() and llama_supports_gpu_offload():
        return -1
    return 0


def detect_chat_format(model_path: str) -> Optional[str]:
    """
    Подбирает chat_format по имени файла модели.
    Покрывает популярные fine-tune'ы (Saiga / Vikhr / Hermes),
    которые обычно наследуют шаблон базы (Llama-3 / Mistral / Qwen).
    """
    name = os.path.basename(model_path).lower()

    # Fine-tune'ы поверх Llama-3 → используют llama-3 ChatML-подобный шаблон.
    llama3_finetunes = (
        "saiga", "saiga_llama3", "vikhr-llama", "vikhrmodels-llama",
        "t-lite", "tlite", "t_lite", "hermes-3-llama", "nous-hermes-3-llama",
    )
    if any(tag in name for tag in llama3_finetunes):
        return "llama-3"

    # Fine-tune'ы поверх Mistral / Nemo
    if "vikhr-nemo" in name or "saiga_nemo" in name or "saiga-nemo" in name:
        return "mistral-instruct"

    if "qwen" in name:
        # Qwen3.5/Qwen3/Qwen2.5/Qwen2 — ChatML; llama-cpp понимает "qwen".
        return "qwen"
    if "mistral" in name or "mixtral" in name or "nemo" in name:
        return "mistral-instruct"
    if (
        "llama-3.2" in name or "llama3.2" in name or
        "llama-3.1" in name or "llama3.1" in name or
        "llama-3" in name or "llama3" in name
    ):
        return "llama-3"
    if "llama-2" in name or "llama2" in name:
        return "llama-2"
    if "phi-3.5" in name or "phi3.5" in name or "phi-3" in name or "phi3" in name:
        return "phi-3"
    if "gemma-3" in name or "gemma3" in name or "gemma-2" in name or "gemma2" in name or "gemma" in name:
        return "gemma"
    return None


class ModelRunner:
    """
    Обёртка над llama-cpp-python для запуска GGUF-моделей.
    По умолчанию — авто: CPU-потоки по ядрам, NVIDIA GPU при подходящей сборке.
    Оптимизирована для Qwen3.5-4B / Qwen3-4B / Qwen2.5-3B (Q4_K_M).
    """

    DEFAULT_PARAMS = {
        "n_ctx": None,             # None → авто по оперативной памяти устройства
        "n_threads": None,       # None → авто (физические ядра)
        "n_gpu_layers": AUTO_N_GPU_LAYERS,  # -2 = авто; 0 = CPU; -1 = все слои на GPU
        "n_batch": 768,          # 768 — sweet-spot между ускорением prompt
                                 # processing и memory-bound потолком на DDR4.
        "n_ubatch": 768,         # micro-batch такой же для согласованности.
        "temperature": 0.3,
        "top_p": 0.9,
        "top_k": 40,
        "repeat_penalty": 1.1,
        "max_tokens": 2048,
        "verbose": False,
        "use_mmap": True,        # mmap-загрузка GGUF — мгновенный старт
        "use_mlock": False,      # не блокируем RAM (важно для 16 GB)
    }

    def __init__(self):
        self.llm = None
        self.model_path: Optional[str] = None
        self.model_name: str = ""
        self.is_loaded: bool = False
        self.params: dict = dict(self.DEFAULT_PARAMS)
        self.using_gpu: bool = False
        # Поддержка GPU зависит не только от видеокарты, но и от сборки llama-cpp-python.
        self.gpu_supported: bool = False
        # Сохранённые kwargs последней загрузки — для безопасного
        # «горячего» rebuild без draft_model при ошибке spec-decoding.
        self._last_load_kwargs: dict = {}
        self._spec_failed_once: bool = False

    # ------------------------------------------------------------------ #
    #  Загрузка модели                                                     #
    # ------------------------------------------------------------------ #

    def load_model(
        self,
        model_path: str,
        n_ctx: Optional[int] = None,
        n_threads: Optional[int] = None,
        n_gpu_layers: int = AUTO_N_GPU_LAYERS,
        n_batch: int = 768,
        n_ubatch: int = 768,
        use_mmap: bool = True,
        use_mlock: bool = False,
        progress_callback: Optional[Callable[[str], None]] = None,
        **_ignored,
    ) -> bool:
        """
        Загружает GGUF-модель. Возвращает True при успехе.

        Аргументы:
            n_ctx: размер контекстного окна. None → авто по RAM устройства.
            n_threads: число потоков. None → физические ядра.
            n_gpu_layers: -2 = авто; 0 = CPU; -1 часто означает «все слои» в llama.cpp.
                Переменная окружения HISTORY_TEST_N_GPU_LAYERS переопределяет это значение.
            n_batch: размер батча. На CPU 128–256 — оптимум.
            use_mmap: True — модель грузится через mmap (мгновенный старт).
            use_mlock: True — модель блокируется в RAM (не своп). Для 16 GB лучше False.

        Любые лишние kwargs (например, flash_attn / kv_cache_quant из старых вызовов)
        тихо игнорируются — это CPU-сборка.
        """
        if n_ctx is None:
            n_ctx = choose_auto_context_tokens()

        if not os.path.exists(model_path):
            raise FileNotFoundError(
                f"Модель не найдена: {model_path}\n"
                "Скачайте GGUF-файл и укажите путь к нему."
            )

        if not model_path.lower().endswith(".gguf"):
            raise ValueError("Поддерживаются только файлы в формате .gguf")

        try:
            from llama_cpp import Llama
        except ImportError:
            raise ImportError(
                "Библиотека llama-cpp-python не установлена.\n"
                "Установите: pip install llama-cpp-python"
            )

        # Prompt-lookup speculative decoding (без второй модели):
        # модель сама ищет n-граммы в уже выведенном тексте и одним
        # forward'ом подтверждает 5–10 токенов сразу.
        #
        # ВАЖНО: в текущей версии llama-cpp-python (0.3.x) есть баг:
        # связка draft_model + stream=True иногда ломается с ошибкой
        # "could not broadcast input array from shape (N,) into shape (0,)".
        # Поэтому по умолчанию speculative ВЫКЛЮЧЕН.
        #
        # Включить опционально (на свой страх и риск):
        #   HISTORY_TEST_SPECULATIVE = 1
        # При ошибке broadcast мы автоматически перезагрузим модель без
        # draft_model и продолжим работу.
        #
        # Тонкая настройка:
        #   HISTORY_TEST_SPEC_TOKENS = 10 (4–16)
        #   HISTORY_TEST_SPEC_NGRAM  = 2  (2–3)
        draft_model = None
        spec_enabled = os.environ.get("HISTORY_TEST_SPECULATIVE", "1") == "1"
        if spec_enabled:
            try:
                from llama_cpp.llama_speculative import LlamaPromptLookupDecoding
                spec_tokens = int(os.environ.get("HISTORY_TEST_SPEC_TOKENS", "10"))
                spec_ngram = int(os.environ.get("HISTORY_TEST_SPEC_NGRAM", "2"))
                # Безопасные границы: на CPU слишком большие spec_tokens
                # увеличивают draft-overhead если предсказания не подтверждаются.
                spec_tokens = max(4, min(16, spec_tokens))
                spec_ngram = max(2, min(3, spec_ngram))
                draft_model = LlamaPromptLookupDecoding(
                    num_pred_tokens=spec_tokens,
                    max_ngram_size=spec_ngram,
                )
            except Exception as e:
                logger.warning(f"Speculative decoding недоступен: {e}")
                draft_model = None

        # GPU-слои: из аргумента load_model, с переопределением через ENV
        # (удобно для демо на ноутбуке с CUDA без правки UI).
        try:
            n_gl = int(n_gpu_layers)
        except (TypeError, ValueError):
            n_gl = AUTO_N_GPU_LAYERS
        env_gl = os.environ.get("HISTORY_TEST_N_GPU_LAYERS")
        auto_gpu = n_gl == AUTO_N_GPU_LAYERS
        if env_gl is not None and str(env_gl).strip() != "":
            try:
                n_gl = int(str(env_gl).strip())
                auto_gpu = n_gl == AUTO_N_GPU_LAYERS
            except ValueError:
                pass
        if auto_gpu:
            n_gl = choose_auto_gpu_layers()

        # Авто-выбор числа потоков:
        #   по умолчанию — физические ядра (для llama.cpp обычно оптимум).
        # Однако на гибридных CPU (Intel 12+ gen, P+E ядра) или когда видно
        # недозагрузку CPU, бывает выгоднее использовать ВСЕ логические ядра.
        # Управляется ENV: HISTORY_TEST_USE_LOGICAL=1 → берём логические.
        physical = detect_physical_cores()
        logical = detect_logical_cores()

        if n_threads is None or n_threads <= 0:
            n_threads = choose_auto_cpu_threads()
        n_threads = max(1, int(n_threads))

        # n_threads_batch (для prompt processing) выгоднее держать = логическим
        # ядрам: это чисто матричные операции, и SMT/HT их хорошо ускоряет.
        # Для генерации (n_threads) лучше физические, потому что каждый
        # шаг — memory-bound и HT не даёт прироста.
        n_threads_batch = max(n_threads, logical)

        chat_format = detect_chat_format(model_path)

        self.params.update({
            "n_ctx": n_ctx,
            "n_threads": n_threads,
            "n_threads_batch": n_threads_batch,
            "n_gpu_layers": n_gl,
            "n_batch": n_batch,
            "n_ubatch": n_ubatch,
            "use_mmap": use_mmap,
            "use_mlock": use_mlock,
            "speculative": draft_model is not None,
        })

        if progress_callback:
            spec_str = "spec=ON" if draft_model is not None else "spec=off"
            gpu_names = detect_nvidia_gpus()
            gpu_note = ""
            if auto_gpu:
                if n_gl != 0:
                    gpu_note = f" · авто-GPU: {', '.join(gpu_names[:2])}"
                elif gpu_names:
                    gpu_note = " · NVIDIA найдена, но llama-cpp-python без GPU-offload"
            backend = f"GPU n_gpu_layers={n_gl}" if n_gl != 0 else "CPU"
            progress_callback(
                f"Загрузка модели… [{backend}{gpu_note} · ядра физ./лог.={physical}/{logical} · "
                f"генерация={n_threads} пот · prompt={n_threads_batch} пот · "
                f"n_batch={n_batch} · n_ctx={n_ctx} · {spec_str}]"
            )

        kwargs = {
            "model_path": model_path,
            "n_ctx": n_ctx,
            "n_threads": n_threads,
            "n_threads_batch": n_threads_batch,
            "n_gpu_layers": n_gl,
            "n_batch": n_batch,
            "n_ubatch": n_ubatch,
            "use_mmap": use_mmap,
            "use_mlock": use_mlock,
            "verbose": False,
        }
        if chat_format:
            kwargs["chat_format"] = chat_format
        if draft_model is not None:
            kwargs["draft_model"] = draft_model

        def instantiate_llama(run_kwargs: dict):
            try:
                return Llama(**run_kwargs), run_kwargs
            except TypeError as e:
                # Старая версия llama-cpp без n_threads_batch / n_ubatch / draft_model:
                # выкидываем неподдерживаемые ключи и пробуем ещё раз.
                logger.warning(f"Старая версия llama-cpp, упрощаю параметры: {e}")
                compatible_kwargs = dict(run_kwargs)
                for key in ("n_threads_batch", "n_ubatch", "use_mmap",
                            "use_mlock", "draft_model"):
                    compatible_kwargs.pop(key, None)
                self.params["speculative"] = False
                return Llama(**compatible_kwargs), compatible_kwargs

        t0 = time.time()
        try:
            self.llm, kwargs = instantiate_llama(kwargs)
        except Exception as e:
            if auto_gpu and n_gl != 0:
                logger.warning(f"Авто-GPU не загрузился, пробую CPU: {e}")
                if progress_callback:
                    progress_callback("GPU-режим не подошёл, пробую стабильный CPU-режим…")
                n_gl = 0
                kwargs["n_gpu_layers"] = 0
                self.params["n_gpu_layers"] = 0
                self.llm, kwargs = instantiate_llama(kwargs)
            else:
                raise
        self.using_gpu = n_gl != 0
        self.gpu_supported = llama_supports_gpu_offload()

        elapsed = time.time() - t0
        self.model_path = model_path
        self.model_name = Path(model_path).stem
        self.is_loaded = True

        spec_label = "spec=ON" if self.params.get("speculative") else "spec=off"
        backend_short = f"GPU×{n_gl}" if n_gl != 0 else "CPU"
        if progress_callback:
            progress_callback(
                f"Модель загружена за {elapsed:.1f} сек. "
                f"({backend_short} · gen={n_threads}п · prompt={n_threads_batch}п · "
                f"n_batch={n_batch} · {spec_label})"
            )

        logger.info(
            f"Модель загружена: {self.model_name} "
            f"({elapsed:.1f}s, {backend_short}, gen={n_threads}/prompt={n_threads_batch} потоков, "
            f"n_batch={n_batch}, {spec_label})"
        )

        # Сохраняем фактически принятые kwargs (БЕЗ draft_model) — для возможной
        # «горячей» перезагрузки без spec-decoding при runtime-ошибке.
        self._last_load_kwargs = dict(kwargs)
        self._last_load_kwargs.pop("draft_model", None)
        return True

    def _reload_without_speculative(self) -> bool:
        """
        Перезагружает модель БЕЗ draft_model. Вызывается при runtime-ошибке
        speculative decoding ("could not broadcast input array..." и т.п.).
        """
        if not self._last_load_kwargs:
            return False
        try:
            from llama_cpp import Llama
        except ImportError:
            return False

        logger.warning("Spec-decoding сломался — перезагружаю модель без draft_model")
        try:
            if self.llm is not None:
                del self.llm
                self.llm = None
            self.llm = Llama(**self._last_load_kwargs)
            self.params["speculative"] = False
            self._spec_failed_once = True
            return True
        except Exception as e:
            logger.error(f"Не удалось перезагрузить модель без spec-decoding: {e}")
            return False

    def unload_model(self):
        """Выгружает модель из памяти."""
        if self.llm is not None:
            del self.llm
            self.llm = None
        self.is_loaded = False
        self.using_gpu = False
        self.gpu_supported = False
        self.model_path = None
        self.model_name = ""

    @staticmethod
    def _is_speculative_runtime_bug(exc: BaseException) -> bool:
        """
        Сигнатура известного бага llama-cpp-python со speculative + stream:
        ValueError: could not broadcast input array from shape (N,) into shape (0,)
        """
        msg = str(exc).lower()
        return "could not broadcast" in msg and "shape" in msg


    def generate(
        self,
        prompt: str,
        max_tokens: int = 2048,
        temperature: float = 0.3,
        stop: Optional[list[str]] = None,
    ) -> str:
        """Генерирует текст по промпту."""
        if not self.is_loaded or self.llm is None:
            raise RuntimeError("Модель не загружена. Загрузите модель в настройках.")

        if stop is None:
            stop = ["```", "<|im_end|>", "</s>"]

        try:
            response = self.llm(
                prompt,
                max_tokens=max_tokens,
                temperature=temperature,
                top_p=self.params["top_p"],
                top_k=self.params["top_k"],
                repeat_penalty=self.params["repeat_penalty"],
                stop=stop,
                echo=False,
            )
            return response["choices"][0]["text"].strip()
        except Exception as e:
            logger.error(f"Ошибка генерации: {e}")
            raise RuntimeError(f"Ошибка при генерации: {e}")

    def generate_chat(
        self,
        messages: list[dict],
        max_tokens: int = 2048,
        temperature: float = 0.3,
        response_format: Optional[dict] = None,
    ) -> str:
        """
        Генерация в формате chat (system/user/assistant).

        response_format: при поддержке моделью можно передать
        {"type": "json_object"} — это включает grammar-ограничение
        вывода в валидный JSON. Это значительно ускоряет получение
        результата (модель не «промахивается» с форматом).
        """
        if not self.is_loaded or self.llm is None:
            raise RuntimeError("Модель не загружена.")

        kwargs = {
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "top_p": self.params["top_p"],
            "top_k": self.params["top_k"],
            "repeat_penalty": self.params["repeat_penalty"],
            "stop": ["<|im_end|>", "</s>"],
        }
        if response_format is not None:
            kwargs["response_format"] = response_format

        try:
            response = self.llm.create_chat_completion(**kwargs)
            return response["choices"][0]["message"]["content"].strip()
        except TypeError:
            # Старая версия не поддерживает response_format
            kwargs.pop("response_format", None)
            response = self.llm.create_chat_completion(**kwargs)
            return response["choices"][0]["message"]["content"].strip()
        except Exception as e:
            # Авто-fallback на не-spec режим при известном баге.
            if (
                self.params.get("speculative")
                and not self._spec_failed_once
                and self._is_speculative_runtime_bug(e)
            ):
                if self._reload_without_speculative():
                    response = self.llm.create_chat_completion(**kwargs)
                    return response["choices"][0]["message"]["content"].strip()
            logger.error(f"Ошибка chat-генерации: {e}")
            raise RuntimeError(f"Ошибка при генерации: {e}")

    def generate_chat_stream(
        self,
        messages: list[dict],
        max_tokens: int = 2048,
        temperature: float = 0.3,
        response_format: Optional[dict] = None,
        stop_after_questions: Optional[int] = None,
    ) -> str:
        """
        Стриминговая chat-генерация с РАЗБОРОМ JSON НА ЛЕТУ.

        Главная идея: каждый раз, когда модель закрывает очередной объект
        вопроса в массиве "questions", мы вытаскиваем строку этого объекта
        и валидируем как JSON. Все валидные объекты копятся в список.

        Это спасает в трёх сценариях, которые раньше давали 0 вопросов:
          (a) early-stop — собрали ровно N и оборвали стрим;
          (b) модель сорвалась посреди (Q2/Q3 квантизации часто так делают
              — недописывает кавычки, проглатывает запятые) → у нас всё
              равно остаются ВСЕ ранее закрытые объекты;
          (c) llama-cpp baz with spec/stream broadcast-error → если до
              ошибки модель успела закрыть N объектов, мы их сохраняем.

        Возвращаем гарантированно валидный JSON
        '{"questions":[obj1,obj2,...]}' — даже если модель в целом
        выдала мусор. Если ни одного валидного объекта собрать не
        удалось — пробрасываем исходную ошибку или возвращаем сырой текст
        (чтобы старый extract_json мог попробовать свои стратегии).
        """
        if not self.is_loaded or self.llm is None:
            raise RuntimeError("Модель не загружена.")

        kwargs = {
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "top_p": self.params["top_p"],
            "top_k": self.params["top_k"],
            "repeat_penalty": self.params["repeat_penalty"],
            "stop": ["<|im_end|>", "</s>"],
            "stream": True,
        }
        if response_format is not None:
            kwargs["response_format"] = response_format

        # Внутренняя функция, чтобы можно было перезапустить стрим без spec.
        def _run_stream() -> tuple[str, list[str], Optional[BaseException]]:
            try:
                stream = self.llm.create_chat_completion(**kwargs)
            except TypeError:
                kwargs.pop("response_format", None)
                try:
                    stream = self.llm.create_chat_completion(**kwargs)
                except TypeError:
                    return ("__NOSTREAM__", [], None)
            except Exception as ee:
                return ("", [], ee)

            buf_parts_local: list[str] = []
            text_so_far = ""
            collected: list[str] = []
            bracket_stack: list[str] = []
            in_string_l = False
            escape_l = False
            obj_start: Optional[int] = None  # позиция { начала объекта-вопроса
            inside_questions = False
            completed = 0
            stop_now_l = False
            err_local: Optional[BaseException] = None

            try:
                try:
                    for chunk in stream:
                        try:
                            delta = chunk["choices"][0].get("delta") or {}
                            piece = delta.get("content", "")
                        except (KeyError, IndexError, TypeError):
                            piece = ""
                        if not piece:
                            continue
                        buf_parts_local.append(piece)
                        for ch in piece:
                            pos = len(text_so_far)
                            text_so_far += ch
                            # Парсер строк / escape
                            if escape_l:
                                escape_l = False
                                continue
                            if in_string_l:
                                if ch == "\\":
                                    escape_l = True
                                elif ch == '"':
                                    in_string_l = False
                                continue
                            if ch == '"':
                                in_string_l = True
                                continue
                            if ch == "[":
                                bracket_stack.append("[")
                                # Первый массив = массив "questions" (наш промпт)
                                if not inside_questions:
                                    inside_questions = True
                            elif ch == "]":
                                if bracket_stack and bracket_stack[-1] == "[":
                                    bracket_stack.pop()
                            elif ch == "{":
                                # Если открываем объект на 2-м уровне внутри
                                # questions — запоминаем его старт.
                                if (
                                    inside_questions
                                    and len(bracket_stack) == 2
                                    and bracket_stack[0] == "{"
                                    and bracket_stack[1] == "["
                                ):
                                    obj_start = pos
                                bracket_stack.append("{")
                            elif ch == "}":
                                if bracket_stack and bracket_stack[-1] == "{":
                                    bracket_stack.pop()
                                # Закрылся объект на 2-м уровне в questions
                                if (
                                    inside_questions
                                    and obj_start is not None
                                    and len(bracket_stack) == 2
                                    and bracket_stack[0] == "{"
                                    and bracket_stack[1] == "["
                                ):
                                    obj_str = text_so_far[obj_start:pos + 1]
                                    # Валидируем — если корректный JSON,
                                    # сохраняем; если нет, тихо пропускаем
                                    # (например, модель забыла кавычку).
                                    try:
                                        json.loads(obj_str)
                                        collected.append(obj_str)
                                        completed += 1
                                    except json.JSONDecodeError:
                                        pass
                                    obj_start = None
                                    if (
                                        stop_after_questions is not None
                                        and completed >= stop_after_questions
                                    ):
                                        stop_now_l = True
                                        break
                        if stop_now_l:
                            break
                except Exception as ee:
                    err_local = ee
            finally:
                close_fn = getattr(stream, "close", None)
                if callable(close_fn):
                    try:
                        close_fn()
                    except Exception:
                        pass

            return ("".join(buf_parts_local), collected, err_local)

        text, collected_objects, stream_error = _run_stream()

        # Старая версия llama-cpp без stream → fallback на обычный generate_chat
        if text == "__NOSTREAM__":
            return self.generate_chat(
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
                response_format=response_format,
            )

        # Spec-decoding баг (broadcast) → ровно один retry без draft_model.
        # Используем СТРИМ повторно, чтобы не потерять сбор объектов на лету.
        if (
            stream_error is not None
            and self.params.get("speculative")
            and not self._spec_failed_once
            and self._is_speculative_runtime_bug(stream_error)
            and self._reload_without_speculative()
        ):
            logger.warning(
                "Stream + speculative дал broadcast-error → повторяю стрим без spec."
            )
            text, collected_objects, stream_error = _run_stream()

        # Если есть хотя бы один валидный объект-вопрос — возвращаем
        # гарантированно валидный JSON, независимо от того, был ли error.
        if collected_objects:
            return '{"questions":[' + ",".join(collected_objects) + "]}"

        # Объектов нет, но есть текст без ошибки — отдаём как есть,
        # чтобы extract_json мог попробовать свои стратегии (regex / fix).
        if stream_error is None:
            return text.strip()

        # Объектов нет И есть ошибка — пробрасываем.
        logger.error(f"Ошибка стрима без собранных объектов: {stream_error}")
        raise RuntimeError(f"Ошибка при генерации: {stream_error}")

    # ------------------------------------------------------------------ #
    #  Утилиты                                                             #
    # ------------------------------------------------------------------ #

    def extract_json(self, text: str) -> Optional[list | dict]:
        """Извлекает JSON из ответа модели; пробует несколько стратегий."""
        text = re.sub(r"```(?:json)?\s*", "", text)
        text = re.sub(r"```\s*", "", text).strip()

        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        array_match = re.search(r"\[[\s\S]*\]", text)
        if array_match:
            try:
                return json.loads(array_match.group())
            except json.JSONDecodeError:
                pass

        obj_match = re.search(r"\{[\s\S]*\}", text)
        if obj_match:
            try:
                return json.loads(obj_match.group())
            except json.JSONDecodeError:
                pass

        fixed = self._fix_truncated_json(text)
        if fixed:
            try:
                return json.loads(fixed)
            except json.JSONDecodeError:
                pass

        logger.warning(f"Не удалось извлечь JSON из ответа: {text[:200]}…")
        return None

    @staticmethod
    def _fix_truncated_json(text: str) -> Optional[str]:
        """Пытается исправить обрезанный JSON, дополнив скобки."""
        depth_square = 0
        depth_curly = 0
        in_string = False
        escape = False

        for ch in text:
            if escape:
                escape = False
                continue
            if ch == "\\" and in_string:
                escape = True
                continue
            if ch == '"':
                in_string = not in_string
                continue
            if in_string:
                continue
            if ch == "[":
                depth_square += 1
            elif ch == "]":
                depth_square -= 1
            elif ch == "{":
                depth_curly += 1
            elif ch == "}":
                depth_curly -= 1

        suffix = "}" * depth_curly + "]" * depth_square
        if suffix:
            return text.rstrip(",\n\r ") + suffix
        return None

    def model_info(self) -> dict:
        n_gl = int(self.params.get("n_gpu_layers", 0) or 0)
        return {
            "loaded": self.is_loaded,
            "name": self.model_name,
            "path": self.model_path,
            "n_ctx": self.params.get("n_ctx"),
            "n_threads": self.params.get("n_threads"),
            "n_threads_batch": self.params.get("n_threads_batch"),
            "n_batch": self.params.get("n_batch"),
            "n_ubatch": self.params.get("n_ubatch"),
            "n_gpu_layers": n_gl,
            "speculative": self.params.get("speculative", False),
            "using_gpu": bool(getattr(self, "using_gpu", False)),
            "gpu_supported": bool(getattr(self, "gpu_supported", False)),
        }


class ModelRegistry:
    """Хранит список путей к GGUF-моделям."""

    REGISTRY_FILE = os.path.join(
        str(user_data_dir()),
        "models.json"
    )

    RECOMMENDED = [
        {
            "name": "Llama-3.2-3B-Instruct (Q4_K_M) — самая быстрая",
            "description": (
                "Meta, 3B, ~1.9 GB. На CPU быстрее Qwen3.5-4B на 30–40% "
                "(~10 ток/с против ~7). Свежее поколение Llama, качество "
                "выше Qwen2.5-3B. Русский — нормальный, JSON-формат "
                "соблюдает хорошо. ЛУЧШИЙ ВЫБОР, если важна скорость."
            ),
            "url": "https://huggingface.co/bartowski/Llama-3.2-3B-Instruct-GGUF",
            "filename": "Llama-3.2-3B-Instruct-Q4_K_M.gguf",
        },
        {
            "name": "Phi-3.5-mini-instruct (3.8B Q4_K_M) — для JSON",
            "description": (
                "Microsoft, 3.8B, ~2.3 GB. На CPU ~8 ток/с. Лучше всех "
                "следует JSON-формату (заточена под structured output). "
                "Логика отличная, русский — средний (термины могут "
                "переводиться неточно). Хороша если важно строгое "
                "соблюдение схемы вопроса."
            ),
            "url": "https://huggingface.co/bartowski/Phi-3.5-mini-instruct-GGUF",
            "filename": "Phi-3.5-mini-instruct-Q4_K_M.gguf",
        },
        {
            "name": "Gemma-3-4B-it (Q4_K_M) — баланс",
            "description": (
                "Google, 4B (Instruct-Tuned), ~2.5 GB. Скорость как у "
                "Qwen3.5-4B (~7 ток/с), но другой характер ответов. "
                "Русский — хороший. Хорошая запасная 4B-модель."
            ),
            "url": "https://huggingface.co/bartowski/gemma-3-4b-it-GGUF",
            "filename": "gemma-3-4b-it-Q4_K_M.gguf",
        },
        {
            "name": "Qwen3.5-4B (Q4_K_M) — текущая",
            "description": "Текущая модель проекта, ~2.5 GB, ~7 ток/с на CPU. Хорошее качество и русский.",
            "url": "",
            "filename": "Qwen3.5-4B.Q4_K_M.gguf",
        },
        {
            "name": "Qwen3.5-4B (Q3_K_M) — Qwen + скорость",
            "description": (
                "Та же Qwen3.5-4B, но ~2.0 GB. На CPU быстрее Q4_K_M на "
                "20–30%, качество просаживается на 1–3%."
            ),
            "url": "",
            "filename": "Qwen3.5-4B.Q3_K_M.gguf",
        },
        {
            "name": "Saiga-Llama3-8B (Q4_K_M) — лучший русский",
            "description": (
                "Илья Гусев, fine-tune Llama 3 8B на русском. ~4.7 GB, "
                "~3.5 ток/с на CPU (≈в 2 раза медленнее 4B). Берите если "
                "качество русского важнее скорости. ≥8 GB RAM."
            ),
            "url": "https://huggingface.co/IlyaGusev/saiga_llama3_8b_gguf",
            "filename": "model-q4_K.gguf",
        },
        {
            "name": "Qwen2.5-3B-Instruct (Q4_K_M)",
            "description": "Старая лёгкая модель ~2 GB. Быстрая, но качество ниже Llama-3.2-3B.",
            "url": "https://huggingface.co/Qwen/Qwen2.5-3B-Instruct-GGUF",
            "filename": "qwen2.5-3b-instruct-q4_k_m.gguf",
        },
        {
            "name": "Qwen2.5-7B-Instruct (Q4_K_M)",
            "description": "Качество выше, ~4.5 GB, на CPU ~3.5 ток/с (≥16 GB RAM).",
            "url": "https://huggingface.co/Qwen/Qwen2.5-7B-Instruct-GGUF",
            "filename": "qwen2.5-7b-instruct-q4_k_m.gguf",
        },
    ]

    def __init__(self):
        os.makedirs(os.path.dirname(self.REGISTRY_FILE), exist_ok=True)
        self._data: list[dict] = self._load()

    def _load(self) -> list[dict]:
        if os.path.exists(self.REGISTRY_FILE):
            try:
                with open(self.REGISTRY_FILE, "r", encoding="utf-8-sig") as f:
                    return json.load(f)
            except Exception:
                return []
        return []

    def _save(self):
        with open(self.REGISTRY_FILE, "w", encoding="utf-8") as f:
            json.dump(self._data, f, ensure_ascii=False, indent=2)

    def add(self, name: str, filepath: str) -> bool:
        if not os.path.exists(filepath):
            return False
        for item in self._data:
            if item["file"] == filepath:
                return False
        self._data.append({"name": name, "file": filepath})
        self._save()
        return True

    def remove(self, name: str):
        self._data = [x for x in self._data if x["name"] != name]
        self._save()

    def get_all(self) -> list[dict]:
        valid = [x for x in self._data if os.path.exists(x["file"])]
        if len(valid) != len(self._data):
            self._data = valid
            self._save()
        return self._data

    def get_last_used(self) -> Optional[dict]:
        all_m = self.get_all()
        return all_m[-1] if all_m else None

    def save_last_model_path(
        self, path: str, n_gpu_layers: Optional[int] = None
    ):
        config_file = os.path.join(os.path.dirname(self.REGISTRY_FILE), "config.json")
        try:
            cfg = {}
            if os.path.exists(config_file):
                with open(config_file, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
            cfg["last_model"] = path
            if n_gpu_layers is not None:
                cfg["last_n_gpu_layers"] = int(n_gpu_layers)
                cfg["last_gpu_layers_auto"] = int(n_gpu_layers) == AUTO_N_GPU_LAYERS
            with open(config_file, "w", encoding="utf-8") as f:
                json.dump(cfg, f, ensure_ascii=False)
        except Exception:
            pass

    def get_last_n_gpu_layers(self) -> int:
        """Последняя настройка GPU-слоёв (-2 = авто, 0 = только CPU)."""
        config_file = os.path.join(os.path.dirname(self.REGISTRY_FILE), "config.json")
        try:
            if os.path.exists(config_file):
                with open(config_file, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
                if cfg.get("last_gpu_layers_auto", True):
                    return AUTO_N_GPU_LAYERS
                return int(cfg.get("last_n_gpu_layers", 0))
        except Exception:
            pass
        return AUTO_N_GPU_LAYERS

    def get_last_model_path(self) -> Optional[str]:
        config_file = os.path.join(os.path.dirname(self.REGISTRY_FILE), "config.json")
        try:
            if os.path.exists(config_file):
                with open(config_file, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
                path = cfg.get("last_model")
                if path and os.path.exists(path):
                    return path
        except Exception:
            pass
        return None
