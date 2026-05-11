import json
import os


def run_cleaning_pipeline(input_file, output_cleaned_file, output_removed_file, history_ledger_file):
    print(f"🚰 [阶段二 & 三：质检与智能去重车间 (带全局审计)] 启动！")
    print("-" * 50)

    if not os.path.exists(input_file):
        print(f"❌ 找不到文件: {input_file}，请确认第一步是否执行成功！")
        return

    # 读取大水池里的原始数据
    with open(input_file, "r", encoding="utf-8") as f:
        raw_data_pool = json.load(f)

    print(f"📥 成功读取原始数据池，本次共计 {len(raw_data_pool)} 笔新流水。")

    verified_data = []
    removed_data = []  # 🌟 用于收集被剔除数据的“垃圾桶”

    # 统计数据面板 (新增全局历史去重统计)
    stats = {
        "bad_format": 0,
        "duplicates_exact": 0,
        "duplicates_fuzzy": 0,
        "duplicates_historical": 0,  # 🌟 新增：历史跨批次重复统计
        "passed": 0
    }

    for item in raw_data_pool:
        # ==========================================
        # 🛡️ 阶段二：质检车间 (格式与类型校验)
        # ==========================================
        required_keys = ["time", "merchant", "type", "amount"]
        if not all(key in item for key in required_keys):
            item['_remove_reason'] = "格式错误：核心字段缺失"
            removed_data.append(item)
            stats["bad_format"] += 1
            continue

        try:
            # 终极清洗：剥离所有隐形垃圾字符
            clean_time = str(item['time']).strip()
            clean_merchant = str(item['merchant']).replace('\n', '').replace('\r', '').strip()
            clean_type = str(item['type']).strip()
            # 强制格式化金额为两位小数的字符串进行对比
            clean_amount = f"{float(item['amount']):.2f}"
        except ValueError:
            item['_remove_reason'] = f"格式错误：金额无法解析 ({item.get('amount')})"
            removed_data.append(item)
            stats["bad_format"] += 1
            continue

        # ==========================================
        # 🧠 阶段三：智能批内去重 (处理本次上传的同批图片)
        # ==========================================
        is_duplicate = False

        # 拿着当前这笔账，去已经合格的列表里找有没有“兄弟”
        for existing_item in verified_data:
            # 1. 核心数字三要素必须绝对相等 (时间、类型、金额)
            if (existing_item['time'] == clean_time and
                    existing_item['type'] == clean_type and
                    f"{float(existing_item['amount']):.2f}" == clean_amount):

                existing_merchant = existing_item['merchant']

                # 2. 商户名完全一样 -> 经典连拍重复
                if clean_merchant == existing_merchant:
                    is_duplicate = True
                    stats["duplicates_exact"] += 1
                    item['_remove_reason'] = "批内完全重复：同批次连拍截屏产生"
                    removed_data.append(item)
                    break

                # 3. 模糊匹配：如果名字互相包含（解决截断问题）
                elif clean_merchant in existing_merchant or existing_merchant in clean_merchant:
                    is_duplicate = True
                    stats["duplicates_fuzzy"] += 1

                    # 4. 优胜劣汰：用名字更长的那个覆盖短的，保留最多信息！
                    if len(clean_merchant) > len(existing_merchant):
                        print(f"  ✨ [信息合并] {existing_merchant} -> 升级为 -> {clean_merchant}")
                        item['_remove_reason'] = f"合并升级：由于包含更完整信息，替换了原有的 '{existing_merchant}'"
                        removed_data.append(item)
                        existing_item['merchant'] = clean_merchant
                    else:
                        print(f"  🛡️ [模糊拦截] 已过滤被截断的重复项: {clean_merchant}")
                        item['_remove_reason'] = f"截断重复：已保留批次中更完整的名字 '{existing_merchant}'"
                        removed_data.append(item)
                    break

        if not is_duplicate:
            item['time'] = clean_time
            item['merchant'] = clean_merchant
            item['type'] = clean_type
            item['amount'] = float(clean_amount)
            verified_data.append(item)

    # ==========================================
    # 🌍 阶段三.五：全局存量去重 (跨批次哈希碰撞)
    # ==========================================
    final_verified_data = []
    historical_fingerprints = set()

    # 1. 提取历史总账本的数字指纹
    if os.path.exists(history_ledger_file):
        with open(history_ledger_file, "r", encoding="utf-8") as f:
            history_data = json.load(f)
            for h_item in history_data:
                h_time = str(h_item.get('time', '')).strip()
                h_type = str(h_item.get('type', '')).strip()
                try:
                    h_amt = f"{float(h_item.get('amount', 0)):.2f}"
                except ValueError:
                    h_amt = "0.00"
                historical_fingerprints.add(f"{h_time}_{h_type}_{h_amt}")

    # 2. 拿着本次洗净的数据，去撞历史指纹库
    for item in verified_data:
        fingerprint = f"{item['time']}_{item['type']}_{item['amount']:.2f}"

        if fingerprint in historical_fingerprints:
            # 撞上了！说明是以前记过的账
            item['_remove_reason'] = "跨批次重复：总账本中已存在该笔历史流水"
            removed_data.append(item)
            stats["duplicates_historical"] += 1
            print(f"  🛑 [全局拦截] 拦截已入账历史数据: {item['merchant']} ({item['amount']}元)")
        else:
            # 没撞上，真正的纯增量新数据
            final_verified_data.append(item)
            stats["passed"] += 1

    # ==========================================
    # 💾 输出纯净结果与审计日志
    # ==========================================
    with open(output_cleaned_file, "w", encoding="utf-8") as f:
        json.dump(final_verified_data, f, ensure_ascii=False, indent=2)

    # 追加写入还是覆盖写入？因为是审计日志，覆盖写入当前批次的日志即可
    with open(output_removed_file, "w", encoding="utf-8") as f:
        json.dump(removed_data, f, ensure_ascii=False, indent=2)

    print("-" * 50)
    print(f"✅ 清洗与去重完成！数据质检报告：")
    print(f"   - ❌ 拦截格式错误: {stats['bad_format']} 笔")
    print(f"   - 🗑️ 剔除批内绝对重复: {stats['duplicates_exact']} 笔")
    print(f"   - ✂️ 修复批内截断重复: {stats['duplicates_fuzzy']} 笔")
    print(f"   - 🛡️ 拦截全局历史重复: {stats['duplicates_historical']} 笔")
    print(f"   - 🌟 最终纯增量数据: {stats['passed']} 笔 (已保存至 {output_cleaned_file})")
    print(f"   - 📂 剔除明细档案: 共 {len(removed_data)} 笔 (已保存至 {output_removed_file})")


if __name__ == "__main__":
    # 阶段一输出的生数据
    input_json = "stage1_raw_data.json"

    # 阶段二输出的纯增量熟数据（准备喂给大模型的）
    output_cleaned_json = "stage2_cleaned_data.json"

    # 被剔除项目的审计记录文件
    output_removed_json = "stage2_removed_duplicates.json"

    # 🌟 新增入参：你最终的全局历史总账本
    history_json = "stage4_final_ledger.json"

    run_cleaning_pipeline(input_json, output_cleaned_json, output_removed_json, history_json)