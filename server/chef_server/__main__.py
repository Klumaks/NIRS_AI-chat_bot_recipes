"""Команды сервера.

    python -m chef_server                       # запустить API (и собранный фронтенд) на 127.0.0.1:8000
    python -m chef_server --host 0.0.0.0 --port 8000 --reload
    python -m chef_server create-admin --email admin@example.com   # первый admin, пароль вводится скрыто
    python -m chef_server init-db               # создать/обновить схему БД
    python -m chef_server rag-status            # изменения каталога администратором по версиям корпуса
    python -m chef_server rag-export --base-key "<ключ>" --out admin.jsonl   # перенос после пересборки
    python -m chef_server rag-drop --base-key "<ключ>"                         # убрать перенесённые изменения
"""
from __future__ import annotations

import argparse
import getpass
import logging
import sys

from .config import Settings
from .db import connect, init_db
from .errors import ApiError
from .routes_auth import create_account
from .security import check_password_policy, normalize_email


def _create_admin(settings: Settings, email: str, password_stdin: bool) -> int:
    init_db(settings.db_path)
    try:
        email = normalize_email(email)
        if password_stdin:
            password = sys.stdin.readline().rstrip("\n")
        else:
            password = getpass.getpass("Пароль администратора: ")
            if getpass.getpass("Повторите пароль: ") != password:
                print("Пароли не совпадают", file=sys.stderr)
                return 1
        check_password_policy(password)
        conn = connect(settings.db_path)
        try:
            user = create_account(conn, email, password, "admin")
        finally:
            conn.close()
    except ApiError as exc:
        print(f"Ошибка: {exc.message}", file=sys.stderr)
        return 1
    print(f"Создан администратор {user['email']} (user_id {user['user_id']})")
    return 0


def _rag_status(settings: Settings) -> int:
    init_db(settings.db_path)
    conn = connect(settings.db_path)
    try:
        rows = conn.execute("SELECT c.base_key, COUNT(*) AS changes, MAX(c.revision) AS revision, "
                            "COUNT(DISTINCT c.recipe_id) AS recipes FROM rag_changes c GROUP BY c.base_key").fetchall()
    finally:
        conn.close()
    if not rows:
        print("Изменений каталога нет")
    for r in rows:
        print(f"{r['base_key']}\tревизия {r['revision']}\tизменений {r['changes']}\tзаписей {r['recipes']}")
    return 0


def _rag_export(settings: Settings, base_key: str, out: str) -> int:
    """Живые записи администратора (последняя версия, без удалённых) в формате импорта JSONL."""
    import json
    conn = connect(settings.db_path)
    try:
        rows = conn.execute("SELECT recipe_id, op, record_json FROM rag_changes WHERE base_key = ? "
                            "ORDER BY recipe_id, revision", (base_key,)).fetchall()
    finally:
        conn.close()
    latest: dict[int, tuple[str, str | None]] = {}
    for r in rows:
        latest[r["recipe_id"]] = (r["op"], r["record_json"])
    keys = ("title", "ingredients", "url", "description", "steps", "nutrition_per_100g", "total_time_minutes")
    n = 0
    with open(out, "w", encoding="utf-8") as f:
        for _rid, (op, raw) in sorted(latest.items()):
            if op != "upsert" or not raw:
                continue
            rec = json.loads(raw)
            f.write(json.dumps({k: rec.get(k) for k in keys}, ensure_ascii=False) + "\n")
            n += 1
    print(f"Выгружено записей: {n} -> {out}. Изменения записей корпуса выгружены как полные рецепты.")
    return 0


def _rag_drop(settings: Settings, base_key: str) -> int:
    conn = connect(settings.db_path)
    try:
        n = conn.execute("DELETE FROM rag_changes WHERE base_key = ?", (base_key,)).rowcount
        conn.execute("DELETE FROM rag_state WHERE base_key = ?", (base_key,))
    finally:
        conn.close()
    print(f"Удалено изменений: {n}. Снимки старых чатов в БД не затронуты.")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m chef_server", description="Сервер «ИИ-шефа»")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--reload", action="store_true", help="перезапуск при изменении кода (разработка)")
    sub = ap.add_subparsers(dest="cmd")
    a = sub.add_parser("create-admin", help="создать администратора (процедура развёртывания)")
    a.add_argument("--email", required=True)
    a.add_argument("--password-stdin", action="store_true", help="прочитать пароль из stdin (для скриптов)")
    sub.add_parser("init-db", help="создать схему БД")
    sub.add_parser("rag-status", help="изменения каталога по версиям корпуса")
    e = sub.add_parser("rag-export", help="выгрузить записи администратора в JSONL")
    e.add_argument("--base-key", required=True)
    e.add_argument("--out", required=True)
    d = sub.add_parser("rag-drop", help="удалить изменения каталога для версии корпуса")
    d.add_argument("--base-key", required=True)
    args = ap.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    settings = Settings.from_env()
    if args.cmd == "create-admin":
        return _create_admin(settings, args.email, args.password_stdin)
    if args.cmd == "rag-status":
        return _rag_status(settings)
    if args.cmd == "rag-export":
        return _rag_export(settings, args.base_key, args.out)
    if args.cmd == "rag-drop":
        return _rag_drop(settings, args.base_key)
    if args.cmd == "init-db":
        init_db(settings.db_path)
        print(f"БД готова: {settings.db_path}")
        return 0

    import uvicorn
    uvicorn.run("chef_server.app:create_app", factory=True, host=args.host, port=args.port,
                reload=args.reload, proxy_headers=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
