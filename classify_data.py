import json
import os
import dashscope
from dashscope import Generation

# ==========================================
# 🔑 你的 API Key
# ==========================================
def configure_dashscope_api_key():
    api_key = os.getenv("DASHSCOPE_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("请先设置环境变量 DASHSCOPE_API_KEY")
    dashscope.api_key = api_key

# 标准分类库
EXPENSE_CATEGORIES = [
    "餐饮", "服饰", "日用", "数码", "美妆", "住房", "交通", "娱乐",
    "医疗", "通讯", "学习", "办公", "运动", "人情", "育儿", "宠物",
    "旅行", "追星", "其他"
]

INCOME_CATEGORIES = [
    "工资", "奖金", "加班", "福利", "公积金", "红包", "兼职",
    "副业", "退税", "投资", "意外收入", "其他"
]

USER_RULES_FILE = "user_rules.json"


# ==========================================
# 🛡️ 新增防线：个人专属记忆库 (One-Shot Learning)
# ==========================================
def personal_rule_intercept(merchant):
    """
    第一道防线：最高优先级。只要你在 Dashboard 修改过，系统永生不忘。
    """
    if not os.path.exists(USER_RULES_FILE):
        return None

    try:
        with open(USER_RULES_FILE, "r", encoding="utf-8") as f:
            user_rules = json.load(f)

        merchant_clean = str(merchant).strip()
        if merchant_clean in user_rules:
            return user_rules[merchant_clean]
    except Exception as e:
        print(f"⚠️ 读取私人记忆库失败: {e}")

    return None


# ==========================================
# 🛡️ 核心升级：本地专家规则库 (拦截器)
# ==========================================
def rule_based_intercept(merchant, tx_type):
    """
    第二道防线：基于业务常识的关键字拦截
    """
    merchant_lower = merchant.lower()

    # 针对支出的规则
    if tx_type == "支出":
        if any(kw in merchant_lower for kw in ["鸿易博", "滴滴", "花小猪", "曹操出行", "地铁", "公交", "12306"]):
            return "交通"
        if any(kw in merchant_lower for kw in ["零食", "便利店", "超市", "麦当劳", "肯德基", "外卖", "饿了么"]):
            return "餐饮"
        if any(kw in merchant_lower for kw in ["转账", "红包"]):
            return "人情"

    # 针对收入的规则
    elif tx_type == "收入":
        if any(kw in merchant_lower for kw in ["转账", "来自", "红包"]):
            return "红包"
        if any(kw in merchant_lower for kw in ["余额宝", "收益", "利息", "基金"]):
            return "投资"
        if any(kw in merchant_lower for kw in ["退款"]):
            return "其他"

    return None


def intelligent_dual_classify(unique_transactions):
    """
    第三道防线：呼叫大模型兜底
    """
    if not unique_transactions:
        return {}

    print(f"🤖 前两道防线未命中，将剩余 {len(unique_transactions)} 个疑难商户交由 Qwen-Max 兜底分析...")

    configure_dashscope_api_key()
    prompt = f"""
    你是一个极其严谨的财务审计专家。
    请严格根据【收支类型】，从【标签库】中选择最合适的一个词分类。

    【支出专属标签库】：{', '.join(EXPENSE_CATEGORIES)}
    【收入专属标签库】：{', '.join(INCOME_CATEGORIES)}

    【待分类交易列表】：
    {json.dumps(unique_transactions, ensure_ascii=False)}

    【分类经验指导（请严格学习以下逻辑）】：
    - 遇到超长名字（如"XX零食超市湖北黄冈店"），请提取核心业务"零食超市"，归入"餐饮"或"日用"。
    - 遇到未知的网络科技公司名字，请谨慎判断，如果无法确定，请填"【待人工确认】"。

    【输出规则】：必须且只能输出 JSON 字典，键为商户原名，值为标签。
    """

    try:
        response = Generation.call(
            model='qwen-max',
            messages=[{"role": "user", "content": prompt}],
            result_format='message'
        )
        result_text = response.output.choices[0].message.content
        return json.loads(result_text.replace("```json", "").replace("```", "").strip())
    except Exception as e:
        print(f"❌ 大模型兜底失败: {e}")
        return {}


def run_classification_pipeline(input_file, output_file):
    print(f"🏷️ [阶段四：归纳决策车间 (三级漏斗自适应引擎)] 启动！")
    print("-" * 50)

    if not os.path.exists(input_file):
        print(f"❌ 找不到输入文件 {input_file}")
        return

    with open(input_file, "r", encoding="utf-8") as f:
        cleaned_data = json.load(f)

    ai_tasks = []
    ai_task_identifiers = set()
    category_mapping = {}

    personal_intercept_count = 0
    rule_intercept_count = 0

    for item in cleaned_data:
        merchant = item['merchant']
        tx_type = item['type']
        identifier = f"{merchant}_{tx_type}"

        # ==========================================
        # 🚦 三级漏斗路由逻辑
        # ==========================================

        # 1. 尝试个人记忆拦截 (最高优先级)
        personal_result = personal_rule_intercept(merchant)
        if personal_result:
            category_mapping[identifier] = personal_result
            personal_intercept_count += 1
            continue

        # 2. 尝试全局规则拦截
        rule_result = rule_based_intercept(merchant, tx_type)
        if rule_result:
            category_mapping[identifier] = rule_result
            rule_intercept_count += 1
            continue

        # 3. 如果拦截失败，加入 AI 任务池 (同时去重)
        if identifier not in ai_task_identifiers:
            ai_task_identifiers.add(identifier)
            ai_tasks.append({"merchant": merchant, "type": tx_type})

    print(f"🎯 个人专属记忆库成功拦截: {personal_intercept_count} 笔交易。")
    print(f"🛡️ 本地专家规则库成功拦截: {rule_intercept_count} 笔交易。")

    # 4. 呼叫大模型处理剩下的难题
    ai_results = intelligent_dual_classify(ai_tasks)

    for task in ai_tasks:
        merch = task['merchant']
        if merch in ai_results:
            category_mapping[f"{merch}_{task['type']}"] = ai_results[merch]

# ==========================================
    # 5. 贴标签并合并入总账本 (Append Logic)
    # ==========================================
    for item in cleaned_data:
        merchant = item['merchant']
        tx_type = item['type']
        item['category'] = category_mapping.get(f"{merchant}_{tx_type}", "其他")

    # 🌟 核心修复：先读取老账本，再把新账单塞进去
    final_ledger = []
    if os.path.exists(output_file):
        with open(output_file, "r", encoding="utf-8") as f:
            final_ledger = json.load(f)

    # 将本次刚刚分好类的新账单追加（extend）到老账单列表的末尾
    final_ledger.extend(cleaned_data)

    # 重新将合并后的全量数据写入总账本
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(final_ledger, f, ensure_ascii=False, indent=2)

    print(f"🎉 分类与合并完成！")
    print(f"   - 本次新增流水: {len(cleaned_data)} 笔")
    print(f"   - 账本累计流水: {len(final_ledger)} 笔")
    print(f"   - 终极账本已保存至: {output_file}")


if __name__ == "__main__":
    input_json = "stage2_cleaned_data.json"
    output_json = "stage4_final_ledger.json"
    run_classification_pipeline(input_json, output_json)
