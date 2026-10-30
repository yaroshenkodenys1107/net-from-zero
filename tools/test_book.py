#!/usr/bin/env python3
"""Самопроверка tools/book.py на временной копии с намеренными ошибками.

Запуск: python3 tools/test_book.py
"""

import contextlib
import io
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
import book  # noqa: E402

TERMS = """
- term: UDP
  kind: abbr
  expansion: "User Datagram Protocol — протокол пользовательских датаграмм"
  introduced_in: "10"
  defined_via: []
  definition: "x"
- term: TCP
  kind: abbr
  expansion: "Transmission Control Protocol — протокол управления передачей"
  introduced_in: "11"
  defined_via: [порт]
  definition: "x"
- term: HTTP
  kind: abbr
  expansion: "HyperText Transfer Protocol — протокол передачи гипертекста"
  introduced_in: "10.1"
  definition: "x"
- term: порт
  kind: term
  introduced_in: "10.1"
  definition: "x"
  forms: [порта, порту, портом, порты, портов]
- term: соединение
  kind: term
  introduced_in: "11.2"
  defined_via: [порт]
  definition: "x"
  forms: [соединения, соединений]
- term: сокет
  kind: term
  introduced_in: "10.2"
  defined_via: [порт, соединение, нечто]
  definition: "x"
  forms: [сокета, сокеты]
"""

SUB_10_1 = """---
id: '10.1'
title: Порт
status: черновик
round: 0
introduces: [порт, HTTP]
goals: []
---

# 10.1 Порт и UDP в заголовке не проверяется

Программа отправляет данные через UDP без расшифровки.

UDP (User Datagram Protocol — протокол пользовательских датаграмм) верно,
и QUIC (Quick UDP Internet Connections — …) внутри скобок не считается.
HTTP/3 (HyperText Transfer Protocol version 3 — …) — суффикс версии допустим.

Порт отличается от TCP, который введён позже.

- Пункт: UDP без скобок в отдельном абзаце.

Код не проверяется: `TCP`.

```
TCP UDP
```

ЧАСТЬ IV, [П5], ОС и [RFC](https://www.rfc-editor.org/rfc/rfc768).
"""

SUB_10_2 = """---
id: '10.2'
title: Сокет
status: черновик
round: 1
introduces: [сокет, соединение]
goals: []
---

# 10.2 Сокет

Сокет хранит номер порта.
"""


class BookToolTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        shutil.copy(ROOT / "PLAN.md", self.tmp / "PLAN.md")
        (self.tmp / "terms").mkdir()
        (self.tmp / "terms" / "allowlist.txt").write_text("", encoding="utf-8")
        self.run_cmd("scaffold")

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def run_cmd(self, *args):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            code = book.main(["--root", str(self.tmp), *args])
        return code, out.getvalue()

    def test_scaffold_structure(self):
        units, parts = book.read_plan(self.tmp)
        chapters = [u for u in units if u["kind"] == "chapter" and u["id"].isdigit()]
        self.assertEqual(len(chapters), 44)
        self.assertEqual([c["id"] for c in chapters], [str(i) for i in range(44)])
        self.assertEqual(len(parts), 14)
        folders = sorted(p.name for p in (self.tmp / "book").iterdir() if p.is_dir())
        self.assertEqual(len(folders), 47)  # 44 главы + 3 указателя
        self.assertIn("11-tcp", folders)
        self.assertIn("16-dns", folders)
        self.assertIn("39-polnyy-razbor", folders)
        tcp = self.tmp / "book" / "11-tcp"
        self.assertTrue((tcp / "01-chto-proishodit-s-paketami.md").exists())
        meta, _, _ = book.split_front_matter((tcp / "04-rukopozhatie.md").read_text())
        self.assertEqual(meta["id"], "11.4")
        self.assertEqual(meta["techniques"], ["П2", "П6"])
        self.assertEqual(meta["status"], "план")
        quic = next((self.tmp / "book" / "26-quic").glob("02-*.md"))
        meta, _, _ = book.split_front_matter(quic.read_text())
        self.assertEqual(meta["techniques"], ["П3", "П4", "П5"])
        code, out = self.run_cmd("scaffold")
        self.assertIn("Создано файлов: 0", out)

    def test_check_finds_planted_errors(self):
        (self.tmp / "terms" / "terms.yaml").write_text(TERMS, encoding="utf-8")
        folder = self.tmp / "book" / "10-porty-i-udp"
        (folder / "01-port.md").write_text(SUB_10_1, encoding="utf-8")
        next(folder.glob("02-*.md")).write_text(SUB_10_2, encoding="utf-8")
        code, out = self.run_cmd("check")
        self.assertEqual(code, 1)
        # правило 1
        self.assertIn("«TCP» использован раньше введения", out)
        self.assertEqual(out.count("использован раньше введения"), 1)  # код и `TCP` не в счёт
        # правило 2: два абзаца с голым UDP, остальное верно
        self.assertEqual(out.count("«UDP» без расшифровки"), 2)
        self.assertNotIn("«HTTP» без расшифровки", out)
        # правило 3
        self.assertIn("«соединение» в introduces, а в terms.yaml введён в 11.2", out)
        # правило 4 и 5
        self.assertIn("«сокет» (введён в 10.2) объяснён через «соединение»", out)
        self.assertIn("«нечто», которого нет в реестре", out)
        # предупреждение 6
        self.assertIn("неизвестная аббревиатура «QUIC»", out)
        self.assertIn("неизвестная аббревиатура «ОС»", out)
        self.assertIn("«RFC»", out)          # текст ссылки проверяется
        self.assertNotIn("rfc768", out)      # адрес ссылки — нет
        self.assertNotIn("«IV»", out)
        self.assertNotIn("«ЧАСТЬ»", out)
        self.assertNotIn("«П5»", out)

    def test_status_and_next(self):
        code, out = self.run_cmd("next")
        self.assertTrue(out.startswith("0 Как читать эту книгу"))
        code, out = self.run_cmd("status")
        self.assertIn("план: 255", out)


if __name__ == "__main__":
    unittest.main()
