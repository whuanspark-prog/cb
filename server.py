import json
import os
import re
import shutil
import sqlite3
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from test_vlm import call_vlm_to_extract


BASE_DIR = Path(__file__).resolve().parent
WEB_DIR = BASE_DIR / "web"
DB_PATH = BASE_DIR / "clip_bill.db"
LEDGER_JSON = BASE_DIR / "stage4_final_ledger.json"
RULES_JSON = BASE_DIR / "user_rules.json"

EXPENSE_CATEGORIES = [
    "餐饮", "服饰", "日用", "数码", "美妆", "住房", "交通", "娱乐",
    "医疗", "通讯", "学习", "办公", "运动", "人情", "育儿", "宠物",
    "旅行", "追星", "其他",
]
INCOME_CATEGORIES = [
    "工资", "奖金", "加班", "福利", "公积金", "红包", "兼职", "副业",
    "退款", "投资", "意外收入", "其他",
]
ALL_CATEGORIES = EXPENSE_CATEGORIES + INCOME_CATEGORIES + ["【待人工确认】"]

app = FastAPI(title="Clip Bill Agent API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.mount("/assets", StaticFiles(directory=WEB_DIR), name="assets")


class ChatMessage(BaseModel):
    message: str


class CategoryUpdate(BaseModel):
    category: str


def connect_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def read_json(path: Path, default):
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def write_json(path: Path, data):
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def init_db():
    with connect_db() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                time TEXT NOT NULL,
                merchant TEXT NOT NULL,
                type TEXT NOT NULL,
                amount REAL NOT NULL,
                category TEXT NOT NULL,
                source TEXT DEFAULT 'import',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS user_rules (
                merchant TEXT PRIMARY KEY,
                category TEXT NOT NULL,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        count = conn.execute("SELECT COUNT(*) AS n FROM transactions").fetchone()["n"]
        if count == 0 and LEDGER_JSON.exists():
            for item in read_json(LEDGER_JSON, []):
                normalized = normalize_transaction(item)
                if normalized:
                    insert_transaction(conn, normalized, source="legacy")

        for merchant, category in read_json(RULES_JSON, {}).items():
            conn.execute(
                """
                INSERT INTO user_rules (merchant, category, updated_at)
                VALUES (?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(merchant) DO UPDATE SET
                    category = excluded.category,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (str(merchant), str(category)),
            )
        conn.commit()


def normalize_time(value: Any):
    text = str(value or "").strip()
    if not text or text.upper() == "UNKNOWN":
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(text, fmt).strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            pass
    try:
        return datetime.fromisoformat(text).strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


def normalize_type(value: Any):
    text = str(value or "").strip()
    if text in {"收入", "支出"}:
        return text
    if "收" in text or "+" in text:
        return "收入"
    return "支出"


def normalize_category(value: Any, tx_type: str):
    text = str(value or "").strip()
    if text in ALL_CATEGORIES:
        return text
    return "其他" if tx_type in {"收入", "支出"} else "【待人工确认】"


def categories_for_type(tx_type: str):
    if tx_type == "收入":
        return INCOME_CATEGORIES + ["【待人工确认】"]
    return EXPENSE_CATEGORIES + ["【待人工确认】"]


def normalize_transaction(item: dict[str, Any]):
    tx_time = normalize_time(item.get("time"))
    merchant = str(item.get("merchant") or "").replace("\n", " ").strip()
    if not tx_time or not merchant:
        return None
    try:
        amount = round(abs(float(item.get("amount"))), 2)
    except (TypeError, ValueError):
        return None
    tx_type = normalize_type(item.get("type"))
    category = normalize_category(item.get("category"), tx_type)
    return {
        "time": tx_time,
        "merchant": merchant,
        "type": tx_type,
        "amount": amount,
        "category": category,
    }


def fingerprint(tx):
    return tx["time"], tx["type"], f"{float(tx['amount']):.2f}"


def exists_transaction(conn, tx):
    return conn.execute(
        """
        SELECT id FROM transactions
        WHERE time = ? AND type = ? AND printf('%.2f', amount) = ?
        LIMIT 1
        """,
        fingerprint(tx),
    ).fetchone()


def insert_transaction(conn, tx, source="agent"):
    cursor = conn.execute(
        """
        INSERT INTO transactions (time, merchant, type, amount, category, source)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (tx["time"], tx["merchant"], tx["type"], tx["amount"], tx["category"], source),
    )
    return cursor.lastrowid


def fetch_rules(conn):
    rows = conn.execute("SELECT merchant, category FROM user_rules").fetchall()
    return {row["merchant"]: row["category"] for row in rows}


def classify_transaction(conn, tx):
    rules = fetch_rules(conn)
    merchant = tx["merchant"].strip()
    if merchant in rules:
        return rules[merchant]

    lowered = merchant.lower()
    if tx["type"] == "支出":
        if any(word in lowered for word in ["麦当劳", "肯德基", "便利店", "超市", "外卖", "饿了么", "美团", "咖啡", "手抓饼"]):
            return "餐饮"
        if any(word in lowered for word in ["打车", "地铁", "公交", "12306", "火车票", "高德"]):
            return "交通"
        if any(word in lowered for word in ["话费", "流量", "通信"]):
            return "通讯"
        if any(word in lowered for word in ["医院", "药", "颗粒", "诊所"]):
            return "医疗"
        if any(word in lowered for word in ["酒店", "机票", "旅行"]):
            return "旅行"
    if tx["type"] == "收入":
        if any(word in lowered for word in ["红包", "转账", "来自"]):
            return "红包"
        if any(word in lowered for word in ["收益", "利息", "基金", "余额宝"]):
            return "投资"
        if "退款" in lowered:
            return "退款"
    return "【待人工确认】"


def sync_json_files():
    with connect_db() as conn:
        rows = conn.execute(
            """
            SELECT time, merchant, type, amount, category
            FROM transactions
            ORDER BY time DESC, id DESC
            """
        ).fetchall()
        ledger = []
        for row in rows:
            month = row["time"][:7] if row["time"] else ""
            ledger.append({**dict(row), "month_str": month})
        rules = fetch_rules(conn)
    write_json(LEDGER_JSON, ledger)
    write_json(RULES_JSON, rules)


def dashboard_payload(highlight_ids=None):
    highlight_ids = set(highlight_ids or [])
    with connect_db() as conn:
        rows = conn.execute(
            """
            SELECT id, time, merchant, type, amount, category
            FROM transactions
            ORDER BY time DESC, id DESC
            """
        ).fetchall()

    transactions = []
    for row in rows:
        item = dict(row)
        item["highlight"] = item["id"] in highlight_ids
        transactions.append(item)

    now_month = datetime.now().strftime("%Y-%m")
    current_month = [t for t in transactions if str(t["time"]).startswith(now_month)]
    base = current_month or transactions

    income = sum(t["amount"] for t in base if t["type"] == "收入")
    expense = sum(t["amount"] for t in base if t["type"] == "支出")
    pending = sum(1 for t in transactions if t["category"] == "【待人工确认】")

    by_category = {}
    by_month = {}
    for tx in transactions:
        if tx["type"] == "支出":
            by_category[tx["category"]] = by_category.get(tx["category"], 0) + tx["amount"]
        month = tx["time"][:7]
        by_month.setdefault(month, {"month": month, "收入": 0, "支出": 0})
        by_month[month][tx["type"]] += tx["amount"]

    return {
        "summary": {
            "income": round(income, 2),
            "expense": round(expense, 2),
            "balance": round(income - expense, 2),
            "pending": pending,
            "scope": "本月" if current_month else "全部",
        },
        "categories": [
            {"category": key, "amount": round(value, 2)}
            for key, value in sorted(by_category.items(), key=lambda kv: kv[1], reverse=True)
        ],
        "monthly": list(sorted(by_month.values(), key=lambda item: item["month"])),
        "transactions": transactions[:120],
    }


def parse_correction(message: str):
    category_pattern = "|".join(re.escape(c) for c in ALL_CATEGORIES if c != "【待人工确认】")
    category_match = re.search(category_pattern, message)
    if not category_match:
        return None
    category = category_match.group(0)

    target = message[: category_match.start()]
    target = re.sub(r"^(不对|错了|修正|改一下|记住)[，,。\s]*", "", target)
    target = re.split(r"不是|应该|以后|这家|这个|商户|买的|消费|是|算|归为|属于", target, maxsplit=1)[0]
    target = target.strip(" ，,。:：")
    if not target:
        quoted = re.search(r"[“\"']([^”\"']+)[”\"']", message)
        target = quoted.group(1).strip() if quoted else ""
    if not target:
        return None
    return target, category


@app.on_event("startup")
def startup():
    init_db()
    sync_json_files()


@app.get("/")
def index():
    return FileResponse(WEB_DIR / "index.html")


@app.get("/api/dashboard")
def get_dashboard():
    return dashboard_payload()


@app.patch("/api/transactions/{transaction_id}/category")
def update_transaction_category(transaction_id: int, payload: CategoryUpdate):
    category = payload.category.strip()

    with connect_db() as conn:
        row = conn.execute(
            "SELECT id, merchant, type FROM transactions WHERE id = ?",
            (transaction_id,),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="找不到这笔流水。")
        if category not in categories_for_type(row["type"]):
            raise HTTPException(status_code=400, detail=f"{row['type']}流水不能选择这个分类。")

        conn.execute(
            "UPDATE transactions SET category = ? WHERE id = ?",
            (category, transaction_id),
        )
        conn.execute(
            """
            INSERT INTO user_rules (merchant, category, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(merchant) DO UPDATE SET
                category = excluded.category,
                updated_at = CURRENT_TIMESTAMP
            """,
            (row["merchant"], category),
        )
        conn.commit()

    sync_json_files()
    return {
        "reply": f"已把“{row['merchant']}”改为“{category}”，并记住这个分类习惯。",
        "need_refresh": True,
        "dashboard": dashboard_payload([transaction_id]),
    }


@app.post("/api/chat/upload")
async def upload_receipt(file: UploadFile = File(...)):
    suffix = Path(file.filename or "receipt.png").suffix.lower()
    if suffix not in {".png", ".jpg", ".jpeg"}:
        raise HTTPException(status_code=400, detail="请上传 PNG/JPG/JPEG 格式的账单截图。")

    if not os.getenv("DASHSCOPE_API_KEY", "").strip():
        raise HTTPException(status_code=400, detail="服务端未设置环境变量 DASHSCOPE_API_KEY。")
    with tempfile.TemporaryDirectory() as tmp:
        image_path = Path(tmp) / f"receipt{suffix}"
        with image_path.open("wb") as f:
            shutil.copyfileobj(file.file, f)
        extracted = call_vlm_to_extract(f"file://{image_path}")

    inserted = []
    skipped = 0
    with connect_db() as conn:
        for item in extracted:
            tx = normalize_transaction(item)
            if not tx:
                skipped += 1
                continue
            tx["category"] = classify_transaction(conn, tx)
            if exists_transaction(conn, tx):
                skipped += 1
                continue
            tx_id = insert_transaction(conn, tx, source="upload")
            inserted.append({**tx, "id": tx_id})
        conn.commit()

    sync_json_files()
    if inserted:
        lines = [f"{tx['merchant']} - {tx['amount']:.2f}元 - {tx['category']}" for tx in inserted[:3]]
        more = f" 等 {len(inserted)} 笔" if len(inserted) > 3 else ""
        reply = f"✅ 记账成功！为您入账：{'；'.join(lines)}{more}。"
    else:
        reply = "我看过这张截图了，没有发现可入账的新流水，可能是重复账单或截图信息不完整。"

    return {
        "reply": reply,
        "items": inserted,
        "skipped": skipped,
        "need_refresh": True,
        "dashboard": dashboard_payload([tx["id"] for tx in inserted]),
    }


@app.post("/api/chat/message")
def chat_message(payload: ChatMessage):
    message = payload.message.strip()
    if not message:
        raise HTTPException(status_code=400, detail="消息不能为空。")

    correction = parse_correction(message)
    if not correction:
        return {
            "reply": "我能处理类似“人淡如菊算餐饮”这样的纠偏指令。你也可以上传截图，我来帮你记账。",
            "need_refresh": False,
        }

    target, category = correction
    with connect_db() as conn:
        conn.execute(
            """
            INSERT INTO user_rules (merchant, category, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(merchant) DO UPDATE SET
                category = excluded.category,
                updated_at = CURRENT_TIMESTAMP
            """,
            (target, category),
        )
        cursor = conn.execute(
            """
            UPDATE transactions
            SET category = ?
            WHERE merchant LIKE ?
            """,
            (category, f"%{target}%"),
        )
        affected = cursor.rowcount
        ids = [
            row["id"]
            for row in conn.execute(
                "SELECT id FROM transactions WHERE merchant LIKE ? ORDER BY time DESC",
                (f"%{target}%",),
            ).fetchall()
        ]
        conn.commit()

    sync_json_files()
    return {
        "reply": f"🫡 收到！已记住“{target} -> {category}”，并修正了 {affected} 笔历史账单。",
        "need_refresh": True,
        "dashboard": dashboard_payload(ids),
    }
