"""阶段 2 数据库结构契约测试。"""

from typing import cast

from sqlalchemy import CheckConstraint, ForeignKeyConstraint, Index, UniqueConstraint, Uuid
from sqlalchemy.dialects.postgresql.asyncpg import PGDialect_asyncpg
from sqlalchemy.engine.interfaces import Dialect

from app.domain.models import Base


def constraint_names(
    table_name: str,
    kind: type[CheckConstraint] | type[UniqueConstraint],
) -> set[str]:
    """返回指定表中某类具名约束。"""

    table = Base.metadata.tables[table_name]
    return {
        str(constraint.name)
        for constraint in table.constraints
        if isinstance(constraint, kind) and constraint.name is not None
    }


def index_names(table_name: str) -> set[str]:
    """返回指定表的索引名称。"""

    table = Base.metadata.tables[table_name]
    return {
        str(index.name)
        for index in table.indexes
        if isinstance(index, Index) and index.name is not None
    }


def foreign_key_shapes(table_name: str) -> set[tuple[tuple[str, ...], tuple[str, ...]]]:
    """返回复合外键的本地列和目标列。"""

    table = Base.metadata.tables[table_name]
    return {
        (
            tuple(element.parent.name for element in constraint.elements),
            tuple(element.target_fullname for element in constraint.elements),
        )
        for constraint in table.constraints
        if isinstance(constraint, ForeignKeyConstraint)
    }


def indexed_column_prefixes(table_name: str) -> set[tuple[str, ...]]:
    """返回主键、唯一约束和普通索引可用的列前缀。"""

    table = Base.metadata.tables[table_name]
    sequences: set[tuple[str, ...]] = {tuple(column.name for column in table.primary_key.columns)}
    sequences.update(
        tuple(column.name for column in constraint.columns)
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint)
    )
    sequences.update(
        tuple(column.name for column in index.columns) for index in table.indexes if index.columns
    )
    return {sequence[:length] for sequence in sequences for length in range(1, len(sequence) + 1)}


def test_account_and_provider_schema_enforces_administration_rules() -> None:
    profiles = Base.metadata.tables["profiles"]
    providers = Base.metadata.tables["provider_configs"]

    assert isinstance(profiles.c.id.type, Uuid)
    assert {"profiles_role_check", "profiles_status_check"} <= constraint_names(
        "profiles", CheckConstraint
    )
    assert "profiles_single_admin_idx" in index_names("profiles")
    assert (("id",), ("auth.users.id",)) in foreign_key_shapes("profiles")

    assert isinstance(providers.c.id.type, Uuid)
    assert providers.c.name.unique is True
    assert {
        "provider_configs_provider_type_check",
        "provider_configs_status_check",
        "provider_configs_limits_check",
        "provider_configs_enabled_check",
        "provider_configs_test_version_check",
        "provider_configs_default_model_check",
    } <= constraint_names("provider_configs", CheckConstraint)
    assert providers.c.config_version.nullable is False
    assert providers.c.tested_config_version.nullable is True


def test_assignment_content_schema_prevents_cross_teacher_links() -> None:
    for table_name in ("assignments", "rubric_versions", "submissions"):
        table = Base.metadata.tables[table_name]
        assert isinstance(table.c.id.type, Uuid)
        assert table.c.owner_id.nullable is False
        assert (("owner_id",), ("profiles.id",)) in foreign_key_shapes(table_name)
        assert f"{table_name}_owner_status_created_idx" in index_names(table_name)

    assert {
        "assignments_instructions_check",
        "assignments_status_check",
        "assignments_title_check",
    } <= constraint_names("assignments", CheckConstraint)
    assert {
        (("assignment_id", "owner_id"), ("assignments.id", "assignments.owner_id"))
    } <= foreign_key_shapes("rubric_versions")
    assert {(("provider_config_id",), ("provider_configs.id",))} <= foreign_key_shapes(
        "rubric_versions"
    )
    assert {
        "rubric_versions_status_check",
        "rubric_versions_score_range_check",
        "rubric_versions_confirmation_check",
        "rubric_versions_structured_rubric_check",
        "rubric_versions_version_check",
        "rubric_versions_generation_check",
        "rubric_versions_content_check",
    } <= constraint_names("rubric_versions", CheckConstraint)
    assert "rubric_versions_assignment_id_version_key" in constraint_names(
        "rubric_versions", UniqueConstraint
    )
    assert {
        "rubric_versions_provider_config_id_idx",
        "rubric_versions_one_draft_idx",
        "rubric_versions_one_confirmed_idx",
    } <= index_names("rubric_versions")
    rubric_versions = Base.metadata.tables["rubric_versions"]
    assert rubric_versions.c.provider_config_id.nullable is True
    assert rubric_versions.c.model.nullable is True

    assert {
        (("assignment_id", "owner_id"), ("assignments.id", "assignments.owner_id"))
    } <= foreign_key_shapes("submissions")
    assert {
        "submissions_status_check",
        "submissions_media_type_check",
        "submissions_file_check",
        "submissions_original_filename_check",
        "submissions_state_check",
        "submissions_object_keys_check",
    } <= constraint_names("submissions", CheckConstraint)
    assert "submissions_assignment_id_content_sha256_key" in constraint_names(
        "submissions", UniqueConstraint
    )
    assert "submissions_source_object_key_key" in constraint_names("submissions", UniqueConstraint)
    assert "submissions_extracted_object_key_idx" in index_names("submissions")


def test_grading_pipeline_schema_is_versioned_and_auditable() -> None:
    assert {table.name for table in Base.metadata.tables.values() if table.schema is None} == {
        "profiles",
        "provider_configs",
        "assignments",
        "rubric_versions",
        "submissions",
        "grading_jobs",
        "grading_job_items",
        "grading_attempts",
        "teacher_reviews",
        "audit_logs",
        "exports",
    }

    for table_name in (
        "grading_jobs",
        "grading_job_items",
        "grading_attempts",
        "teacher_reviews",
        "exports",
    ):
        table = Base.metadata.tables[table_name]
        assert isinstance(table.c.id.type, Uuid)
        assert table.c.owner_id.nullable is False
        assert f"{table_name}_owner_status_created_idx" in index_names(table_name)

    assert {
        (
            ("rubric_version_id", "assignment_id", "owner_id"),
            (
                "rubric_versions.id",
                "rubric_versions.assignment_id",
                "rubric_versions.owner_id",
            ),
        )
    } <= foreign_key_shapes("grading_jobs")
    assert "grading_jobs_owner_id_idempotency_key_key" in constraint_names(
        "grading_jobs", UniqueConstraint
    )
    assert "grading_jobs_model_parameters_check" in constraint_names(
        "grading_jobs", CheckConstraint
    )
    grading_jobs = Base.metadata.tables["grading_jobs"]
    assert {
        "result_schema_version",
        "result_schema_hash",
        "rubric_hash",
    } <= set(grading_jobs.c.keys())
    assert all(
        grading_jobs.c[column_name].nullable is False
        for column_name in (
            "result_schema_version",
            "result_schema_hash",
            "rubric_hash",
        )
    )

    assert {
        (
            ("grading_job_id", "assignment_id", "owner_id"),
            ("grading_jobs.id", "grading_jobs.assignment_id", "grading_jobs.owner_id"),
        ),
        (
            ("submission_id", "assignment_id", "owner_id"),
            ("submissions.id", "submissions.assignment_id", "submissions.owner_id"),
        ),
    } <= foreign_key_shapes("grading_job_items")

    assert {
        "grading_attempts_score_range_check",
        "grading_attempts_result_check",
        "grading_attempts_attempt_number_check",
        "grading_attempts_criteria_results_check",
    } <= constraint_names("grading_attempts", CheckConstraint)
    assert {
        "grading_attempts_grading_job_item_id_attempt_number_key",
        "grading_attempts_owner_id_idempotency_key_key",
    } <= constraint_names("grading_attempts", UniqueConstraint)
    grading_attempts = Base.metadata.tables["grading_attempts"]
    assert "request_version" in grading_attempts.c
    assert grading_attempts.c.request_version.nullable is False

    assert {
        "teacher_reviews_score_range_check",
        "teacher_reviews_confirmation_check",
        "teacher_reviews_revision_number_check",
        "teacher_reviews_json_shapes_check",
    } <= constraint_names("teacher_reviews", CheckConstraint)
    assert "teacher_reviews_one_confirmed_idx" in index_names("teacher_reviews")

    assert {
        "audit_logs_owner_created_idx",
        "audit_logs_actor_created_idx",
        "audit_logs_resource_created_idx",
    } <= index_names("audit_logs")
    assert "audit_logs_metadata_check" in constraint_names("audit_logs", CheckConstraint)
    assert "exports_owner_id_idempotency_key_key" in constraint_names("exports", UniqueConstraint)
    assert "exports_audit_metadata_check" in constraint_names("exports", CheckConstraint)


def test_nullable_jsonb_fields_bind_python_none_as_sql_null() -> None:
    """可空 JSONB 字段不得把 Python None 写成 JSON null。"""

    dialect = cast(type[Dialect], PGDialect_asyncpg)()
    for table_name, column_name in (
        ("rubric_versions", "structured_rubric"),
        ("grading_attempts", "criteria_results"),
        ("teacher_reviews", "criteria_results"),
    ):
        column_type = Base.metadata.tables[table_name].c[column_name].type
        processor = column_type.bind_processor(dialect)
        bound_value = processor(None) if processor is not None else None

        assert bound_value is None, f"{table_name}.{column_name} 必须绑定为 SQL NULL"


def test_every_foreign_key_has_a_matching_leftmost_index() -> None:
    for table in Base.metadata.tables.values():
        if table.schema is not None:
            continue
        indexed_prefixes = indexed_column_prefixes(table.name)
        for constraint in table.constraints:
            if not isinstance(constraint, ForeignKeyConstraint):
                continue
            local_columns = tuple(element.parent.name for element in constraint.elements)
            assert local_columns in indexed_prefixes, (
                f"{table.name} 的外键 {local_columns} 缺少同顺序索引"
            )
