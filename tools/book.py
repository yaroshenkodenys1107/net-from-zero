#!/usr/bin/env python3
"""Инструменты книги «Сети с нуля».

Подкоманды:
  scaffold     создать папки и файлы по PLAN.md (существующие не трогает)
  status       статусы всех глав и подглав
  next         следующая подглава для работы
  check [id]   проверка терминов и аббревиатур

Задание — tools/SPEC.md, соглашения — CONVENTIONS.md. Зависимость — pyyaml.
"""

import argparse
import re
import sys
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover
    sys.exit("Нужен pyyaml: pip install -r requirements.txt")

ROOT = Path(__file__).resolve().parent.parent

STATUSES = ["план", "черновик", "проверка", "нужен человек", "принято"]
DONE_STATUSES = {"принято", "нужен человек"}

# Указатели в конце книги: буква в PLAN.md → (номер папки, имя папки).
INDEX_FOLDERS = {
    "А": (90, "90-ukazatel-simptomy"),
    "Б": (91, "91-ukazatel-priemy"),
    "В": (92, "92-glossariy"),
}

TRANSLIT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e",
    "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "h", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "sch",
    "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
}

RE_CHAPTER = re.compile(r"^(\d+)\.\s+(.+)$")
RE_SUB = re.compile(r"^\s+(\d+)\.(\d+)\s+(.+)$")
RE_PART = re.compile(r"^ЧАСТЬ\s+([IVXLC]+)\.\s*(.+)$")
RE_INDEX_ENTRY = re.compile(r"^([А-ЯЁ])\.\s+(.+)$")
RE_TAGS = re.compile(r"\s*\[(П\d+(?:\s*(?:[–—-]|,)\s*П\d+)*)\]")
RE_REF = re.compile(r"\s*\(→[^)]*\)")


# ---------------------------------------------------------------- общее

def fail(msg):
    print(msg, file=sys.stderr)
    sys.exit(2)


def slugify(text, max_words):
    """Транслит: до max_words значимых слов (3+ символа), короткие слова
    между ними сохраняются: «Что происходит с пакетами» → chto-proishodit-s-paketami."""
    parts, significant = [], 0
    for word in text.split():
        clean = ""
        for ch in word.lower():
            if ch in TRANSLIT:
                clean += TRANSLIT[ch]
            elif ch.isascii() and ch.isalnum():
                clean += ch
            else:
                clean += "-"
        clean = re.sub(r"-+", "-", clean).strip("-")
        if not clean:
            continue
        parts.append(clean)
        if len(clean) >= 3:
            significant += 1
            if significant >= max_words:
                break
    return "-".join(parts) or "x"


def expand_tags(raw):
    """«П3–П5» → [П3, П4, П5]; «П3, П4» → [П3, П4]."""
    result = []
    for piece in raw.split(","):
        piece = piece.strip()
        m = re.match(r"П(\d+)\s*[–—-]\s*П(\d+)$", piece)
        if m:
            result += [f"П{i}" for i in range(int(m.group(1)), int(m.group(2)) + 1)]
        elif re.match(r"П\d+$", piece):
            result.append(piece)
    return result


def take_tags(text):
    tags = []
    for m in RE_TAGS.finditer(text):
        tags += expand_tags(m.group(1))
    return tags


def unique(items):
    seen, out = set(), []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


def split_front_matter(text):
    """Вернуть (шапка, тело, номер первой строки тела)."""
    text = text.replace("\r\n", "\n")
    if not text.startswith("---\n"):
        return {}, text, 1
    end = text.find("\n---", 4)
    if end == -1:
        return {}, text, 1
    head = text[4:end]
    rest_start = text.find("\n", end + 4)
    body = "" if rest_start == -1 else text[rest_start + 1:]
    meta = yaml.safe_load(head) or {}
    body_line = text[: len(text) - len(body)].count("\n") + 1
    return meta, body, body_line


BLOCK_LIST_KEYS = {"goals"}


def dump_front_matter(meta):
    """Шапка в блочном стиле; короткие списки — в строку: [П2, П6]."""
    out = ["---"]
    for key, value in meta.items():
        if isinstance(value, list) and key not in BLOCK_LIST_KEYS:
            text = yaml.safe_dump(value, allow_unicode=True, default_flow_style=True,
                                  width=1000).strip()
            out.append(f"{key}: {text}")
        else:
            text = yaml.safe_dump({key: value}, allow_unicode=True, sort_keys=False,
                                  default_flow_style=False, width=1000).rstrip("\n")
            out.append(text)
    out.append("---")
    return "\n".join(out) + "\n"


# ---------------------------------------------------------------- PLAN.md

def read_plan(root):
    path = root / "PLAN.md"
    if not path.exists():
        fail("Нет PLAN.md")
    text = path.read_text(encoding="utf-8")
    m = re.search(r"^```[^\n]*\n(.*?)^```", text, re.S | re.M)
    if not m:
        fail("В PLAN.md не найден блок кода с оглавлением")
    return parse_plan(m.group(1).splitlines())


def parse_plan(lines):
    """Разобрать оглавление. Возвращает (единицы по порядку, части)."""
    units, parts, warnings = [], [], []
    part = chapter = sub = index_entry = None
    mode = None

    def finish_sub():
        if sub:
            sub["thesis"] = " ".join(sub.pop("_thesis")).strip()
            sub["techniques"] = unique(sub["techniques"] + take_tags(sub["thesis"]))

    for raw in lines:
        line = raw.rstrip()
        if not line.strip():
            continue
        if RE_PART.match(line):
            finish_sub()
            sub = None
            m = RE_PART.match(line)
            part = {"id": m.group(1), "title": m.group(2).strip(),
                    "description": "", "chapters": []}
            parts.append(part)
            mode = "part"
            continue
        if line.startswith("УКАЗАТЕЛИ"):
            finish_sub()
            sub = chapter = None
            mode = "indices"
            continue
        if mode in ("indices", "index_entry") and RE_INDEX_ENTRY.match(line):
            m = RE_INDEX_ENTRY.match(line)
            letter = m.group(1)
            if letter not in INDEX_FOLDERS:
                warnings.append(f"Неизвестный указатель «{letter}» в PLAN.md — пропущен")
                mode = "indices"
                continue
            number, folder = INDEX_FOLDERS[letter]
            index_entry = {
                "kind": "chapter", "id": letter, "chapter": number, "sub": 0,
                "title": m.group(2).strip(), "thesis": "", "techniques": [],
                "folder_slug": folder, "_desc": [],
            }
            units.append(index_entry)
            mode = "index_entry"
            continue
        m = RE_CHAPTER.match(line)
        if m and mode != "indices":
            finish_sub()
            sub = None
            raw_title = m.group(2).strip()
            title = RE_TAGS.sub("", raw_title).strip()
            after_colon = title.split(": ", 1)[1] if ": " in title else title
            chapter = {
                "kind": "chapter", "id": m.group(1), "chapter": int(m.group(1)),
                "sub": 0, "title": title, "thesis": "",
                "techniques": take_tags(raw_title),
                "folder_slug": f"{int(m.group(1)):02d}-{slugify(after_colon, 4)}",
                "_desc": [],
            }
            units.append(chapter)
            if part:
                part["chapters"].append(chapter["id"])
            mode = "chapter"
            continue
        m = RE_SUB.match(line)
        if m and chapter is not None and mode in ("chapter", "sub"):
            finish_sub()
            if int(m.group(1)) != chapter["chapter"]:
                warnings.append(
                    f"Подглава {m.group(1)}.{m.group(2)} стоит внутри главы {chapter['id']}")
            raw_title = m.group(3).strip()
            refs = [r.strip() for r in RE_REF.findall(raw_title)]
            title = RE_REF.sub("", RE_TAGS.sub("", raw_title)).strip()
            sub = {
                "kind": "sub", "id": f"{m.group(1)}.{m.group(2)}",
                "chapter": int(m.group(1)), "sub": int(m.group(2)),
                "title": title, "techniques": take_tags(raw_title),
                "parent": chapter, "_thesis": [], "_refs": refs,
            }
            units.append(sub)
            mode = "sub"
            continue
        if raw[:1].isspace():
            text = line.strip()
            if mode == "sub":
                sub["_thesis"].append(text)
            elif mode == "chapter":
                chapter["_desc"].append(text)
            elif mode == "index_entry":
                index_entry["_desc"].append(text)
            elif mode == "part":
                part["description"] = (part["description"] + " " + text).strip()
            continue
        warnings.append(f"Непонятная строка в PLAN.md: {line!r}")
        mode = None

    finish_sub()
    for unit in units:
        if unit["kind"] == "chapter":
            unit["thesis"] = " ".join(unit.pop("_desc")).strip()
            unit["techniques"] = unique(unit["techniques"] + take_tags(unit["thesis"]))
        else:
            refs = unit.pop("_refs")
            if refs:
                unit["thesis"] = (unit["thesis"] + " " + " ".join(refs)).strip()
            unit["file_slug"] = f"{unit['sub']:02d}-{slugify(unit['title'], 3)}"
    for w in warnings:
        print("Предупреждение: " + w, file=sys.stderr)
    return units, parts


def order_key(unit):
    return (unit["chapter"], unit["sub"])


# ---------------------------------------------------------------- book/

def scan_book(root):
    """Все файлы книги: id → {path, meta, body, body_line}."""
    found = {}
    book = root / "book"
    if not book.exists():
        return found
    for path in sorted(book.glob("*/*.md")):
        try:
            meta, body, body_line = split_front_matter(path.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            print(f"Ошибка в шапке {rel(root, path)}: {exc}", file=sys.stderr)
            continue
        uid = meta.get("id")
        if uid is None:
            print(f"Предупреждение: у {rel(root, path)} нет id в шапке", file=sys.stderr)
            continue
        uid = str(uid)
        if uid in found:
            print(f"Предупреждение: id {uid} повторяется: {rel(root, found[uid]['path'])}"
                  f" и {rel(root, path)}", file=sys.stderr)
            continue
        found[uid] = {"path": path, "meta": meta, "body": body, "body_line": body_line}
    return found


def rel(root, path):
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def chapter_folder(root, unit, existing_folders):
    number = unit["chapter"]
    if number in existing_folders:
        return existing_folders[number]
    return root / "book" / unit["folder_slug"]


def existing_chapter_folders(root):
    folders = {}
    book = root / "book"
    if book.exists():
        for d in sorted(book.iterdir()):
            m = re.match(r"(\d+)-", d.name)
            if d.is_dir() and m:
                folders.setdefault(int(m.group(1)), d)
    return folders


def cmd_scaffold(root):
    units, parts = read_plan(root)
    existing = scan_book(root)
    folders = existing_chapter_folders(root)
    created = skipped = 0
    planned_ids = set()

    for unit in units:
        uid = unit["id"]
        planned_ids.add(uid)
        chapter = unit if unit["kind"] == "chapter" else unit["parent"]
        folder = chapter_folder(root, chapter, folders)
        folders.setdefault(chapter["chapter"], folder)
        if unit["kind"] == "chapter":
            path = folder / "index.md"
            meta = {"id": uid, "title": unit["title"]}
            if unit["thesis"]:
                meta["thesis"] = unit["thesis"]
            if unit["techniques"]:
                meta["techniques"] = unit["techniques"]
            meta["status"] = "план"
            if uid in INDEX_FOLDERS:
                heading = f"# {unit['title']}"
            else:
                heading = f"# {uid}. {unit['title']}"
            body = heading + "\n"
        else:
            path = folder / f"{unit['file_slug']}.md"
            meta = {
                "id": uid, "title": unit["title"], "thesis": unit["thesis"],
                "techniques": unit["techniques"], "status": "план", "round": 0,
                "introduces": [], "goals": [],
            }
            body = f"# {uid} {unit['title']}\n\n*{unit['thesis']}*\n" if unit["thesis"] \
                else f"# {uid} {unit['title']}\n"

        if uid in existing:
            old = existing[uid]["path"]
            if old != path:
                print(f"{uid}: файл уже есть под другим именем: {rel(root, old)}"
                      f" (по плану было бы {rel(root, path)}) — не трогаю")
            skipped += 1
            continue
        if path.exists():
            print(f"{uid}: {rel(root, path)} существует, но без этого id в шапке — не трогаю")
            skipped += 1
            continue
        folder.mkdir(parents=True, exist_ok=True)
        path.write_text(dump_front_matter(meta) + "\n" + body, encoding="utf-8")
        created += 1

    for uid, info in existing.items():
        if uid not in planned_ids:
            print(f"Предупреждение: {uid} нет в PLAN.md, а файл есть: "
                  f"{rel(root, info['path'])} — не удаляю")

    parts_path = root / "book" / "parts.yaml"
    parts_path.parent.mkdir(parents=True, exist_ok=True)
    parts_path.write_text(
        "# Части книги. Файл создаётся заново командой scaffold по PLAN.md.\n"
        + yaml.safe_dump(parts, allow_unicode=True, sort_keys=False, width=1000),
        encoding="utf-8")

    chapters = sum(1 for u in units if u["kind"] == "chapter" and u["id"].isdigit())
    subs = sum(1 for u in units if u["kind"] == "sub")
    print(f"По плану: {chapters} глав, {subs} подглав, "
          f"{len(units) - chapters - subs} указателя, {len(parts)} частей.")
    print(f"Создано файлов: {created}, уже было: {skipped}.")


# ---------------------------------------------------------------- status / next

def ordered_units(root):
    """Единицы книги по порядку: план + что реально лежит в book/."""
    units, _ = read_plan(root)
    existing = scan_book(root)
    rows = []
    for unit in sorted(units, key=order_key):
        info = existing.get(unit["id"])
        meta = info["meta"] if info else {}
        rows.append({
            "id": unit["id"], "kind": unit["kind"], "key": order_key(unit),
            "title": meta.get("title", unit["title"]),
            "status": meta.get("status", "нет файла") if info else "нет файла",
            "round": meta.get("round", ""), "info": info,
        })
    return rows


def cmd_status(root):
    rows = ordered_units(root)
    print(f"{'id':<6} {'статус':<14} {'круг':<5} заголовок")
    print("-" * 72)
    for row in rows:
        indent = "" if row["kind"] == "chapter" else "  "
        rnd = "" if row["kind"] == "chapter" else str(row["round"])
        print(f"{row['id']:<6} {row['status']:<14} {rnd:<5} {indent}{row['title']}")
    print("-" * 72)
    counts = {}
    for row in rows:
        counts[row["status"]] = counts.get(row["status"], 0) + 1
    order = STATUSES + sorted(set(counts) - set(STATUSES))
    print("  ".join(f"{s}: {counts[s]}" for s in order if s in counts)
          + f"  (всего {len(rows)})")


def cmd_next(root):
    for row in ordered_units(root):
        if row["status"] not in DONE_STATUSES:
            where = rel(root, row["info"]["path"]) if row["info"] else "файла нет — scaffold"
            print(f"{row['id']} {row['title']} (статус: {row['status']}) — {where}")
            return
    print("Всё принято или ждёт человека.")


# ---------------------------------------------------------------- check

def load_terms(root):
    path = root / "terms" / "terms.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else []
    return data or []


def load_allowlist(root):
    path = root / "terms" / "allowlist.txt"
    if not path.exists():
        return set()
    words = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            words.add(line)
    return words


def mask(text, start, end):
    return text[:start] + re.sub(r"[^\n]", " ", text[start:end]) + text[end:]


def clean_body(body):
    """Убрать блоки кода, инлайн-код, адреса ссылок и HTML-комментарии,
    сохранив номера строк."""
    lines = body.split("\n")
    fence = None
    for i, line in enumerate(lines):
        stripped = line.lstrip()
        if fence:
            if stripped.startswith(fence):
                fence = None
            lines[i] = ""
            continue
        m = re.match(r"(```+|~~~+)", stripped)
        if m:
            fence = m.group(1)
            lines[i] = ""
    text = "\n".join(lines)
    for pattern in (r"<!--.*?-->", r"`[^`\n]+`", r"\]\([^)\s]*\)", r"https?://\S+"):
        for m in reversed(list(re.finditer(pattern, text, re.S))):
            keep_bracket = pattern.startswith(r"\]")
            start = m.start() + (1 if keep_bracket else 0)
            text = mask(text, start, m.end())
    return text


def paragraphs(text):
    """Разбить текст на абзацы. Пункт списка, строка таблицы и заголовок —
    отдельные абзацы. Возвращает [(номер, первая строка, текст, заголовок?)]."""
    result, current, start = [], [], None

    def flush():
        nonlocal current, start
        if current:
            result.append([start, "\n".join(current), False])
        current, start = [], None

    for i, line in enumerate(text.split("\n")):
        body = re.sub(r"^\s*>\s?", "", line)
        if not body.strip():
            flush()
            continue
        if re.match(r"^#{1,6}\s", body):
            flush()
            result.append([i, body, True])
            continue
        if re.match(r"^\s*([-*+]|\d+[.)])\s", body) or re.match(r"^\s*\|", body):
            flush()
        if start is None:
            start = i
        current.append(body)
    flush()
    return [(n + 1, s, t, h) for n, (s, t, h) in enumerate(result)]


class Term:
    def __init__(self, entry):
        self.name = str(entry["term"])
        self.kind = entry.get("kind", "term")
        self.introduced_in = str(entry.get("introduced_in", ""))
        self.defined_via = [str(x) for x in (entry.get("defined_via") or [])]
        forms = [self.name] + [str(f) for f in (entry.get("forms") or [])]
        forms = sorted(unique(forms), key=len, reverse=True)
        flags = 0 if self.kind == "abbr" else re.IGNORECASE
        alt = "|".join(re.escape(f) for f in forms)
        self.forms = set(forms)
        self.regex = re.compile(rf"(?<!\w)(?:{alt})(?!\w)", flags)


# Суффикс, который может идти между аббревиатурой и скобкой:
# «HTTP/3 (», «TLS 1.3 (», «TCP-соединение (».
ABBR_TAIL = re.compile(r"(?:[-/][\w.]+|[  ]\d+(?:\.\d+)*)?[  ]?\(")

RE_LATIN_ABBR = re.compile(r"(?<!\w)(?:[A-Z]{2,}v\d+|[A-Z][A-Z0-9]+(?:[-/][A-Z0-9]+)*)(?!\w)")
RE_CYR_ABBR = re.compile(r"(?<!\w)[А-ЯЁ][А-ЯЁ0-9]{1,3}(?!\w)")
RE_ROMAN = re.compile(r"^[IVXLCDM]+$")
RE_TECHNIQUE = re.compile(r"^П\d+$")


def expansion_spans(text, abbr_terms):
    """Области «(…)» сразу после аббревиатуры — внутри них упоминания
    других аббревиатур не считаются первыми в абзаце."""
    spans = []
    for term in abbr_terms:
        for m in term.regex.finditer(text):
            tail = ABBR_TAIL.match(text, m.end())
            if not tail:
                continue
            depth, j = 1, tail.end()
            while j < len(text) and depth:
                depth += {"(": 1, ")": -1}.get(text[j], 0)
                j += 1
            spans.append((tail.end(), j))
    return spans


def inside(pos, spans):
    return any(a <= pos < b for a, b in spans)


def cmd_check(root, only_id=None):
    units, _ = read_plan(root)
    files = scan_book(root)
    positions = {u["id"]: order_key(u) for u in units}
    for uid, info in files.items():  # файлы вне плана тоже получают место
        if uid not in positions:
            m = re.match(r"^(\d+)(?:\.(\d+))?$", uid)
            if m:
                positions[uid] = (int(m.group(1)), int(m.group(2) or 0))

    try:
        raw_terms = load_terms(root)
    except yaml.YAMLError as exc:
        fail(f"Ошибка в terms/terms.yaml: {exc}")
    allow = load_allowlist(root)
    errors, warnings = [], []

    terms, seen = [], set()
    for entry in raw_terms:
        if not isinstance(entry, dict) or "term" not in entry:
            errors.append(f"terms.yaml: запись без поля term: {entry!r}")
            continue
        term = Term(entry)
        if term.name in seen:
            errors.append(f"terms.yaml: термин «{term.name}» записан дважды")
            continue
        seen.add(term.name)
        terms.append(term)
    by_name = {t.name: t for t in terms}
    abbr_terms = [t for t in terms if t.kind == "abbr"]
    known_tokens = set()
    for t in terms:
        known_tokens |= t.forms

    if only_id is not None and only_id not in files:
        fail(f"Нет файла с id {only_id}. Сначала: python3 tools/book.py scaffold")

    # --- реестр: правила 4 и 5
    for term in terms:
        if only_id is not None and term.introduced_in != only_id:
            continue
        pos = positions.get(term.introduced_in)
        if pos is None:
            errors.append(f"terms.yaml: «{term.name}»: introduced_in «{term.introduced_in}»"
                          f" — такой главы или подглавы нет")
            continue
        for dep in term.defined_via:
            if dep not in by_name:
                errors.append(f"terms.yaml: «{term.name}»: в defined_via «{dep}»,"
                              f" которого нет в реестре [5]")
                continue
            dep_pos = positions.get(by_name[dep].introduced_in)
            if dep_pos is not None and dep_pos > pos:
                errors.append(f"terms.yaml: «{term.name}» (введён в {term.introduced_in})"
                              f" объяснён через «{dep}», который введён позже,"
                              f" в {by_name[dep].introduced_in} [4]")

    # --- тексты
    targets = sorted(files.items(), key=lambda kv: positions.get(kv[0], (999, 0)))
    checked = 0
    for uid, info in targets:
        if only_id is not None and uid != only_id:
            continue
        status = str(info["meta"].get("status", "план"))
        if status == "план":
            if only_id is not None:
                print(f"{uid}: статус «план» — проверять нечего.")
            continue
        checked += 1
        name = rel(root, info["path"])
        here = positions.get(uid, (999, 0))
        offset = info["body_line"] - 1
        text = clean_body(info["body"])

        def line_of(pos):
            return text.count("\n", 0, pos) + 1 + offset

        # правило 3
        for t in info["meta"].get("introduces") or []:
            t = str(t)
            if t not in by_name:
                errors.append(f"{name}: «{t}» в introduces, но нет в terms.yaml [3]")
            elif by_name[t].introduced_in != uid:
                errors.append(f"{name}: «{t}» в introduces, а в terms.yaml введён"
                              f" в {by_name[t].introduced_in} [3]")

        # правило 1
        for term in terms:
            intro = positions.get(term.introduced_in)
            if intro is None or here >= intro:
                continue
            for m in term.regex.finditer(text):
                errors.append(f"{name}:{line_of(m.start())}: «{m.group(0)}» использован"
                              f" раньше введения (введён в {term.introduced_in}) [1]")
                break

        # правило 2 и предупреждение 6
        for number, start_line, para, is_heading in paragraphs(text):
            spans = expansion_spans(para, abbr_terms)
            if not is_heading:
                for term in abbr_terms:
                    for m in term.regex.finditer(para):
                        if inside(m.start(), spans):
                            continue
                        if not ABBR_TAIL.match(para, m.end()):
                            line = start_line + 1 + offset + para.count("\n", 0, m.start())
                            errors.append(f"{name}:{line}: абзац {number}: «{m.group(0)}»"
                                          f" без расшифровки при первом упоминании в абзаце [2]")
                        break
            for regex in (RE_LATIN_ABBR, RE_CYR_ABBR):
                for m in regex.finditer(para):
                    token = m.group(0)
                    if token_known(token, known_tokens, allow):
                        continue
                    line = start_line + 1 + offset + para.count("\n", 0, m.start())
                    warnings.append(f"{name}:{line}: неизвестная аббревиатура «{token}»"
                                    f" — добавьте в terms.yaml или terms/allowlist.txt [6]")

    for e in unique(errors):
        print("ОШИБКА: " + e)
    for w in unique(warnings):
        print("предупреждение: " + w)
    print(f"Проверено файлов: {checked}. Ошибок: {len(unique(errors))},"
          f" предупреждений: {len(unique(warnings))}.")
    return 1 if errors else 0


def token_known(token, known, allow):
    if token in known or token in allow:
        return True
    if RE_ROMAN.match(token) or RE_TECHNIQUE.match(token):
        return True
    pieces = re.split(r"[-/]", token)
    if len(pieces) > 1:
        return all(p.isdigit() or p in known or p in allow or RE_ROMAN.match(p)
                   for p in pieces if p)
    return False


# ---------------------------------------------------------------- main

def main(argv=None):
    parser = argparse.ArgumentParser(description="Инструменты книги «Сети с нуля»")
    parser.add_argument("--root", type=Path, default=ROOT,
                        help="корень репозитория (по умолчанию — над tools/)")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("scaffold", help="создать файлы по PLAN.md")
    sub.add_parser("status", help="статусы глав и подглав")
    sub.add_parser("next", help="следующая подглава для работы")
    p_check = sub.add_parser("check", help="проверка терминов")
    p_check.add_argument("id", nargs="?", help="id подглавы, например 11.4")
    args = parser.parse_args(argv)
    root = args.root.resolve()

    if args.cmd == "scaffold":
        cmd_scaffold(root)
    elif args.cmd == "status":
        cmd_status(root)
    elif args.cmd == "next":
        cmd_next(root)
    elif args.cmd == "check":
        return cmd_check(root, args.id)
    return 0


if __name__ == "__main__":
    sys.exit(main())
