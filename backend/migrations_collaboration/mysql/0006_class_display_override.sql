-- Add an explicit, nullable class display-name override.
--
-- Target: MySQL 8.4.  Apply only after 0005 to the isolated collaboration
-- database.  The stable class ID, semantic class number, grade history and
-- memberships are unchanged; NULL keeps the existing promotion-derived name.
--
-- MySQL DDL auto-commits.  If any statement fails, STOP and record the first
-- failed statement plus objects already altered.

ALTER TABLE classes
    ADD COLUMN display_name_override VARCHAR(120) NULL AFTER display_name,
    ADD CONSTRAINT ck_classes_display_name_override
        CHECK (
            display_name_override IS NULL
            OR CHAR_LENGTH(display_name_override) BETWEEN 1 AND 120
        );