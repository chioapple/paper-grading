"""把供应商连接测试绑定到当前配置版本。

Revision ID: 20260715_0007
Revises: 20260715_0006
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260715_0007"
down_revision: str | None = "20260715_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "provider_configs",
        sa.Column("config_version", sa.BigInteger(), server_default=sa.text("'1'"), nullable=False),
    )
    op.add_column(
        "provider_configs",
        sa.Column("tested_config_version", sa.BigInteger(), nullable=True),
    )
    op.execute(
        "UPDATE public.provider_configs "
        "SET status = 'draft', tested_at = NULL "
        "WHERE status = 'enabled' OR tested_at IS NOT NULL"
    )

    op.drop_constraint(
        op.f("provider_configs_enabled_check"),
        "provider_configs",
        type_="check",
    )
    op.drop_constraint(
        op.f("provider_configs_key_material_check"),
        "provider_configs",
        type_="check",
    )
    op.create_check_constraint(
        op.f("provider_configs_enabled_check"),
        "provider_configs",
        "status <> 'enabled' or (tested_at is not null and encrypted_api_key is not null "
        "and default_model is not null and tested_config_version = config_version)",
    )
    op.create_check_constraint(
        op.f("provider_configs_key_material_check"),
        "provider_configs",
        "(encrypted_api_key is null and api_key_nonce is null) or "
        "(encrypted_api_key is not null and api_key_nonce is not null "
        "and octet_length(api_key_nonce) = 12 and octet_length(encrypted_api_key) >= 17)",
    )
    op.create_check_constraint(
        op.f("provider_configs_test_version_check"),
        "provider_configs",
        "config_version > 0 and (tested_config_version is null or tested_config_version > 0) "
        "and ((tested_at is null) = (tested_config_version is null))",
    )
    op.create_check_constraint(
        op.f("provider_configs_text_check"),
        "provider_configs",
        "btrim(name) <> '' and btrim(base_url) <> ''",
    )
    op.create_check_constraint(
        op.f("provider_configs_default_model_check"),
        "provider_configs",
        "default_model is null or (btrim(default_model) <> '' "
        "and allowed_models @> jsonb_build_array(default_model))",
    )

    op.execute(
        """
        CREATE FUNCTION public.paper_grading_invalidate_provider_test()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = ''
        AS $$
        BEGIN
            IF ROW(
                NEW.provider_type,
                NEW.base_url,
                NEW.encrypted_api_key,
                NEW.api_key_nonce,
                NEW.allowed_models,
                NEW.default_model,
                NEW.timeout_seconds
            ) IS DISTINCT FROM ROW(
                OLD.provider_type,
                OLD.base_url,
                OLD.encrypted_api_key,
                OLD.api_key_nonce,
                OLD.allowed_models,
                OLD.default_model,
                OLD.timeout_seconds
            ) THEN
                NEW.config_version := OLD.config_version + 1;
                NEW.tested_at := NULL;
                NEW.tested_config_version := NULL;
                NEW.status := 'draft';
            ELSE
                NEW.config_version := OLD.config_version;
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        REVOKE EXECUTE ON FUNCTION public.paper_grading_invalidate_provider_test() FROM PUBLIC
        """
    )
    op.execute(
        """
        DO $$
        DECLARE role_name text;
        BEGIN
            FOREACH role_name IN ARRAY ARRAY['anon', 'authenticated', 'service_role']
            LOOP
                IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = role_name) THEN
                    EXECUTE format(
                        'REVOKE EXECUTE ON FUNCTION '
                        'public.paper_grading_invalidate_provider_test() FROM %I',
                        role_name
                    );
                END IF;
            END LOOP;
        END
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER provider_configs_invalidate_test
        BEFORE UPDATE ON public.provider_configs
        FOR EACH ROW
        EXECUTE FUNCTION public.paper_grading_invalidate_provider_test()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS provider_configs_invalidate_test ON public.provider_configs")
    op.execute("DROP FUNCTION IF EXISTS public.paper_grading_invalidate_provider_test()")
    op.drop_constraint(
        op.f("provider_configs_default_model_check"),
        "provider_configs",
        type_="check",
    )
    op.drop_constraint(
        op.f("provider_configs_text_check"),
        "provider_configs",
        type_="check",
    )
    op.drop_constraint(
        op.f("provider_configs_test_version_check"),
        "provider_configs",
        type_="check",
    )
    op.drop_constraint(
        op.f("provider_configs_key_material_check"),
        "provider_configs",
        type_="check",
    )
    op.drop_constraint(
        op.f("provider_configs_enabled_check"),
        "provider_configs",
        type_="check",
    )
    op.create_check_constraint(
        op.f("provider_configs_key_material_check"),
        "provider_configs",
        "(encrypted_api_key is null) = (api_key_nonce is null)",
    )
    op.create_check_constraint(
        op.f("provider_configs_enabled_check"),
        "provider_configs",
        "status <> 'enabled' or (tested_at is not null and encrypted_api_key is not null "
        "and default_model is not null)",
    )
    op.drop_column("provider_configs", "tested_config_version")
    op.drop_column("provider_configs", "config_version")
