import streamlit as st
import pandas as pd
import plotly.express as px
import json
import os

# ==========================================
# 1. 页面基础配置
# ==========================================
st.set_page_config(page_title="Clip Bill 智能财务看板", layout="wide")
st.title("📊 Clip Bill 智能财务看板")
st.markdown("---")

FILE_PATH = "stage4_final_ledger.json"

# 标准分类库（用于人工接管时的下拉菜单）
STANDARD_CATEGORIES = [
    "餐饮", "服饰", "日用", "数码", "美妆", "住房", "交通", "娱乐",
    "医疗", "通讯", "学习", "办公", "运动", "人情", "育儿", "宠物",
    "旅行", "追星", "其他", "工资", "奖金", "加班", "福利", "公积金",
    "红包", "兼职", "副业", "退税", "投资", "意外收入", "【待人工确认】"
]

if not os.path.exists(FILE_PATH):
    st.error(f"❌ 找不到数据文件 {FILE_PATH}，请确保前三个阶段已成功运行并生成 JSON。")
else:
    # 加载全局数据
    with open(FILE_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    df = pd.DataFrame(data)

    # 🌟 修复点：时间预处理。增加 errors='coerce' 防止因个别格式不一导致崩溃
    # 使用 pd.to_datetime 时不强制指定 format，让其自动兼容有秒和无秒的情况
    df['time'] = pd.to_datetime(df['time'], errors='coerce')

    # 过滤掉无法解析的脏数据（NaT），保证图表正常运行
    df = df.dropna(subset=['time'])

    df['month_str'] = df['time'].dt.strftime('%Y-%m')

    # ==========================================
    # 2. 侧边栏筛选引擎
    # ==========================================
    st.sidebar.header("🔍 数据筛选引擎")

    # 月份筛选
    available_months = sorted(df['month_str'].unique().tolist(), reverse=True)
    available_months.insert(0, "📅 全部时间")
    selected_month = st.sidebar.selectbox("按月份查账", available_months)

    # 类型筛选
    selected_type = st.sidebar.multiselect("收支类型", options=['支出', '收入'], default=['支出', '收入'])

    # 分类筛选
    all_categories = sorted(df['category'].unique().tolist())
    selected_categories = st.sidebar.multiselect("分类过滤", options=all_categories, default=all_categories)

    # 数据联动过滤
    filtered_df = df.copy()
    if selected_month != "📅 全部时间":
        filtered_df = filtered_df[filtered_df['month_str'] == selected_month]

    filtered_df = filtered_df[
        (filtered_df['type'].isin(selected_type)) &
        (filtered_df['category'].isin(selected_categories))
        ]

    if filtered_df.empty:
        st.warning("⚠️ 当前筛选条件下无账单记录，请检查侧边栏选项。")
    else:
        # ==========================================
        # 3. 顶部核心指标
        # ==========================================
        total_income = filtered_df[filtered_df['type'] == '收入']['amount'].sum()
        total_expense = filtered_df[filtered_df['type'] == '支出']['amount'].sum()
        balance = total_income - total_expense

        col1, col2, col3 = st.columns(3)
        col1.metric("总收入", f"¥ {total_income:,.2f}")
        col2.metric("总支出", f"¥ {total_expense:,.2f}")
        col3.metric("结余", f"¥ {balance:,.2f}")

        # ==========================================
        # 4. 可视化图表展示
        # ==========================================
        st.markdown("### 📈 收支占比总览")
        plot_col1, plot_col2 = st.columns(2)

        expense_df = filtered_df[filtered_df['type'] == '支出']
        if not expense_df.empty:
            fig_expense = px.pie(expense_df, values='amount', names='category', title='支出分类权重',
                                 hole=0.4, color_discrete_sequence=px.colors.qualitative.Pastel)
            plot_col1.plotly_chart(fig_expense, use_container_width=True)

        income_df = filtered_df[filtered_df['type'] == '收入']
        if not income_df.empty:
            fig_income = px.pie(income_df, values='amount', names='category', title='收入分类权重',
                                hole=0.4, color_discrete_sequence=px.colors.qualitative.Set3)
            plot_col2.plotly_chart(fig_income, use_container_width=True)

        # ==========================================
        # 5. 排序逻辑：流水明细表 (A-Z + 金额降序)
        # ==========================================
        st.markdown("### 🔍 逐笔流水明细 (已分类对齐)")
        det_tab1, det_tab2 = st.tabs(["🔴 支出明细", "🟢 收入明细"])


        def get_sorted_detail(df_sub):
            if df_sub.empty: return pd.DataFrame()
            # 🌟 核心排序：分类 A->Z 升序，金额 降序
            sorted_sub = df_sub.sort_values(by=['category', 'amount'], ascending=[True, False]).copy()
            # 这里统一显示为“无秒”格式
            sorted_sub['time_display'] = sorted_sub['time'].dt.strftime('%Y-%m-%d %H:%M')
            display = sorted_sub[['category', 'amount', 'merchant', 'time_display']]
            display.columns = ['分类', '金额(¥)', '交易商户/说明', '交易时间']
            return display.reset_index(drop=True)


        with det_tab1:
            st.dataframe(get_sorted_detail(expense_df), use_container_width=True, height=400)
        with det_tab2:
            st.dataframe(get_sorted_detail(income_df), use_container_width=True, height=400)

        # ==========================================
        # 6. 🛠️ 核心设计：人工接管（HITL）工作台
        # ==========================================
        st.markdown("---")
        st.markdown("### 🛠️ 人工审核与数据修正中心")
        st.info("💡 提示：你可以在下方表格中直接修改 AI 识别错误的分类、金额或商户。点击保存后，数据将双向同步回 JSON 账本。")

        # 准备用于编辑的数据，将时间显式转为“无秒”字符串
        df_for_edit = df.copy()
        df_for_edit['time'] = df_for_edit['time'].dt.strftime('%Y-%m-%d %H:%M')

        edited_df = st.data_editor(
            df_for_edit,
            use_container_width=True,
            num_rows="dynamic",
            column_config={
                "category": st.column_config.SelectboxColumn(
                    "分类 (双击修改)",
                    options=STANDARD_CATEGORIES,
                    required=True,
                ),
                "type": st.column_config.SelectboxColumn(
                    "收支类型",
                    options=["支出", "收入"],
                    required=True,
                ),
                "amount": st.column_config.NumberColumn(
                    "金额(¥)",
                    format="%.2f",
                    min_value=0,
                ),
                "time": st.column_config.TextColumn("时间 (YYYY-MM-DD HH:MM)"),
                "merchant": st.column_config.TextColumn("商户名"),
                "month_str": st.column_config.TextColumn("月份标签", disabled=True)
            },
            key="hitl_editor"
        )

        if st.button("💾 确认并保存所有修改", type="primary"):
            try:
                # 1. 提取并清洗表格里的最新数据
                final_data = edited_df.to_dict(orient="records")
                for item in final_data:
                    item['amount'] = float(item['amount'])

                # ==========================================
                # 🌟 自适应学习引擎逻辑
                # ==========================================
                USER_RULES_FILE = "user_rules.json"
                STOP_WORDS = ["微信收款", "支付宝", "扫码支付", "个人收款", "转账", "美团代收"]

                if os.path.exists(USER_RULES_FILE):
                    with open(USER_RULES_FILE, "r", encoding="utf-8") as f:
                        user_rules = json.load(f)
                else:
                    user_rules = {}

                for item in final_data:
                    merchant = str(item.get("merchant", "")).strip()
                    category = str(item.get("category", ""))
                    if not merchant or category == "【待人工确认】":
                        continue
                    if any(sw in merchant for sw in STOP_WORDS):
                        continue
                    user_rules[merchant] = category

                with open(USER_RULES_FILE, "w", encoding="utf-8") as f:
                    json.dump(user_rules, f, ensure_ascii=False, indent=2)

                # ==========================================
                # 2. 覆写主账本并刷新页面
                # ==========================================
                with open(FILE_PATH, "w", encoding="utf-8") as f:
                    json.dump(final_data, f, ensure_ascii=False, indent=2)

                st.success("🎉 账本已更新（遵循无秒标准），正在刷新...")
                st.rerun()
            except Exception as e:
                st.error(f"保存过程中发生错误: {e}")

        # 导出功能
        csv = filtered_df.to_csv(index=False).encode('utf-8-sig')
        st.download_button("📥 导出当前筛选后的 CSV 报表", csv, "my_ledger_export.csv", "text/csv")