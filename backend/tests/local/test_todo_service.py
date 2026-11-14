"""Pure personal-todo service tests with an in-process fake repository.

No SQLite, database, HTTP server or migration is used.  The fake repository
is a small dict-backed test double, not a database.
"""

from __future__ import annotations

import copy
import unittest
import uuid
from datetime import date, datetime, timedelta

from app.local import todo_domain as domain
from app.local import todo_service
from app.local.todo_models import LocalTodo
from app.local.todo_repository import _row


def request_id() -> str:
    return str(uuid.uuid4())


class FakeTodoRepository:
    profile_id = "profile-1"

    def __init__(self) -> None:
        self.todos: dict[str, dict] = {}
        self.operations: dict[str, dict] = {}
        self.fail_commit = False
        self.fail_rollback = False
        self.rollback_calls = 0

    def list_todos(self, archived=False):
        return [
            copy.deepcopy(row)
            for row in self.todos.values()
            if (row.get("archived_at") is not None) == bool(archived)
        ]

    def read_operation(self, request_id):
        return copy.deepcopy(self.operations.get(request_id))

    def begin_write(self):
        pass

    def commit(self):
        if self.fail_commit:
            raise RuntimeError('synthetic commit lost')

    def rollback(self):
        self.rollback_calls += 1
        if self.fail_rollback:
            raise OSError('synthetic rollback also failed')

    def get_operation(self, request_id):
        return copy.deepcopy(self.operations.get(request_id))

    def get_todo(self, todo_id):
        row = self.todos.get(todo_id)
        return copy.deepcopy(row) if row is not None else None

    def insert_todo(self, row):
        self.todos[row["todo_id"]] = copy.deepcopy(dict(row))

    def update_todo(self, todo_id, fields):
        row = self.todos[todo_id]
        row.update(copy.deepcopy(dict(fields)))
        row["updated_at"] = fields["updated_at"]

    def delete_todo(self, todo_id):
        self.todos.pop(todo_id, None)

    def insert_operation(self, row):
        self.operations[row["request_id"]] = copy.deepcopy(dict(row))


class TodoServicePureTests(unittest.TestCase):
    def setUp(self):
        self.repo = FakeTodoRepository()

    def make(self, title="合成待办", due=None, rid=None):
        return todo_service.create_todo(
            self.repo,
            request_id=rid or request_id(),
            title=title,
            due_date=due,
        )

    def test_create_list_and_profile_scope_shape(self):
        due = date.today() + timedelta(days=2)
        created = self.make("带截止日", due)
        self.assertEqual(created["title"], "带截止日")
        self.assertEqual(created["due_date"], due.isoformat())
        self.assertFalse(created["completed"])
        self.assertEqual(created["version"], 1)
        self.assertEqual(set(created), {
            "todo_id", "title", "due_date", "completed", "archived_at", "version",
            "created_at", "updated_at",
        })
        listed = todo_service.list_todos(self.repo)
        self.assertEqual([item["todo_id"] for item in listed], [created["todo_id"]])

    def test_create_replay_is_idempotent_and_conflicting_reuse_is_rejected(self):
        rid = request_id()
        first = self.make("原请求", rid=rid)
        second = self.make("原请求", rid=rid)
        self.assertEqual(first, second)
        self.assertEqual(len(self.repo.todos), 1)
        with self.assertRaises(domain.TodoRequestConflict):
            self.make("不同内容", rid=rid)

    def test_edit_complete_and_version_conflict_keep_original(self):
        created = self.make("旧标题", date.today())
        edited = todo_service.update_todo(
            self.repo,
            todo_id=created["todo_id"],
            request_id=request_id(),
            expected_version=1,
            fields={"title": "新标题", "due_date": None},
        )
        self.assertEqual(edited["title"], "新标题")
        self.assertIsNone(edited["due_date"])
        self.assertEqual(edited["version"], 2)
        completed = todo_service.update_todo(
            self.repo,
            todo_id=created["todo_id"],
            request_id=request_id(),
            expected_version=2,
            fields={"completed": True},
        )
        self.assertTrue(completed["completed"])
        self.assertEqual(completed["version"], 3)
        with self.assertRaises(domain.TodoVersionConflict) as caught:
            todo_service.update_todo(
                self.repo,
                todo_id=created["todo_id"],
                request_id=request_id(),
                expected_version=1,
                fields={"title": "竞争旧版本"},
            )
        self.assertEqual(caught.exception.details["todo"]["version"], 3)
        self.assertEqual(caught.exception.details["todo"]["title"], "新标题")
        self.assertEqual(self.repo.todos[created["todo_id"]]["title"], "新标题")

    def test_delete_operation_receipt_and_replay(self):
        created = self.make("待删除")
        rid = request_id()
        deleted = todo_service.delete_todo(
            self.repo,
            todo_id=created["todo_id"],
            request_id=rid,
            expected_version=1,
        )
        receipt = todo_service.get_operation(self.repo, request_id=rid)
        self.assertEqual(receipt["todo"]["title"], "待删除")
        self.assertTrue(receipt["deleted"])
        replay = todo_service.delete_todo(
            self.repo,
            todo_id=created["todo_id"],
            request_id=rid,
            expected_version=1,
        )
        self.assertEqual(replay, deleted)
        with self.assertRaises(domain.TodoNotFound):
            todo_service.delete_todo(
                self.repo,
                todo_id=created["todo_id"],
                request_id=request_id(),
                expected_version=1,
            )

    def test_batch_archive_delete_and_original_receipt(self):
        first = self.make("完成一")
        second = self.make("完成二")
        for current in (first, second):
            todo_service.update_todo(
                self.repo,
                todo_id=current["todo_id"],
                request_id=request_id(),
                expected_version=1,
                fields={"completed": True},
            )
        open_item = self.make("未完成不归档")
        archive_rid = request_id()
        archived = todo_service.batch_todos(
            self.repo,
            request_id=archive_rid,
            action="archive",
            items=[
                {"todo_id": first["todo_id"], "expected_version": 2},
                {"todo_id": second["todo_id"], "expected_version": 2},
            ],
        )
        self.assertEqual(archived["action"], "archive")
        self.assertEqual(len(archived["items"]), 2)
        self.assertTrue(all(item["archived_at"] for item in archived["items"]))
        self.assertEqual(
            [item["todo_id"] for item in todo_service.list_todos(self.repo)],
            [open_item["todo_id"]],
        )
        self.assertEqual(
            {item["todo_id"] for item in todo_service.list_todos(self.repo, archived=True)},
            {first["todo_id"], second["todo_id"]},
        )
        replay = todo_service.batch_todos(
            self.repo,
            request_id=archive_rid,
            action="archive",
            items=[
                {"todo_id": first["todo_id"], "expected_version": 2},
                {"todo_id": second["todo_id"], "expected_version": 2},
            ],
        )
        self.assertEqual(replay, archived)
        delete_rid = request_id()
        deleted = todo_service.batch_todos(
            self.repo,
            request_id=delete_rid,
            action="delete",
            items=[
                {"todo_id": first["todo_id"], "expected_version": 3},
                {"todo_id": second["todo_id"], "expected_version": 3},
            ],
        )
        self.assertTrue(deleted["deleted"])
        self.assertEqual(todo_service.list_todos(self.repo, archived=True), [])
        delete_replay = todo_service.batch_todos(
            self.repo,
            request_id=delete_rid,
            action="delete",
            items=[
                {"todo_id": first["todo_id"], "expected_version": 3},
                {"todo_id": second["todo_id"], "expected_version": 3},
            ],
        )
        self.assertEqual(delete_replay, deleted)
    def test_batch_validation_is_atomic(self):
        first = self.make("可归档")
        second = self.make("版本冲突")
        for current in (first, second):
            todo_service.update_todo(
                self.repo,
                todo_id=current["todo_id"],
                request_id=request_id(),
                expected_version=1,
                fields={"completed": True},
            )
        archive_rid = request_id()
        with self.assertRaises(domain.TodoVersionConflict):
            todo_service.batch_todos(
                self.repo,
                request_id=archive_rid,
                action="archive",
                items=[
                    {"todo_id": first["todo_id"], "expected_version": 2},
                    {"todo_id": second["todo_id"], "expected_version": 1},
                ],
            )
        self.assertIsNone(self.repo.todos[first["todo_id"]].get("archived_at"))
        self.assertIsNone(self.repo.todos[second["todo_id"]].get("archived_at"))
        self.assertNotIn(archive_rid, self.repo.operations)
        with self.assertRaises(domain.TodoInputError):
            todo_service.batch_todos(
                self.repo,
                request_id=request_id(),
                action="archive",
                items=[
                    {"todo_id": first["todo_id"], "expected_version": 2},
                    {"todo_id": first["todo_id"], "expected_version": 2},
                ],
            )
        open_item = self.make("未完成")
        with self.assertRaises(domain.TodoInputError):
            todo_service.batch_todos(
                self.repo,
                request_id=request_id(),
                action="archive",
                items=[{"todo_id": open_item["todo_id"], "expected_version": 1}],
            )
        self.assertIsNone(self.repo.todos[open_item["todo_id"]].get("archived_at"))
    def test_archived_todo_editable_but_cannot_reopen(self):
        created = self.make("归档后修改")
        todo_service.update_todo(
            self.repo,
            todo_id=created["todo_id"],
            request_id=request_id(),
            expected_version=1,
            fields={"completed": True},
        )
        todo_service.batch_todos(
            self.repo,
            request_id=request_id(),
            action="archive",
            items=[{"todo_id": created["todo_id"], "expected_version": 2}],
        )
        edited = todo_service.update_todo(
            self.repo,
            todo_id=created["todo_id"],
            request_id=request_id(),
            expected_version=3,
            fields={"title": "归档后新标题", "due_date": date.today()},
        )
        self.assertEqual(edited["title"], "归档后新标题")
        self.assertTrue(edited["archived_at"])
        self.assertTrue(edited["completed"])
        self.assertEqual(edited["version"], 4)
        with self.assertRaises(domain.TodoInputError):
            todo_service.update_todo(
                self.repo,
                todo_id=created["todo_id"],
                request_id=request_id(),
                expected_version=4,
                fields={"completed": False},
            )
        self.assertTrue(self.repo.todos[created["todo_id"]]["completed"])
        self.assertEqual(self.repo.todos[created["todo_id"]]["version"], 4)

    def test_old_update_receipt_survives_later_changes(self):
        created = self.make("v1")
        rid = request_id()
        first = todo_service.update_todo(
            self.repo,
            todo_id=created["todo_id"],
            request_id=rid,
            expected_version=1,
            fields={"title": "v2"},
        )
        todo_service.update_todo(
            self.repo,
            todo_id=created["todo_id"],
            request_id=request_id(),
            expected_version=2,
            fields={"title": "v3"},
        )
        replay = todo_service.update_todo(
            self.repo,
            todo_id=created["todo_id"],
            request_id=rid,
            expected_version=1,
            fields={"title": "v2"},
        )
        self.assertEqual(first, replay)
        self.assertEqual(replay["title"], "v2")
        self.assertEqual(self.repo.todos[created["todo_id"]]["title"], "v3")

    def test_commit_uncertain_keeps_dedicated_code_and_original_receipt(self):
        rid = request_id()
        self.repo.fail_commit = True
        with self.assertRaises(domain.TodoCommitUncertain) as caught:
            todo_service.create_todo(
                self.repo,
                request_id=rid,
                title="提交未决",
                due_date=None,
            )
        self.assertEqual(caught.exception.code, "TODO_COMMIT_UNCERTAIN")
        self.assertEqual(caught.exception.status_code, 503)
        receipt = todo_service.get_operation(self.repo, request_id=rid)
        self.assertEqual(receipt["todo"]["title"], "提交未决")
        self.repo.fail_commit = False
        replay = todo_service.create_todo(
            self.repo,
            request_id=rid,
            title="提交未决",
            due_date=None,
        )
        self.assertEqual(replay["title"], "提交未决")
        self.assertEqual(len(self.repo.todos), 1)

    def test_commit_and_rollback_failures_preserve_commit_uncertain(self):
        rid = request_id()
        self.repo.fail_commit = True
        self.repo.fail_rollback = True
        with self.assertRaises(domain.TodoCommitUncertain) as caught:
            self.make("提交和回滚都失败", rid=rid)
        self.assertEqual(caught.exception.code, "TODO_COMMIT_UNCERTAIN")
        self.assertEqual(caught.exception.status_code, 503)
        self.assertEqual(self.repo.rollback_calls, 1)
        receipt = todo_service.get_operation(self.repo, request_id=rid)
        self.assertEqual(receipt["todo"]["title"], "提交和回滚都失败")

        self.repo.fail_commit = False
        self.repo.fail_rollback = False
        replay = self.make("提交和回滚都失败", rid=rid)
        self.assertEqual(replay["title"], "提交和回滚都失败")
        self.assertEqual(len(self.repo.todos), 1)

    def test_update_and_delete_commit_uncertain_survive_rollback_failure(self):
        created = self.make("待修改")
        update_rid = request_id()
        self.repo.fail_commit = True
        self.repo.fail_rollback = True
        with self.assertRaises(domain.TodoCommitUncertain):
            todo_service.update_todo(
                self.repo,
                todo_id=created["todo_id"],
                request_id=update_rid,
                expected_version=1,
                fields={"title": "已修改"},
            )
        self.assertEqual(self.repo.rollback_calls, 1)
        update_receipt = todo_service.get_operation(
            self.repo, request_id=update_rid
        )
        self.assertEqual(update_receipt["todo"]["title"], "已修改")

        self.repo.fail_commit = False
        self.repo.fail_rollback = False
        doomed = self.make("待删除")
        delete_rid = request_id()
        self.repo.fail_commit = True
        self.repo.fail_rollback = True
        with self.assertRaises(domain.TodoCommitUncertain):
            todo_service.delete_todo(
                self.repo,
                todo_id=doomed["todo_id"],
                request_id=delete_rid,
                expected_version=1,
            )
        self.assertEqual(self.repo.rollback_calls, 2)
        delete_receipt = todo_service.get_operation(
            self.repo, request_id=delete_rid
        )
        self.assertTrue(delete_receipt["deleted"])

    def test_definite_failure_and_replay_survive_rollback_failure(self):
        rid = request_id()
        created = self.make("重放原请求", rid=rid)
        self.repo.fail_rollback = True
        replay = self.make("重放原请求", rid=rid)
        self.assertEqual(replay, created)
        self.assertEqual(self.repo.rollback_calls, 1)

        self.repo.fail_rollback = True
        with self.assertRaises(domain.TodoVersionConflict):
            todo_service.update_todo(
                self.repo,
                todo_id=created["todo_id"],
                request_id=request_id(),
                expected_version=99,
                fields={"title": "不应写入"},
            )
        self.assertEqual(self.repo.rollback_calls, 2)
        self.assertEqual(self.repo.todos[created["todo_id"]]["title"], "重放原请求")

    def test_operation_not_found_and_invalid_inputs(self):
        with self.assertRaises(domain.TodoOperationNotFound):
            todo_service.get_operation(self.repo, request_id=request_id())
        with self.assertRaises(domain.TodoInputError):
            self.make(" ")
        with self.assertRaises(domain.TodoInputError):
            self.make("超长标题" * 100)
        with self.assertRaises(domain.TodoInputError):
            self.make("日期", "2026-02-30")
        with self.assertRaises(domain.TodoInputError):
            todo_service.update_todo(
                self.repo,
                todo_id="missing",
                request_id=request_id(),
                expected_version=0,
                fields={"title": "x"},
            )

    def test_unarchive_restores_completed_item_and_replays_receipt(self):
        created = self.make("归档恢复")
        todo_service.update_todo(
            self.repo,
            todo_id=created["todo_id"],
            request_id=request_id(),
            expected_version=1,
            fields={"completed": True},
        )
        todo_service.batch_todos(
            self.repo,
            request_id=request_id(),
            action="archive",
            items=[{"todo_id": created["todo_id"], "expected_version": 2}],
        )
        rid = request_id()
        restored = todo_service.unarchive_todo(
            self.repo,
            todo_id=created["todo_id"],
            request_id=rid,
            expected_version=3,
        )
        self.assertTrue(restored["completed"])
        self.assertIsNone(restored["archived_at"])
        self.assertEqual(restored["version"], 4)
        self.assertEqual(
            [item["todo_id"] for item in todo_service.list_todos(self.repo)],
            [created["todo_id"]],
        )
        self.assertEqual(todo_service.list_todos(self.repo, archived=True), [])
        self.assertEqual(
            todo_service.get_operation(self.repo, request_id=rid)["todo"],
            restored,
        )
        replay = todo_service.unarchive_todo(
            self.repo,
            todo_id=created["todo_id"],
            request_id=rid,
            expected_version=3,
        )
        self.assertEqual(replay, restored)
        with self.assertRaises(domain.TodoVersionConflict):
            todo_service.unarchive_todo(
                self.repo,
                todo_id=created["todo_id"],
                request_id=request_id(),
                expected_version=3,
            )
        self.assertTrue(self.repo.todos[created["todo_id"]]["completed"])
        self.assertIsNone(self.repo.todos[created["todo_id"]]["archived_at"])

    def test_unarchive_rejects_active_item_and_keeps_commit_uncertain_receipt(self):
        active = self.make("活动待办")
        with self.assertRaises(domain.TodoInputError):
            todo_service.unarchive_todo(
                self.repo,
                todo_id=active["todo_id"],
                request_id=request_id(),
                expected_version=1,
            )
        todo_service.update_todo(
            self.repo,
            todo_id=active["todo_id"],
            request_id=request_id(),
            expected_version=1,
            fields={"completed": True},
        )
        todo_service.batch_todos(
            self.repo,
            request_id=request_id(),
            action="archive",
            items=[{"todo_id": active["todo_id"], "expected_version": 2}],
        )
        rid = request_id()
        self.repo.fail_commit = True
        with self.assertRaises(domain.TodoCommitUncertain):
            todo_service.unarchive_todo(
                self.repo,
                todo_id=active["todo_id"],
                request_id=rid,
                expected_version=3,
            )
        receipt = todo_service.get_operation(self.repo, request_id=rid)
        self.assertTrue(receipt["todo"]["completed"])
        self.assertIsNone(receipt["todo"]["archived_at"])
        self.repo.fail_commit = False
        replay = todo_service.unarchive_todo(
            self.repo,
            todo_id=active["todo_id"],
            request_id=rid,
            expected_version=3,
        )
        self.assertEqual(replay, receipt["todo"])

    def test_repository_row_projection_includes_archived_at(self):
        stamp = datetime(2026, 11, 1, 10, 0, 0)
        row = LocalTodo(
            id="todo-1",
            profile_id="profile-1",
            title="归档待办",
            due_date=None,
            completed=True,
            version=3,
            created_at=stamp,
            updated_at=stamp,
            archived_at=stamp,
        )
        projected = _row(row)
        self.assertEqual(projected["archived_at"], stamp)
        self.assertEqual(
            domain.todo_to_dict(projected)["archived_at"],
            stamp.isoformat(),
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
