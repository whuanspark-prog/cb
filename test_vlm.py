import dashscope
from dashscope import MultiModalConversation
import json
import datetime
import os

# ==========================================
# 🔑 你的 API Key (请填入最新的，注意保密)
# ==========================================
def configure_dashscope_api_key():
    api_key = os.getenv("DASHSCOPE_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("请先设置环境变量 DASHSCOPE_API_KEY")
    dashscope.api_key = api_key


def call_vlm_to_extract(image_path):
    """
    核心感知引擎：负责单张图片的解析
    """
    configure_dashscope_api_key()
    current_date = datetime.date.today().strftime("%Y-%m-%d")

    # 【终极版 Prompt】包含了收支分类规则和去重排除规则
    system_prompt = f"""
    你是一个高精度的财务数据提取专家。
    【当前系统时间】：今天是 {current_date}。
    
    请严格遵守核心铁律 - 对抗幻觉（必须严格遵守）：
    1. 宁缺毋滥（禁止脑补）：只提取**上下边界完全可见**的交易记录。如果某笔流水在截图顶部或底部被截断（例如：只露出时间没露出金额，或只露出商户名没露出时间），**请直接丢弃该笔记录！绝对不允许猜测、推导或捏造任何缺失字段！**
    2. 占位符兜底：对于图片边缘的流水，如果你拿不准它是否完整，请不要强行猜测。你可以正常输出这笔记录，但必须强制将你看不见的字段填写为 "UNKNOWN"。
    3. 严禁逻辑推演：不要根据上下文的流水时间去顺延或倒推被截断流水的时间，看到什么就输出什么，没看到就写 "UNKNOWN" 或直接丢弃。
    
    请严格遵循以下规则提取交易记录：
    1. 【排除规则（极度重要）】：为了防止重复记账，如果交易名称或商户名中包含“还款”（如“花呗主动还款”、“信用卡还款”等内部转账行为），请直接跳过，绝对不要将其提取到最终结果中！
    2. 【字段规范】：
       - time (字符串): 交易时间。统一格式化为严格的 "YYYY-MM-DD HH:MM" 绝对时间。
         *注意：如果显示为“今天 16:30”，请结合当前系统时间换算；“昨天”往前推一天；“05-04 16:25”补齐当前系统年份。*
       - merchant (字符串): 交易对象或商户名称。
       - type (字符串): 收支类型。仔细观察金额前方的符号规律：
         * 如果金额前面有 "-" 号，输出 "支出"；如果有 "+" 号，或者【没有任何符号】（支付宝收入默认无符号），输出 "收入"。
       - amount (浮点数): 交易金额绝对值。剥离 "+", "-", "¥" 等符号，仅保留干净的数字本身。

    【输出格式强制要求】
    必须且只能输出严格的 JSON 数组格式，不要有任何多余的解释文字，不要带 Markdown 符号：
    [
      {{"time": "2026-05-06 16:30", "merchant": "瑞幸咖啡", "type": "支出", "amount": 15.00}},
      {{"time": "2026-05-08 05:06", "merchant": "余额宝-收益发放", "type": "收入", "amount": 0.06}}
    ]
    """

    messages = [
        {
            "role": "user",
            "content": [
                {"image": image_path},
                {"text": system_prompt}
            ]
        }
    ]

    try:
        response = MultiModalConversation.call(
            model='qwen-vl-max',
            messages=messages
        )

        raw_content = response.output.choices[0].message.content

        # 剥离阿里云特有的“快递盒” (List -> Dict)
        if isinstance(raw_content, list):
            result_text = raw_content[0]['text']
        else:
            result_text = raw_content

        # 清洗可能带有的 Markdown 符号
        result_text = result_text.replace("```json", "").replace("```", "").strip()

        try:
            parsed_json = json.loads(result_text)
            return parsed_json
        except json.JSONDecodeError:
            print(f"❌ 解析失败，模型返回了非标准格式的数据")
            return []

    except Exception as e:
        print(f"❌ API 调用异常: {e}")
        return []


def run_extraction_stage(folder_path):
    """
    感知车间流水线：遍历文件夹，收集所有数据
    """
    raw_data_pool = []

    # 筛选出所有的图片文件
    valid_extensions = ('.png', '.jpg', '.jpeg')
    image_files = [f for f in os.listdir(folder_path) if f.lower().endswith(valid_extensions)]

    print(f"🏭 [阶段一：感知车间] 启动！共发现 {len(image_files)} 张账单截图。")
    print("-" * 50)

    for index, file_name in enumerate(image_files, start=1):
        print(f"⏳ 正在处理 ({index}/{len(image_files)}): {file_name} ...")

        image_absolute_path = os.path.join(folder_path, file_name)
        target_image = f"file://{image_absolute_path}"

        # 呼叫大模型提取单张图
        extracted_items = call_vlm_to_extract(target_image)

        if extracted_items:
            print(f"  ✅ 成功提取 {len(extracted_items)} 笔交易。")
            # 将提取到的数据倒进大水池里
            raw_data_pool.extend(extracted_items)
        else:
            print(f"  ⚠️ 未能从该图片中提取到有效数据。")

    print("-" * 50)
    print(f"🎉 阶段一全部完成！所有图片共提取出 {len(raw_data_pool)} 笔原始流水。")

    # 将结果保存为本地 JSON 文件，作为下一阶段的输入
    output_file = "stage1_raw_data.json"
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(raw_data_pool, f, ensure_ascii=False, indent=2)

    print(f"💾 原始数据大水池已保存至当前目录下的: {output_file}")


if __name__ == "__main__":
    # ==========================================
    # 你的账单文件夹绝对路径
    # ==========================================
    bill_folder = r"D:\Agentaccount\账单2"

    # 启动第一阶段流水线
    run_extraction_stage(bill_folder)
