# 迁移版本目录

当前没有 revision 或业务表；不要为骨架生成空迁移。

后续 schema 经授权后，在 `migrations/env.py` 接入实际模型 metadata，
再生成并审阅 revision。业务表须使用 MySQL 8.4 / InnoDB，迁移必须显式
声明 InnoDB 与字符集，不依赖服务器默认值。数据库创建、连接验证及迁移
执行属于后续任务；应用启动不执行 `create_all` 或 Alembic upgrade。
