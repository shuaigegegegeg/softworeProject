# migrate_database.py - 数据库迁移脚本
import os
import sqlite3
import shutil
from datetime import datetime


def backup_database(db_path):
    """备份现有数据库"""
    backup_name = f"car_system_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
    backup_path = os.path.join(os.path.dirname(db_path), backup_name)

    try:
        shutil.copy2(db_path, backup_path)
        print(f"✅ 数据库已备份到: {backup_path}")
        return backup_path
    except Exception as e:
        print(f"❌ 备份失败: {e}")
        return None


def check_column_exists(cursor, table, column):
    """检查列是否存在"""
    cursor.execute(f"PRAGMA table_info({table})")
    columns = [row[1] for row in cursor.fetchall()]
    return column in columns


def migrate_database(db_path):
    """执行数据库迁移"""
    if not os.path.exists(db_path):
        print(f"❌ 数据库文件不存在: {db_path}")
        return False

    # 备份数据库
    backup_path = backup_database(db_path)
    if not backup_path:
        print("❌ 无法备份数据库，迁移中止")
        return False

    try:
        # 连接数据库
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        print("🔍 检查数据库结构...")

        # 检查需要添加的字段
        fields_to_add = [
            ('longitude', 'FLOAT'),
            ('latitude', 'FLOAT'),
            ('home_name', 'VARCHAR(100)')
        ]

        added_fields = []

        for field_name, field_type in fields_to_add:
            if not check_column_exists(cursor, 'user', field_name):
                try:
                    sql = f"ALTER TABLE user ADD COLUMN {field_name} {field_type}"
                    cursor.execute(sql)
                    added_fields.append(field_name)
                    print(f"✅ 已添加字段: {field_name} ({field_type})")
                except Exception as e:
                    print(f"❌ 添加字段 {field_name} 失败: {e}")
                    raise e
            else:
                print(f"ℹ️ 字段 {field_name} 已存在，跳过")

        # 提交更改
        conn.commit()

        if added_fields:
            print(f"🎉 数据库迁移完成！添加了 {len(added_fields)} 个新字段: {', '.join(added_fields)}")
        else:
            print("ℹ️ 数据库已是最新版本，无需迁移")

        # 验证迁移结果
        print("\n🔍 验证迁移结果:")
        cursor.execute("PRAGMA table_info(user)")
        columns = cursor.fetchall()

        print("用户表当前字段:")
        for col in columns:
            print(f"  - {col[1]} ({col[2]})")

        conn.close()
        return True

    except Exception as e:
        print(f"❌ 数据库迁移失败: {e}")
        print(f"🔄 正在恢复备份...")

        try:
            # 恢复备份
            shutil.copy2(backup_path, db_path)
            print(f"✅ 已恢复到备份版本: {backup_path}")
        except Exception as restore_error:
            print(f"❌ 恢复备份失败: {restore_error}")
            print(f"⚠️ 请手动从 {backup_path} 恢复数据库")

        return False


def main():
    """主函数"""
    print("🔧 车载系统数据库迁移工具")
    print("=" * 50)

    # 数据库路径
    db_path = os.path.join("instance", "car_system.db")

    if not os.path.exists(db_path):
        print(f"❌ 数据库文件不存在: {db_path}")
        print("请确保数据库文件存在，或者运行主程序创建数据库")
        return

    print(f"📍 数据库位置: {db_path}")

    # 询问用户确认
    response = input("\n是否继续进行数据库迁移？(y/N): ").strip().lower()
    if response not in ['y', 'yes']:
        print("❌ 用户取消操作")
        return

    # 执行迁移
    success = migrate_database(db_path)

    if success:
        print("\n🎉 迁移成功！现在可以重启车载系统了")
    else:
        print("\n❌ 迁移失败！请检查错误信息")


if __name__ == "__main__":
    main()