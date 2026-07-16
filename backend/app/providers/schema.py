"""把阶段八规范 Schema 投影为供应商支持的确定性子集。"""

import hashlib
import json
from copy import deepcopy
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.domain.grading import canonical_json_bytes

ProviderSchemaDialect = Literal["openai", "anthropic", "gemini"]
_PYDANTIC_ONLY_KEYS = {"decimal_places", "max_digits"}
_GEMINI_UNSUPPORTED_KEYS = {
    "pattern",
    "minLength",
    "maxLength",
    "minItems",
    "maxItems",
}


class CompiledProviderSchema(BaseModel):
    """实际发送给供应商的 Schema 与其审计哈希。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    dialect: ProviderSchemaDialect
    schema_body: dict[str, object]
    canonical_json: bytes = Field(min_length=2, max_length=1_000_000, repr=False)
    sha256: bytes = Field(min_length=32, max_length=32)


def _resolve_reference(reference: str, definitions: dict[str, object]) -> object:
    prefix = "#/$defs/"
    if not reference.startswith(prefix):
        raise ValueError("结果 Schema 只能引用本地 $defs")
    name = reference.removeprefix(prefix)
    if not name or "/" in name or name not in definitions:
        raise ValueError("结果 Schema 包含无效本地引用")
    return deepcopy(definitions[name])


def _project_node(
    value: object,
    *,
    dialect: ProviderSchemaDialect,
    definitions: dict[str, object],
    reference_stack: tuple[str, ...] = (),
) -> object:
    if isinstance(value, list):
        return [
            _project_node(
                item,
                dialect=dialect,
                definitions=definitions,
                reference_stack=reference_stack,
            )
            for item in value
        ]
    if not isinstance(value, dict):
        return value
    if "$ref" in value:
        reference = value["$ref"]
        if not isinstance(reference, str) or reference in reference_stack:
            raise ValueError("结果 Schema 包含无效或递归引用")
        resolved = _resolve_reference(reference, definitions)
        return _project_node(
            resolved,
            dialect=dialect,
            definitions=definitions,
            reference_stack=(*reference_stack, reference),
        )

    projected: dict[str, object] = {}
    for key, item in value.items():
        if key == "$defs" or key in _PYDANTIC_ONLY_KEYS:
            continue
        if dialect == "gemini" and key in _GEMINI_UNSUPPORTED_KEYS:
            continue
        if key == "const":
            projected["enum"] = [
                _project_node(
                    item,
                    dialect=dialect,
                    definitions=definitions,
                    reference_stack=reference_stack,
                )
            ]
            continue
        projected[key] = _project_node(
            item,
            dialect=dialect,
            definitions=definitions,
            reference_stack=reference_stack,
        )

    properties = projected.get("properties")
    if isinstance(properties, dict) and dialect in {"openai", "anthropic"}:
        projected["required"] = list(properties)
        projected["additionalProperties"] = False
    return projected


def compile_provider_schema(
    canonical_schema_json: bytes,
    *,
    dialect: ProviderSchemaDialect,
) -> CompiledProviderSchema:
    """严格解析、解引用并按固定方言生成唯一 JSON。"""

    try:
        decoded = json.loads(canonical_schema_json)
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise ValueError("结果 Schema 不是有效 UTF-8 JSON") from error
    if not isinstance(decoded, dict):
        raise ValueError("结果 Schema 根节点必须是对象")
    raw_definitions = decoded.get("$defs", {})
    if not isinstance(raw_definitions, dict):
        raise ValueError("结果 Schema 的 $defs 必须是对象")
    definitions = {str(key): value for key, value in raw_definitions.items()}
    projected = _project_node(decoded, dialect=dialect, definitions=definitions)
    if not isinstance(projected, dict):
        raise ValueError("结果 Schema 投影失败")
    compiled_json = canonical_json_bytes(projected)
    return CompiledProviderSchema(
        dialect=dialect,
        schema_body=projected,
        canonical_json=compiled_json,
        sha256=hashlib.sha256(compiled_json).digest(),
    )
