-- 0009: administrator entity deletion (2026-11-26).
--
-- Schools, classes and teachers gain a nullable deleted_at timestamp.  A
-- delete request with history/associations deactivates the entity: the row
-- keeps its stable id and every referencing row, deleted_at is set and all
-- admin/teacher-facing lists filter it out.  Teachers additionally get
-- active=0 and their bearer tokens revoked, so a deactivated teacher can no
-- longer log in or act.  An entity without any referencing row is deleted
-- outright.  Existing rows are untouched (NULL = present).

ALTER TABLE schools
    ADD COLUMN deleted_at DATETIME(6) NULL AFTER created_at;

ALTER TABLE classes
    ADD COLUMN deleted_at DATETIME(6) NULL AFTER created_at;

ALTER TABLE teachers
    ADD COLUMN deleted_at DATETIME(6) NULL AFTER created_at;
