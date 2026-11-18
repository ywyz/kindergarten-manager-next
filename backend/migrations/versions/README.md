# 迁移版本目录

本目录保存 v1 MySQL 迁移链，当前包含六个 revision（I1、I2×2、I3、I4、AI1A）。

维护后续 v1 revision 时应核对 `../env.py` 中已有的模型元数据。业务表使用 MySQL 8.4 和 InnoDB，迁移显式声明 InnoDB 与字符集。数据库验证和迁移通过独立命令执行，应用启动不运行 `create_all` 或 Alembic upgrade。

桌面应用的本地 SQLite 迁移在 [../../migrations_local/](../../migrations_local/)。
