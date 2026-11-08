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

    def list_todos(self):
        return [copy.deepcopy(row) for row in self.todos.values()]

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
            "todo_id", "title", "due_date", "completed", "version",
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


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
