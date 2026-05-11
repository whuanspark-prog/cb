import json
import os
import tempfile
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

from clean_data import run_cleaning_pipeline
from classify_data import run_classification_pipeline
from test_vlm import run_extraction_stage


APP_DIR = Path(__file__).resolve().parent
LEDGER_FILE = APP_DIR / "stage4_final_ledger.json"
RAW_FILE = APP_DIR / "stage1_raw_data.json"
CLEANED_FILE = APP_DIR / "stage2_cleaned_data.json"
REMOVED_FILE = APP_DIR / "stage2_removed_duplicates.json"
RULES_FILE = APP_DIR / "user_rules.json"
UPLOAD_DIR = APP_DIR / "uploads"

EXPENSE_CATEGORIES = [
    "餐饮", "服饰", "日用", "数码", "美妆", "住房", "交通", "娱乐",
    "医疗", "通讯", "学习", "办公", "运动", "人情", "育儿", "宠物",
    "旅行", "追星", "其他",
]
INCOME_CATEGORIES = [
    "工资", "奖金", "加班", "福利", "公积金", "红包", "兼职", "副业",
    "退款", "投资", "意外收入", "其他",
]
STANDARD_CATEGORIES = EXPENSE_CATEGORIES + INCOME_CATEGORIES + ["【待人工确认】"]
STANDARD_TYPES = ["支出", "收入"]


st.set_page_config(
    page_title="Clip Bill 智能账本",
    page_icon="💳",
    layout="wide",
    initial_sidebar_state="expanded",
)


def apply_theme():
    st.markdown(
        """
        <style>
        .block-container { padding-top: 1.2rem; padding-bottom: 2rem; }
        [data-testid="stMetricValue"] { font-size: 1.55rem; }
        [data-testid="stSidebar"] { border-right: 1px solid #e8ecef; }
        div[data-testid="stAlert"] { border-radius: 8px; }
        .app-title {
            display: flex;
            align-items: center;
            gap: .65rem;
            margin-bottom: .15rem;
        }
        .app-title h1 {
            font-size: 1.85rem;
            line-height: 1.15;
            margin: 0;
            letter-spacing: 0;
        }
        .muted { color: #637083; font-size: .96rem; }
        .status-pill {
            display: inline-block;
            padding: .2rem .55rem;
            border: 1px solid #d7dee8;
            border-radius: 999px;
            color: #465568;
            font-size: .82rem;
            margin-right: .35rem;
            background: #ffffff;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def read_json(path: Path, default):
    if not path.exists():
        return default
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError:
        st.error(f"{path.name} 不是有效 JSON，请先修复文件。")
        return default


def write_json(path: Path, data):
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def normalize_ledger(records):
    df = pd.DataFrame(records)
    expected = ["time", "merchant", "type", "amount", "category"]
    for col in expected:
        if col not in df.columns:
            df[col] = "" if col != "amount" else 0.0

    df["time"] = pd.to_datetime(df["time"], errors="coerce")
    df["amount"] = pd.to_numeric(df["amount"], errors="coerce").fillna(0.0)
    df["merchant"] = df["merchant"].fillna("").astype(str)
    df["type"] = df["type"].fillna("支出").astype(str)
    df["category"] = df["category"].fillna("【待人工确认】").astype(str)
    df["month"] = df["time"].dt.strftime("%Y-%m").fillna("未知时间")
    df["_row_id"] = range(len(df))
    return df


def dataframe_to_records(df):
    export_df = df.copy()
    export_df["time"] = pd.to_datetime(export_df["time"], errors="coerce").dt.strftime("%Y-%m-%d %H:%M")
    export_df["month_str"] = pd.to_datetime(export_df["time"], errors="coerce").dt.strftime("%Y-%m")
    export_df["amount"] = pd.to_numeric(export_df["amount"], errors="coerce").fillna(0.0).round(2)
    export_df = export_df.drop(columns=[c for c in ["month", "_row_id"] if c in export_df.columns])
    return export_df.to_dict(orient="records")


def refresh_rules_from_records(records):
    rules = read_json(RULES_FILE, {})
    stop_words = ["微信收款", "支付宝", "扫码支付", "个人收款", "转账", "美团代收"]
    for item in records:
        merchant = str(item.get("merchant", "")).strip()
        category = str(item.get("category", "")).strip()
        if not merchant or not category or category == "【待人工确认】":
            continue
        if any(word in merchant for word in stop_words):
            continue
        rules[merchant] = category
    write_json(RULES_FILE, rules)


def sidebar_filters(df):
    st.sidebar.header("筛选账本")
    months = ["全部月份"] + sorted(df["month"].dropna().unique().tolist(), reverse=True)
    selected_month = st.sidebar.selectbox("月份", months)
    selected_types = st.sidebar.multiselect("收支类型", STANDARD_TYPES, default=STANDARD_TYPES)
    categories = sorted([c for c in df["category"].dropna().unique().tolist() if c])
    selected_categories = st.sidebar.multiselect("分类", categories, default=categories)
    keyword = st.sidebar.text_input("搜索商户")

    filtered = df.copy()
    if selected_month != "全部月份":
        filtered = filtered[filtered["month"] == selected_month]
    if selected_types:
        filtered = filtered[filtered["type"].isin(selected_types)]
    if selected_categories:
        filtered = filtered[filtered["category"].isin(selected_categories)]
    if keyword:
        filtered = filtered[filtered["merchant"].str.contains(keyword, case=False, na=False)]
    return filtered


def render_header():
    st.markdown(
        """
        <div class="app-title">
          <h1>Clip Bill 智能账本</h1>
        </div>
        <div class="muted">上传账单截图，自动识别流水、清洗去重、智能分类，并在这里完成校对和导出。</div>
        """,
        unsafe_allow_html=True,
    )


def render_import_tab():
    st.subheader("导入账单截图")
    st.caption("支持 PNG、JPG、JPEG。识别会调用 DashScope 多模态模型，请确认服务端已设置 DASHSCOPE_API_KEY。")
    uploaded_files = st.file_uploader(
        "选择账单截图",
        type=["png", "jpg", "jpeg"],
        accept_multiple_files=True,
    )

    col1, col2, col3 = st.columns([1, 1, 2])
    run_all = col1.button("开始识别并入账", type="primary", width="stretch")
    run_clean = col2.button("仅清洗现有原始数据", width="stretch")

    if run_all:
        if not os.getenv("DASHSCOPE_API_KEY", "").strip():
            st.error("请先设置环境变量 DASHSCOPE_API_KEY。")
            return
        if not uploaded_files:
            st.error("请先上传至少一张账单截图。")
            return

        UPLOAD_DIR.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=UPLOAD_DIR) as tmp:
            tmp_dir = Path(tmp)
            for file in uploaded_files:
                target = tmp_dir / file.name
                target.write_bytes(file.getbuffer())

            with st.status("正在处理截图，请保持页面打开...", expanded=True) as status:
                st.write("1. 识别截图中的交易流水")
                run_extraction_stage(str(tmp_dir))
                st.write("2. 清洗格式并去除重复流水")
                run_cleaning_pipeline(str(RAW_FILE), str(CLEANED_FILE), str(REMOVED_FILE), str(LEDGER_FILE))
                st.write("3. 智能分类并追加到总账")
                run_classification_pipeline(str(CLEANED_FILE), str(LEDGER_FILE))
                status.update(label="处理完成，账本已更新。", state="complete")
        st.rerun()

    if run_clean:
        with st.status("正在清洗现有 stage1_raw_data.json...", expanded=True) as status:
            run_cleaning_pipeline(str(RAW_FILE), str(CLEANED_FILE), str(REMOVED_FILE), str(LEDGER_FILE))
            status.update(label="清洗完成。", state="complete")

    removed_count = len(read_json(REMOVED_FILE, []))
    raw_count = len(read_json(RAW_FILE, []))
    cleaned_count = len(read_json(CLEANED_FILE, []))
    st.markdown(
        f"""
        <span class="status-pill">原始流水 {raw_count}</span>
        <span class="status-pill">清洗后 {cleaned_count}</span>
        <span class="status-pill">拦截记录 {removed_count}</span>
        """,
        unsafe_allow_html=True,
    )


def render_overview_tab(df, filtered_df):
    income = filtered_df.loc[filtered_df["type"] == "收入", "amount"].sum()
    expense = filtered_df.loc[filtered_df["type"] == "支出", "amount"].sum()
    balance = income - expense
    pending = len(df[df["category"] == "【待人工确认】"])

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("收入", f"¥ {income:,.2f}")
    c2.metric("支出", f"¥ {expense:,.2f}")
    c3.metric("结余", f"¥ {balance:,.2f}")
    c4.metric("待确认", f"{pending} 笔")

    if filtered_df.empty:
        st.info("当前筛选条件下没有流水。")
        return

    chart_col1, chart_col2 = st.columns(2)
    expense_df = filtered_df[filtered_df["type"] == "支出"]
    income_df = filtered_df[filtered_df["type"] == "收入"]

    if not expense_df.empty:
        by_expense = expense_df.groupby("category", as_index=False)["amount"].sum()
        chart_col1.plotly_chart(
            px.pie(by_expense, values="amount", names="category", hole=0.45, title="支出分类占比"),
            width="stretch",
        )
    else:
        chart_col1.info("没有支出数据。")

    if not income_df.empty:
        by_income = income_df.groupby("category", as_index=False)["amount"].sum()
        chart_col2.plotly_chart(
            px.pie(by_income, values="amount", names="category", hole=0.45, title="收入分类占比"),
            width="stretch",
        )
    else:
        chart_col2.info("没有收入数据。")

    monthly = (
        filtered_df.dropna(subset=["time"])
        .groupby(["month", "type"], as_index=False)["amount"]
        .sum()
        .sort_values("month")
    )
    if not monthly.empty:
        st.plotly_chart(
            px.bar(monthly, x="month", y="amount", color="type", barmode="group", title="月度收支趋势"),
            width="stretch",
        )

    detail = filtered_df.sort_values("time", ascending=False)[
        ["time", "type", "category", "amount", "merchant"]
    ].copy()
    detail["time"] = detail["time"].dt.strftime("%Y-%m-%d %H:%M")
    detail.columns = ["时间", "类型", "分类", "金额", "商户/说明"]
    st.dataframe(detail, width="stretch", height=360, hide_index=True)


def render_review_tab(df):
    st.subheader("人工校对")
    st.caption("修改后点击保存，会更新总账并同步学习商户分类规则。")

    show_pending = st.toggle("仅显示待人工确认", value=False)
    edit_df = df.copy()
    if show_pending:
        edit_df = edit_df[edit_df["category"] == "【待人工确认】"]

    editable = edit_df[["_row_id", "time", "type", "category", "amount", "merchant"]].copy()
    editable["time"] = editable["time"].dt.strftime("%Y-%m-%d %H:%M")

    edited = st.data_editor(
        editable,
        width="stretch",
        height=520,
        hide_index=True,
        num_rows="dynamic",
        column_config={
            "_row_id": st.column_config.NumberColumn("ID", disabled=True),
            "time": st.column_config.TextColumn("时间"),
            "type": st.column_config.SelectboxColumn("类型", options=STANDARD_TYPES, required=True),
            "category": st.column_config.SelectboxColumn("分类", options=STANDARD_CATEGORIES, required=True),
            "amount": st.column_config.NumberColumn("金额", min_value=0.0, format="%.2f"),
            "merchant": st.column_config.TextColumn("商户/说明"),
        },
    )

    if st.button("保存校对结果", type="primary"):
        merged = df.copy()
        for _, row in edited.iterrows():
            row_id = row.get("_row_id")
            if pd.isna(row_id):
                continue
            mask = merged["_row_id"] == int(row_id)
            if not mask.any():
                continue
            merged.loc[mask, "time"] = pd.to_datetime(row["time"], errors="coerce")
            merged.loc[mask, "type"] = row["type"]
            merged.loc[mask, "category"] = row["category"]
            merged.loc[mask, "amount"] = float(row["amount"] or 0)
            merged.loc[mask, "merchant"] = row["merchant"]

        records = dataframe_to_records(merged)
        write_json(LEDGER_FILE, records)
        refresh_rules_from_records(records)
        st.success("已保存，总账和学习规则都更新了。")
        st.rerun()


def render_rules_tab():
    st.subheader("学习规则")
    rules = read_json(RULES_FILE, {})
    if not rules:
        st.info("还没有学习到商户分类规则。")
        return

    rules_df = pd.DataFrame(
        [{"merchant": merchant, "category": category} for merchant, category in rules.items()]
    )
    edited_rules = st.data_editor(
        rules_df,
        width="stretch",
        height=420,
        hide_index=True,
        num_rows="dynamic",
        column_config={
            "merchant": st.column_config.TextColumn("商户/说明", required=True),
            "category": st.column_config.SelectboxColumn("分类", options=STANDARD_CATEGORIES, required=True),
        },
    )

    if st.button("保存规则"):
        cleaned_rules = {
            str(row["merchant"]).strip(): str(row["category"]).strip()
            for _, row in edited_rules.iterrows()
            if str(row.get("merchant", "")).strip()
        }
        write_json(RULES_FILE, cleaned_rules)
        st.success("规则已保存。")
        st.rerun()


def render_export_tab(df, filtered_df):
    st.subheader("导出")
    csv = filtered_df.drop(columns=["_row_id"], errors="ignore").to_csv(index=False).encode("utf-8-sig")
    json_bytes = json.dumps(dataframe_to_records(df), ensure_ascii=False, indent=2).encode("utf-8")

    c1, c2 = st.columns(2)
    c1.download_button("下载当前筛选 CSV", csv, "clip_bill_filtered.csv", "text/csv", width="stretch")
    c2.download_button("下载完整账本 JSON", json_bytes, "clip_bill_ledger.json", "application/json", width="stretch")

    st.caption(f"账本文件位置：{LEDGER_FILE}")


def main():
    apply_theme()
    render_header()

    records = read_json(LEDGER_FILE, [])
    df = normalize_ledger(records)

    if df.empty:
        st.info("还没有账本数据。请先在“导入截图”里上传账单截图并运行流水线。")
        tabs = st.tabs(["导入截图", "学习规则"])
        with tabs[0]:
            render_import_tab()
        with tabs[1]:
            render_rules_tab()
        return

    filtered_df = sidebar_filters(df)

    tabs = st.tabs(["总览", "导入截图", "人工校对", "学习规则", "导出"])
    with tabs[0]:
        render_overview_tab(df, filtered_df)
    with tabs[1]:
        render_import_tab()
    with tabs[2]:
        render_review_tab(df)
    with tabs[3]:
        render_rules_tab()
    with tabs[4]:
        render_export_tab(df, filtered_df)


if __name__ == "__main__":
    main()
