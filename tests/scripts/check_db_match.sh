#!/bin/bash

echo "=========================================="
echo "🔍 代码与数据库字段匹配检查"
echo "=========================================="
echo ""

python3 << 'EOF'
import sys
sys.path.insert(0, 'cloud')
from database import mysql_client

print("=== 检查所有表的字段匹配情况 ===\n")

# 定义代码中使用的字段
expected_fields = {
    'vehicle_whitelist': {
        'code_expects': ['plate_number', 'owner_name', 'status'],
        'usage': 'get_whitelist_entry(), plate_recognition_processor.py'
    },
    'edge_device': {
        'code_expects': ['device_id', 'device_type', 'stream_url', 'scene_id', 'status'],
        'usage': 'upsert_device(), device_manager.py'
    },
    'recognition_event': {
        'code_expects': ['event_type', 'device_id', 'scene_id', 'plate_number', 'vehicle_type', 'confidence', 'bbox', 'detail_json'],
        'usage': 'insert_recognition_event(), video_processor.py'
    },
    'alarm_record': {
        'code_expects': ['alarm_type', 'device_id', 'scene_id', 'target_type', 'target_id', 'plate_number', 'description', 'bbox', 'status', 'detail_json'],
        'usage': 'insert_alarm_record(), video_processor.py'
    },
    'system_config': {
        'code_expects': ['config_key', 'config_value', 'description'],
        'usage': 'load_system_config(), video_processor.py'
    }
}

mismatches = []

with mysql_client.get_connection() as conn:
    with conn.cursor() as cursor:
        for table_name, info in expected_fields.items():
            print(f"📋 {table_name}")
            print(f"   用途: {info['usage']}")

            # 获取实际字段
            cursor.execute(f'DESCRIBE {table_name}')
            columns = cursor.fetchall()
            actual_fields = [col['Field'] for col in columns]

            print(f"   实际字段: {', '.join(actual_fields[:10])}{'...' if len(actual_fields) > 10 else ''}")
            print(f"   代码期望: {', '.join(info['code_expects'])}")

            # 检查匹配
            missing_fields = []
            for field in info['code_expects']:
                if field not in actual_fields:
                    missing_fields.append(field)

            if missing_fields:
                print(f"   ❌ 缺少字段: {', '.join(missing_fields)}")
                mismatches.append({
                    'table': table_name,
                    'missing': missing_fields,
                    'actual': actual_fields
                })
            else:
                print(f"   ✅ 字段匹配")

            print()

print("\n=== 匹配结果总结 ===\n")

if mismatches:
    print(f"❌ 发现 {len(mismatches)} 个表的字段不匹配:\n")

    for mismatch in mismatches:
        print(f"表: {mismatch['table']}")
        print(f"  缺少字段: {', '.join(mismatch['missing'])}")
        print(f"  可能的对应字段:")

        # 智能匹配建议
        for missing in mismatch['missing']:
            similar = [f for f in mismatch['actual'] if missing.lower() in f.lower() or f.lower() in missing.lower()]
            if similar:
                print(f"    {missing} → 可能是 {', '.join(similar)}")
        print()
else:
    print("✅ 所有表字段匹配正常！")

print("\n=== 功能测试 ===\n")

# 测试关键函数
print("1️⃣  测试 get_whitelist_entry...")
try:
    result = mysql_client.get_whitelist_entry('京E4682Y')
    if result:
        print(f"   ✅ 查询成功")
        # 检查代码中使用的字段
        if 'permission_status' in result:
            print(f"   ✅ permission_status 字段存在 (代码期望: status)")
        if 'owner' in result:
            print(f"   ✅ owner 字段存在 (代码期望: owner_name)")
    else:
        print(f"   ⚠️  未找到该车牌")
except Exception as e:
    print(f"   ❌ 查询失败: {e}")

print()

print("2️⃣  测试 load_system_config...")
try:
    config = mysql_client.load_system_config()
    print(f"   ✅ 加载成功，配置项: {len(config)}")
    for key in config:
        print(f"      - {key}")
except Exception as e:
    print(f"   ❌ 加载失败: {e}")

print()

print("3️⃣  测试 insert_recognition_event...")
try:
    # 使用现有设备
    with mysql_client.get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute('SELECT device_id FROM edge_device LIMIT 1')
            device = cursor.fetchone()
            device_id = device['device_id'] if device else None

    if device_id:
        from datetime import datetime
        test_data = {
            'device_id': device_id,
            'plate_number': '匹配测试123',
            'vehicle_type': 'car',
            'confidence': 0.99,
            'bbox': [100, 200, 300, 400],
            'timestamp': datetime.now().isoformat()
        }
        result = mysql_client.insert_recognition_event('vehicle_detection', device_id, test_data, scene_id='test')
        print(f"   ✅ 写入成功")
    else:
        print(f"   ⚠️  没有设备，跳过测试")
except Exception as e:
    print(f"   ❌ 写入失败: {e}")

print()
print("========================================")
print("检查完成！")
print("========================================")

EOF
