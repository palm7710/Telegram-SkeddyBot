#!/usr/bin/env python3

from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from io import StringIO
from zoneinfo import ZoneInfo

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import CallbackQueryHandler
import html

JST = ZoneInfo("Asia/Tokyo")
DB_PATH = os.getenv("DB_PATH", "./skeddy.db")


def esc(s: str) -> str:
    return html.escape(s, quote=False)


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with get_conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                text TEXT NOT NULL,
                ts_utc TEXT NOT NULL
            )
            """
        )
        conn.commit()


@dataclass
class Entry:
    id: int
    user_id: int
    text: str
    ts_utc: datetime


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def to_jst(dt_utc: datetime) -> datetime:
    return dt_utc.astimezone(JST)


def jst_day_bounds(dt: datetime) -> tuple[datetime, datetime]:
    start = datetime(dt.year, dt.month, dt.day, tzinfo=JST)
    end = start + timedelta(days=1)
    return start, end


def insert_entry(user_id: int, text: str) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO entries(user_id, text, ts_utc) VALUES (?, ?, ?)",
            (user_id, text.strip(), now_utc().isoformat()),
        )
        conn.commit()
        return cur.lastrowid


def fetch_entries_between(
    user_id: int, start_jst: datetime, end_jst: datetime
) -> list[Entry]:
    start_utc = start_jst.astimezone(timezone.utc)
    end_utc = end_jst.astimezone(timezone.utc)
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT id, user_id, text, ts_utc
            FROM entries
            WHERE user_id = ? AND ts_utc >= ? AND ts_utc < ?
            ORDER BY ts_utc ASC
            """,
            (user_id, start_utc.isoformat(), end_utc.isoformat()),
        ).fetchall()
    return [
        Entry(r["id"], r["user_id"], r["text"], datetime.fromisoformat(r["ts_utc"]))
        for r in rows
    ]


def fetch_last_entry_today(user_id: int) -> Entry | None:
    today_jst = datetime.now(JST)
    start, end = jst_day_bounds(today_jst)
    start_utc = start.astimezone(timezone.utc)
    end_utc = end.astimezone(timezone.utc)
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT id, user_id, text, ts_utc
            FROM entries
            WHERE user_id = ? AND ts_utc >= ? AND ts_utc < ?
            ORDER BY ts_utc DESC
            LIMIT 1
            """,
            (user_id, start_utc.isoformat(), end_utc.isoformat()),
        ).fetchone()
    if not row:
        return None
    return Entry(
        row["id"], row["user_id"], row["text"], datetime.fromisoformat(row["ts_utc"])
    )


def delete_entry(entry_id: int) -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM entries WHERE id = ?", (entry_id,))
        conn.commit()


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (
        "こんにちは😄\n今日の1日を記録しましょう!\n\n"
        "使い方:\n"
        "• /log <今やったこと> - 記録\n"
        "• /today - 今日の記録を表示\n"
        "• /week - 直近7日の記録を表示\n"
        "• /undo - 今日の最新1件を取り消し\n"
        "• /export - CSVでエクスポート\n"
    )
    await update.effective_message.reply_text(text, reply_markup=build_main_menu())


async def cmd_log(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = context.args
    if not args:
        await update.effective_message.reply_text("使い方: /log <今やったこと>")
        return
    content = " ".join(args).strip()
    insert_entry(update.effective_user.id, content)
    local_time = to_jst(now_utc()).strftime("%H:%M")
    preview = (content[:30] + "…") if len(content) > 30 else content
    await update.effective_message.reply_text(
        f"📝 追加しました ({local_time})\nプレビュー: {esc(preview)}",
        parse_mode=ParseMode.HTML,
    )


async def cmd_today(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    now = datetime.now(JST)
    start, end = jst_day_bounds(now)
    entries = fetch_entries_between(update.effective_user.id, start, end)
    if not entries:
        await update.effective_message.reply_text(
            "今日はまだ記録がありません。/log と入力してみよう！"
        )
        return
    lines = ["📒 <b>今日の記録</b>"]
    for e in entries:
        # 長文でも改行が維持される
        t = to_jst(e.ts_utc).strftime("%H:%M")
        body = esc(e.text).replace("</pre>", "&lt;/pre&gt;") + "\u200B"
        lines.append(f"{t}\n<pre>{body}</pre>")
    await update.effective_message.reply_text(
        "\n".join(lines), parse_mode=ParseMode.HTML
    )


async def cmd_week(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    now = datetime.now(JST)
    start = datetime(now.year, now.month, now.day, tzinfo=JST) - timedelta(days=6)
    end = datetime(now.year, now.month, now.day, tzinfo=JST) + timedelta(days=1)
    entries = fetch_entries_between(update.effective_user.id, start, end)
    if not entries:
        await update.effective_message.reply_text(
            "直近7日の記録がありません。今日から始めましょう！"
        )
        return

    by_date: dict[str, list[Entry]] = {}
    for e in entries:
        day_label = to_jst(e.ts_utc).strftime("%Y-%m-%d (%a)")
        by_date.setdefault(day_label, []).append(e)

    chunks = ["🗓 <b>直近7日</b>"]
    for day in sorted(by_date.keys()):
        chunks.append(f"\n<b>{day}</b>\n──────────")
        for e in by_date[day]:
            t = to_jst(e.ts_utc).strftime("%H:%M")
            body = esc(e.text).replace("</pre>", "&lt;/pre&gt;") + "\u200B"
            chunks.append(f"{t}\n<pre>{body}</pre>")


    await update.effective_message.reply_text(
        "\n".join(chunks), parse_mode=ParseMode.HTML
    )


async def cmd_undo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    last = fetch_last_entry_today(update.effective_user.id)
    if not last:
        await update.effective_message.reply_text(
            "取り消す対象が見つかりません（今日は未記録です）"
        )
        return
    delete_entry(last.id)
    await update.effective_message.reply_text(
        f"↩️ 直近の1件を削除しました\n- {last.text}"
    )


async def cmd_export(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, user_id, text, ts_utc FROM entries WHERE user_id = ? ORDER BY ts_utc ASC",
            (update.effective_user.id,),
        ).fetchall()
    if not rows:
        await update.effective_message.reply_text("まだデータがありません。")
        return

    sio = StringIO()
    sio.write("id,user_id,ts_jst,text\n")
    for r in rows:
        ts_utc = datetime.fromisoformat(r["ts_utc"])
        ts_jst = to_jst(ts_utc).strftime("%Y-%m-%d %H:%M:%S")
        text = str(r["text"]).replace('"', '""')
        sio.write(f"{r['id']},{r['user_id']},\"{ts_jst}\",\"{text}\"\n")

    sio.seek(0)
    await update.effective_message.reply_document(
        document=sio, filename="skeddy_export.csv"
    )


async def on_plain_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    content = update.effective_message.text.strip()
    if not content:
        return
    insert_entry(update.effective_user.id, content)
    local_time = to_jst(now_utc()).strftime("%H:%M")
    await update.effective_message.reply_text(
        f"📝 記録しました（{local_time}）\n- {content}"
    )


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    print(f"[ERROR] {context.error}")


def build_main_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("🗒 今日", callback_data="SHOW_TODAY"),
                InlineKeyboardButton("🗓 7日", callback_data="SHOW_WEEK"),
            ],
            [
                InlineKeyboardButton("↩️ 取り消し", callback_data="UNDO"),
                InlineKeyboardButton("⬇️ CSV", callback_data="EXPORT"),
            ],
        ]
    )


async def on_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()
    data = (q.data or "").upper()
    if data == "SHOW_TODAY":
        await cmd_today(update, context)
    elif data == "SHOW_WEEK":
        await cmd_week(update, context)
    elif data == "UNDO":
        await cmd_undo(update, context)
    elif data == "EXPORT":
        await cmd_export(update, context)


def main() -> None:
    init_db()
    token = os.environ.get("TELEGRAM_TOKEN")
    if not token:
        raise RuntimeError("環境変数TELEGRAM_TOKEN を設定してください")

    app = Application.builder().token(token).concurrent_updates(True).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("log", cmd_log))
    app.add_handler(CommandHandler("today", cmd_today))
    app.add_handler(CommandHandler("week", cmd_week))
    app.add_handler(CommandHandler("undo", cmd_undo))
    app.add_handler(CommandHandler("export", cmd_export))
    app.add_handler(CallbackQueryHandler(on_cb))

    # コマンドなしの場合も記録（現在、コメントアウトで無効)
    # app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), on_plain_text))

    app.add_handler(CallbackQueryHandler(on_cb))

    app.add_error_handler(on_error)

    print("Skeddybot is running (polling)… Press Ctrl+C to stop.")
    app.run_polling(close_loop=False, allowed_updates=["message", "edited_message", "callback_query"])  # type: ignore


if __name__ == "__main__":
    main()
