"""Listening record/domain partial-save, ownership and receipt behaviour."""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import date

import pytest

from app.local import (
    config_service,
    listening_service,
    listening_templates,
    profile_service,
)
from app.local.models import LocalSettings
from app.local.normalize import normalize_initialization
from app.local.runtime import LocalRuntime
from tests.local.support import initialize_body


def _runtime(tmp_path, name="data") -> LocalRuntime:
    runtime = LocalRuntime(
        tmp_path / name, credential_root=tmp_path / (name + "-cred")
    )
    runtime.prepare()
    session = runtime.session()
    try:
        profile_service.initialize(
            session, normalize_initialization(**initialize_body())
        )
        session.commit()
    finally:
        session.close()
    return runtime


def _context(runtime: LocalRuntime):
    session = runtime.session()
    try:
        context = profile_service.require_context(session, date.today())
        return context.profile.id, context.terms[0].id
    finally:
        session.close()


def _create(runtime: LocalRuntime, name: str = "倾听幼儿", request_id=None):
    profile_id, term_id = _context(runtime)
    session = runtime.session()
    try:
        return listening_service.create_record(
            session,
            profile_id=profile_id,
            request_id=request_id or str(uuid.uuid4()),
            term_id=term_id,
            child_name=name,
        )
    finally:
        session.close()


def _read(runtime: LocalRuntime, record_id: str):
    profile_id, _term_id = _context(runtime)
    session = runtime.session()
    try:
        return listening_service.read_record(
            session, profile_id=profile_id, record_id=record_id
        )
    finally:
        session.close()


def test_create_generates_five_domains_three_groups_and_empty_stars(tmp_path) -> None:
    runtime = _runtime(tmp_path)
    try:
        profile_id, term_id = _context(runtime)
        create_request = str(uuid.uuid4())
        first = _create(runtime, "同名幼儿", request_id=create_request)
        second = _create(runtime, "同名幼儿")
        assert first["record_id"] != second["record_id"]
        assert first["revision"] == 1
        record = _read(runtime, first["record_id"])
        assert [domain["domain"] for domain in record["domains"]] == list(
            listening_service.DOMAINS
        )
        for domain in record["domains"]:
            assert domain["template_version"] == "v1"
            assert len(domain["groups"]) == 3
            assert [group["position"] for group in domain["groups"]] == [0, 1, 2]
            assert all(group["asset_id"] is None for group in domain["groups"])
            assert all(
                item["stars"] is None for item in domain["evaluation"]
            )
            assert all(
                group["work_date"] is None and group["listening_text"] is None
                for group in domain["groups"]
            )
        # The same request id returns the original receipt, not a new record.
        session = runtime.session()
        try:
            replay = listening_service.create_record(
                session,
                profile_id=profile_id,
                request_id=create_request,
                term_id=term_id,
                child_name="同名幼儿",
            )
            assert replay["record_id"] == first["record_id"]
            with pytest.raises(listening_service.ListeningRequestConflict):
                listening_service.create_record(
                    session,
                    profile_id=profile_id,
                    request_id=create_request,
                    term_id=term_id,
                    child_name="另一个名字",
                )
        finally:
            session.close()
        assert len(_list(runtime)) == 2
    finally:
        runtime.dispose()


def _list(runtime: LocalRuntime, **kwargs):
    profile_id, _term_id = _context(runtime)
    session = runtime.session()
    try:
        return listening_service.list_records(
            session, profile_id=profile_id, **kwargs
        )["items"]
    finally:
        session.close()


def test_partial_patch_preserves_omitted_fields_and_clears_explicit_null(tmp_path) -> None:
    runtime = _runtime(tmp_path)
    try:
        created = _create(runtime)
        profile_id, _term_id = _context(runtime)
        session = runtime.session()
        try:
            record = listening_service.read_record(
                session, profile_id=profile_id, record_id=created["record_id"]
            )
            health = record["domains"][0]
            group_id = health["groups"][0]["group_id"]
            request_id = str(uuid.uuid4())
            saved = listening_service.save_domain(
                session,
                profile_id=profile_id,
                record_id=created["record_id"],
                domain="health",
                request_id=request_id,
                expected_revision=record["revision"],
                patch={
                    "observation_date": "9月1日 上午",
                    "goal": "观察目标",
                    "overall_evaluation": "综合评价",
                    "evaluation": {"health_1": 2, "health_2": 3},
                    "groups": [
                        {
                            "group_id": group_id,
                            "work_date": "9月2日",
                            "listening_text": "孩子说：\n我想画太阳。",
                        }
                    ],
                },
            )
            assert saved["changed"] is True
            assert saved["revision"] == 2
            current = listening_service.read_record(
                session, profile_id=profile_id, record_id=created["record_id"]
            )
            health = current["domains"][0]
            assert health["observation_date"] == "9月1日 上午"
            assert health["goal"] == "观察目标"
            assert health["evaluation"][0]["stars"] == 2
            assert health["evaluation"][1]["stars"] == 3
            assert health["groups"][0]["work_date"] == "9月2日"
            assert health["groups"][0]["listening_text"] == "孩子说：\n我想画太阳。"
            # Omitted fields/stars and the other four domains stay unchanged.
            second = listening_service.save_domain(
                session,
                profile_id=profile_id,
                record_id=created["record_id"],
                domain="health",
                request_id=str(uuid.uuid4()),
                expected_revision=current["revision"],
                patch={"observation_area": "美工区"},
            )
            assert second["revision"] == 3
            current = listening_service.read_record(
                session, profile_id=profile_id, record_id=created["record_id"]
            )
            health = current["domains"][0]
            assert health["goal"] == "观察目标"
            assert health["evaluation"][0]["stars"] == 2
            assert health["groups"][0]["listening_text"] == "孩子说：\n我想画太阳。"
            other = current["domains"][1]
            assert other["goal"] is None
            assert all(item["stars"] is None for item in other["evaluation"])
            # Explicit null clears only the submitted fields.
            third = listening_service.save_domain(
                session,
                profile_id=profile_id,
                record_id=created["record_id"],
                domain="health",
                request_id=str(uuid.uuid4()),
                expected_revision=current["revision"],
                patch={
                    "observation_date": None,
                    "goal": None,
                    "evaluation": {"health_1": None},
                    "groups": [{"group_id": group_id, "listening_text": None}],
                },
            )
            assert third["revision"] == 4
            current = listening_service.read_record(
                session, profile_id=profile_id, record_id=created["record_id"]
            )
            health = current["domains"][0]
            assert health["observation_date"] is None
            assert health["goal"] is None
            assert health["evaluation"][0]["stars"] is None
            assert health["evaluation"][1]["stars"] == 3
            assert health["groups"][0]["listening_text"] is None
            # Explicit null for the whole evaluation map clears every star.
            fourth = listening_service.save_domain(
                session,
                profile_id=profile_id,
                record_id=created["record_id"],
                domain="health",
                request_id=str(uuid.uuid4()),
                expected_revision=current["revision"],
                patch={"evaluation": None},
            )
            assert fourth["revision"] == 5
            current = listening_service.read_record(
                session, profile_id=profile_id, record_id=created["record_id"]
            )
            assert all(
                item["stars"] is None
                for item in current["domains"][0]["evaluation"]
            )
        finally:
            session.close()
    finally:
        runtime.dispose()


def test_invalid_stars_unknown_items_and_bool_are_rejected_atomically(tmp_path) -> None:
    runtime = _runtime(tmp_path)
    try:
        created = _create(runtime)
        profile_id, _term_id = _context(runtime)
        session = runtime.session()
        try:
            record = listening_service.read_record(
                session, profile_id=profile_id, record_id=created["record_id"]
            )
            revision = record["revision"]
            for patch in (
                {"evaluation": {"health_1": 4}},
                {"evaluation": {"health_1": 0}},
                {"evaluation": {"health_1": True}},
                {"evaluation": {"health_1": "2"}},
                {"evaluation": {"health_unknown": 2}},
                {"evaluation": {"health_1": 4}, "goal": "不会保存"},
                {"unknown_field": "x"},
            ):
                with pytest.raises(listening_service.ListeningValidationError):
                    listening_service.save_domain(
                        session,
                        profile_id=profile_id,
                        record_id=created["record_id"],
                        domain="health",
                        request_id=str(uuid.uuid4()),
                        expected_revision=revision,
                        patch=patch,
                    )
                current = listening_service.read_record(
                    session, profile_id=profile_id, record_id=created["record_id"]
                )
                assert current["revision"] == revision
                assert current["domains"][0]["goal"] is None
                assert all(
                    item["stars"] is None
                    for item in current["domains"][0]["evaluation"]
                )
        finally:
            session.close()
    finally:
        runtime.dispose()


def test_revision_conflict_and_request_replay(tmp_path) -> None:
    runtime = _runtime(tmp_path)
    try:
        created = _create(runtime)
        profile_id, _term_id = _context(runtime)
        session = runtime.session()
        try:
            record = listening_service.read_record(
                session, profile_id=profile_id, record_id=created["record_id"]
            )
            request_id = str(uuid.uuid4())
            patch = {"goal": "第一次"}
            first = listening_service.save_domain(
                session,
                profile_id=profile_id,
                record_id=created["record_id"],
                domain="health",
                request_id=request_id,
                expected_revision=record["revision"],
                patch=patch,
            )
            assert first["revision"] == 2
            replay = listening_service.save_domain(
                session,
                profile_id=profile_id,
                record_id=created["record_id"],
                domain="health",
                request_id=request_id,
                expected_revision=record["revision"],
                patch=patch,
            )
            assert replay == first
            with pytest.raises(listening_service.ListeningRequestConflict):
                listening_service.save_domain(
                    session,
                    profile_id=profile_id,
                    record_id=created["record_id"],
                    domain="health",
                    request_id=request_id,
                    expected_revision=record["revision"],
                    patch={"goal": "不同内容"},
                )
            with pytest.raises(listening_service.ListeningRevisionConflict):
                listening_service.save_domain(
                    session,
                    profile_id=profile_id,
                    record_id=created["record_id"],
                    domain="health",
                    request_id=str(uuid.uuid4()),
                    expected_revision=record["revision"],
                    patch={"goal": "过期修订"},
                )
            current = listening_service.read_record(
                session, profile_id=profile_id, record_id=created["record_id"]
            )
            assert current["revision"] == 2
            assert current["domains"][0]["goal"] == "第一次"
        finally:
            session.close()
    finally:
        runtime.dispose()


def test_name_correction_is_shared_and_domains_do_not_copy_name(tmp_path) -> None:
    runtime = _runtime(tmp_path)
    try:
        first = _create(runtime, "旧名")
        second = _create(runtime, "旧名")
        profile_id, _term_id = _context(runtime)
        session = runtime.session()
        try:
            record = listening_service.read_record(
                session, profile_id=profile_id, record_id=first["record_id"]
            )
            request_id = str(uuid.uuid4())
            changed = listening_service.patch_record_name(
                session,
                profile_id=profile_id,
                record_id=first["record_id"],
                request_id=request_id,
                expected_revision=record["revision"],
                child_name="新名",
            )
            assert changed["changed"] is True
            assert changed["revision"] == 2
            again = listening_service.patch_record_name(
                session,
                profile_id=profile_id,
                record_id=first["record_id"],
                request_id=request_id,
                expected_revision=record["revision"],
                child_name="新名",
            )
            assert again == changed
            current = listening_service.read_record(
                session, profile_id=profile_id, record_id=first["record_id"]
            )
            assert current["child_name"] == "新名"
            assert all(domain["domain"] for domain in current["domains"])
            peer = listening_service.read_record(
                session, profile_id=profile_id, record_id=second["record_id"]
            )
            assert peer["child_name"] == "旧名"
            # A no-op rename keeps the revision stable.
            no_change = listening_service.patch_record_name(
                session,
                profile_id=profile_id,
                record_id=first["record_id"],
                request_id=str(uuid.uuid4()),
                expected_revision=current["revision"],
                child_name="新名",
            )
            assert no_change["changed"] is False
            assert no_change["revision"] == current["revision"]
        finally:
            session.close()
    finally:
        runtime.dispose()


def test_ownership_term_and_template_guards(tmp_path) -> None:
    runtime = _runtime(tmp_path)
    try:
        created = _create(runtime)
        profile_id, term_id = _context(runtime)
        session = runtime.session()
        try:
            with pytest.raises(listening_service.ListeningTermNotFound):
                listening_service.create_record(
                    session,
                    profile_id=profile_id,
                    request_id=str(uuid.uuid4()),
                    term_id="not-a-term",
                    child_name="无效学期",
                )
            with pytest.raises(listening_service.ListeningTermNotFound):
                listening_service.list_records(
                    session, profile_id=profile_id, term_id="not-a-term"
                )
            with pytest.raises(listening_service.ListeningNotFound):
                listening_service.read_record(
                    session,
                    profile_id="another-profile",
                    record_id=created["record_id"],
                )
            templates = listening_service.get_templates(
                session, profile_id=profile_id
            )
            assert len(templates["templates"]) == 5
            one = listening_service.get_templates(
                session, profile_id=profile_id, domain="health"
            )
            assert len(one["templates"]) == 1
            assert one["templates"][0]["version"] == "v1"
            with pytest.raises(listening_service.ListeningValidationError):
                listening_service.get_templates(
                    session, profile_id=profile_id, domain="unknown"
                )
            items = _list(runtime, term_id=term_id, child_name="倾听幼儿")
            assert len(items) == 1
        finally:
            session.close()
    finally:
        runtime.dispose()


def test_two_same_name_records_keep_five_domains_independent(tmp_path) -> None:
    runtime = _runtime(tmp_path)
    try:
        first = _create(runtime, "同名双人")
        second = _create(runtime, "同名双人")
        profile_id, _term_id = _context(runtime)
        session = runtime.session()
        try:
            current_first = listening_service.read_record(
                session, profile_id=profile_id, record_id=first["record_id"]
            )
            current_second = listening_service.read_record(
                session, profile_id=profile_id, record_id=second["record_id"]
            )
            for index, domain in enumerate(listening_service.DOMAINS):
                first_group = current_first["domains"][index]["groups"][0][
                    "group_id"
                ]
                second_group = current_second["domains"][index]["groups"][0][
                    "group_id"
                ]
                first_item = current_first["domains"][index]["evaluation"][0][
                    "item_id"
                ]
                second_item = current_second["domains"][index]["evaluation"][0][
                    "item_id"
                ]
                listening_service.save_domain(
                    session,
                    profile_id=profile_id,
                    record_id=first["record_id"],
                    domain=domain,
                    request_id=str(uuid.uuid4()),
                    expected_revision=current_first["revision"],
                    patch={
                        "goal": f"甲-{domain}",
                        "evaluation": {first_item: 1},
                        "groups": [
                            {
                                "group_id": first_group,
                                "listening_text": f"甲-{domain}正文",
                            }
                        ],
                    },
                )
                listening_service.save_domain(
                    session,
                    profile_id=profile_id,
                    record_id=second["record_id"],
                    domain=domain,
                    request_id=str(uuid.uuid4()),
                    expected_revision=current_second["revision"],
                    patch={
                        "goal": f"乙-{domain}",
                        "evaluation": {second_item: 3},
                        "groups": [
                            {
                                "group_id": second_group,
                                "listening_text": f"乙-{domain}正文",
                            }
                        ],
                    },
                )
                current_first = listening_service.read_record(
                    session, profile_id=profile_id, record_id=first["record_id"]
                )
                current_second = listening_service.read_record(
                    session, profile_id=profile_id, record_id=second["record_id"]
                )
            assert current_first["child_name"] == current_second["child_name"]
            assert current_first["revision"] == current_second["revision"] == 6
            for index, domain in enumerate(listening_service.DOMAINS):
                first_domain = current_first["domains"][index]
                second_domain = current_second["domains"][index]
                assert first_domain["goal"] == f"甲-{domain}"
                assert second_domain["goal"] == f"乙-{domain}"
                assert first_domain["evaluation"][0]["stars"] == 1
                assert second_domain["evaluation"][0]["stars"] == 3
                assert first_domain["groups"][0]["listening_text"] == (
                    f"甲-{domain}正文"
                )
                assert second_domain["groups"][0]["listening_text"] == (
                    f"乙-{domain}正文"
                )
        finally:
            session.close()
    finally:
        runtime.dispose()


def test_create_forged_receipt_record_is_not_replayed(tmp_path) -> None:
    runtime = _runtime(tmp_path)
    try:
        profile_id, term_id = _context(runtime)
        first_request = str(uuid.uuid4())
        second_request = str(uuid.uuid4())
        first = _create(
            runtime, "同名伪造", request_id=first_request
        )
        second = _create(
            runtime, "同名伪造", request_id=second_request
        )
        connection = sqlite3.connect(str(runtime.db_path))
        try:
            raw = connection.execute(
                "SELECT result_json FROM local_listening_operations "
                "WHERE request_id = ?",
                (first_request,),
            ).fetchone()[0]
            forged = json.loads(raw)
            forged["record_id"] = second["record_id"]
            connection.execute(
                "UPDATE local_listening_operations SET result_json = ? "
                "WHERE request_id = ?",
                (json.dumps(forged, ensure_ascii=False), first_request),
            )
            connection.commit()
        finally:
            connection.close()
        session = runtime.session()
        try:
            with pytest.raises(listening_service.ListeningRequestConflict):
                listening_service.create_record(
                    session,
                    profile_id=profile_id,
                    request_id=first_request,
                    term_id=term_id,
                    child_name="同名伪造",
                )
            with pytest.raises(listening_service.ListeningOperationNotFound):
                listening_service.read_operation_receipt(
                    session,
                    profile_id=profile_id,
                    request_id=first_request,
                )
            # Normal idempotent replay for the untouched peer still works.
            replay = listening_service.create_record(
                session,
                profile_id=profile_id,
                request_id=second_request,
                term_id=term_id,
                child_name="同名伪造",
            )
            assert replay["record_id"] == second["record_id"]
            listed = listening_service.list_records(
                session, profile_id=profile_id
            )
            assert listed["total"] == 2
            assert {item["record_id"] for item in listed["items"]} == {
                first["record_id"],
                second["record_id"],
            }
        finally:
            session.close()
    finally:
        runtime.dispose()


def test_grade_snapshot_survives_class_upgrade(tmp_path) -> None:
    runtime = _runtime(tmp_path)
    try:
        profile_id, term_id = _context(runtime)
        old = _create(runtime, "升班幼儿")
        old_before = _read(runtime, old["record_id"])
        assert old_before["grade"] == "middle"
        assert old_before["domains"][0]["template_sha256"] == (
            listening_templates.get_template("middle", "health").sha256
        )
        session = runtime.session()
        try:
            settings = session.get(LocalSettings, "singleton")
            context = profile_service.require_context(session, date.today())
            change = {
                "kind": "current_class",
                "name": context.school_class.name,
                "grade": "large",
            }
            preview = config_service.preview(
                session,
                expected_config_version=settings.config_version,
                change=change,
            )
            config_service.apply(
                session,
                request_id=str(uuid.uuid4()),
                expected_config_version=settings.config_version,
                change=change,
                preview_token=preview["preview_token"],
            )
        finally:
            session.close()
        old_after = _read(runtime, old["record_id"])
        assert old_after["grade"] == "middle"
        assert old_after["domains"][0]["template_sha256"] == (
            listening_templates.get_template("middle", "health").sha256
        )
        new = _create(runtime, "升班后新生")
        new_record = _read(runtime, new["record_id"])
        assert new_record["grade"] == "large"
        assert new_record["domains"][0]["template_sha256"] == (
            listening_templates.get_template("large", "health").sha256
        )
        # The old record remains saveable under its stored middle-grade
        # template even though the class is now large.
        session = runtime.session()
        try:
            saved = listening_service.save_domain(
                session,
                profile_id=profile_id,
                record_id=old["record_id"],
                domain="health",
                request_id=str(uuid.uuid4()),
                expected_revision=old_after["revision"],
                patch={"evaluation": {"health_1": 1}},
            )
            assert saved["changed"] is True
        finally:
            session.close()
    finally:
        runtime.dispose()


def test_record_bound_templates_use_stored_grade_and_version(tmp_path) -> None:
    runtime = _runtime(tmp_path)
    try:
        profile_id, _term_id = _context(runtime)
        old = _create(runtime, "绑定旧生")
        old_record = _read(runtime, old["record_id"])
        assert old_record["grade"] == "middle"
        session = runtime.session()
        try:
            listening_service.save_domain(
                session,
                profile_id=profile_id,
                record_id=old["record_id"],
                domain="health",
                request_id=str(uuid.uuid4()),
                expected_revision=old_record["revision"],
                patch={"evaluation": {"health_1": 2}},
            )
        finally:
            session.close()
        # Class maintenance: same class row moves from middle to large.
        session = runtime.session()
        try:
            settings = session.get(LocalSettings, "singleton")
            context = profile_service.require_context(session, date.today())
            change = {
                "kind": "current_class",
                "name": context.school_class.name,
                "grade": "large",
            }
            preview = config_service.preview(
                session,
                expected_config_version=settings.config_version,
                change=change,
            )
            config_service.apply(
                session,
                request_id=str(uuid.uuid4()),
                expected_config_version=settings.config_version,
                change=change,
                preview_token=preview["preview_token"],
            )
        finally:
            session.close()
        new = _create(runtime, "绑定新生")
        session = runtime.session()
        try:
            middle_health = listening_templates.get_template("middle", "health")
            large_health = listening_templates.get_template("large", "health")
            bound = listening_service.get_templates(
                session,
                profile_id=profile_id,
                domain="health",
                version="v1",
                record_id=old["record_id"],
            )
            assert bound["grade"] == "middle"
            assert bound["record_id"] == old["record_id"]
            assert bound["templates"][0]["sha256"] == middle_health.sha256
            assert bound["templates"][0]["items"] == middle_health.as_dict()["items"]
            five = listening_service.get_templates(
                session,
                profile_id=profile_id,
                record_id=old["record_id"],
            )
            assert five["grade"] == "middle"
            assert five["record_id"] == old["record_id"]
            assert [item["domain"] for item in five["templates"]] == list(
                listening_service.DOMAINS
            )
            assert all(item["grade"] == "middle" for item in five["templates"])
            assert [item["sha256"] for item in five["templates"]] == [
                listening_templates.get_template("middle", domain).sha256
                for domain in listening_service.DOMAINS
            ]
            new_bound = listening_service.get_templates(
                session,
                profile_id=profile_id,
                domain="health",
                record_id=new["record_id"],
            )
            assert new_bound["grade"] == "large"
            assert new_bound["record_id"] == new["record_id"]
            assert new_bound["templates"][0]["sha256"] == large_health.sha256
            current = listening_service.get_templates(
                session, profile_id=profile_id, domain="health"
            )
            assert current["grade"] == "large"
            assert "record_id" not in current
            assert current["templates"][0]["sha256"] == large_health.sha256
            current_all = listening_service.get_templates(
                session, profile_id=profile_id
            )
            assert current_all["grade"] == "large"
            assert len(current_all["templates"]) == 5
            assert all(
                item["sha256"]
                == listening_templates.get_template("large", item["domain"]).sha256
                for item in current_all["templates"]
            )
            with pytest.raises(listening_service.ListeningValidationError):
                listening_service.get_templates(
                    session,
                    profile_id=profile_id,
                    domain="health",
                    version="v0",
                    record_id=old["record_id"],
                )
            with pytest.raises(listening_service.ListeningValidationError):
                listening_service.get_templates(
                    session,
                    profile_id=profile_id,
                    version="v0",
                    record_id=old["record_id"],
                )
            with pytest.raises(listening_templates.ListeningTemplateNotFound):
                listening_service.get_templates(
                    session,
                    profile_id=profile_id,
                    domain="health",
                    version="v0",
                )
            with pytest.raises(listening_templates.ListeningTemplateNotFound):
                listening_service.get_templates(
                    session, profile_id=profile_id, version="v0"
                )
            with pytest.raises(listening_service.ListeningNotFound):
                listening_service.get_templates(
                    session,
                    profile_id=profile_id,
                    record_id="missing-record",
                )
            # read_record keeps its existing DTO shape and stored snapshot.
            restored = listening_service.read_record(
                session, profile_id=profile_id, record_id=old["record_id"]
            )
            assert restored["grade"] == "middle"
            assert (
                restored["domains"][0]["template_sha256"]
                == middle_health.sha256
            )
            assert restored["domains"][0]["evaluation"][0]["stars"] == 2
        finally:
            session.close()
    finally:
        runtime.dispose()
