#!/usr/bin/env python3
"""
向数据库添加车牌白名单的工具脚本
"""
import os
import sys

# 添加父目录到Python路径以支持导入
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(CURRENT_DIR)
CLOUD_DIR = os.path.join(REPO_ROOT, "cloud")
sys.path.insert(0, CLOUD_DIR)

from database import mysql_client


def add_whitelist_plates(plates_info):
    """
    批量添加车牌到白名单

    Args:
        plates_info: 列表，每项为字典 {'plate_number': str, 'owner': str, 'vehicle_type': str, 'remark': str}

    Returns:
        int: 成功添加的数量
    """
    if not mysql_client.check_connection():
        print("❌ 数据库连接失败，请检查配置")
        return 0

    success_count = 0

    with mysql_client.get_connection() as conn:
        with conn.cursor() as cursor:
            for info in plates_info:
                plate_number = info['plate_number']
                owner = info.get('owner')
                vehicle_type = info.get('vehicle_type')
                remark = info.get('remark')
                permission_status = info.get('permission_status', 1)  # 默认允许通行

                try:
                    # 使用 INSERT IGNORE 或 ON DUPLICATE KEY UPDATE 避免重复插入
                    cursor.execute(
                        """
                        INSERT INTO vehicle_whitelist
                        (plate_number, owner, vehicle_type, permission_status, remark)
                        VALUES (%s, %s, %s, %s, %s)
                        ON DUPLICATE KEY UPDATE
                            owner = VALUES(owner),
                            vehicle_type = VALUES(vehicle_type),
                            permission_status = VALUES(permission_status),
                            remark = VALUES(remark),
                            updated_at = CURRENT_TIMESTAMP
                        """,
                        (plate_number, owner, vehicle_type, permission_status, remark)
                    )
                    conn.commit()
                    print(f"✅ 成功添加/更新车牌: {plate_number}")
                    success_count += 1
                except Exception as e:
                    print(f"❌ 添加车牌 {plate_number} 失败: {e}")

    return success_count


def main():
    # 要添加的车牌信息
    plates_to_add = [
        {
            'plate_number': '京E4682Y',
            'owner': None,
            'vehicle_type': None,
            'permission_status': 1,
            'remark': '白名单车辆'
        },
        {
            'plate_number': '京K9134J',
            'owner': None,
            'vehicle_type': None,
            'permission_status': 1,
            'remark': '白名单车辆'
        },
        {
            'plate_number': '京E7654Z',
            'owner': None,
            'vehicle_type': None,
            'permission_status': 1,
            'remark': '白名单车辆'
        },
    ]

    print("=" * 60)
    print("开始向数据库添加车牌白名单")
    print("=" * 60)

    success = add_whitelist_plates(plates_to_add)

    print("\n" + "=" * 60)
    print(f"添加完成！成功: {success}/{len(plates_to_add)}")
    print("=" * 60)

    # 验证添加结果
    print("\n验证添加结果：")
    for info in plates_to_add:
        plate_number = info['plate_number']
        entry = mysql_client.get_whitelist_entry(plate_number)
        if entry:
            print(f"✅ {plate_number}: {entry}")
        else:
            print(f"❌ {plate_number}: 未找到")


if __name__ == '__main__':
    main()
