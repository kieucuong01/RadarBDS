from __future__ import annotations

import pytest

from scripts.radar_ask_vector_migration import (
    ALLOWED_MODEL_DIMENSIONS,
    VECTOR_CONTRACT_VERSION,
    build_readiness_function_sql,
    build_semantic_function_sql,
    validate_dimension,
    validate_model_id,
)


def test_only_benchmarked_candidates_and_exact_dimensions_are_accepted():
    for model_id, dimension in ALLOWED_MODEL_DIMENSIONS.items():
        assert validate_model_id(model_id) == model_id
        assert validate_dimension(model_id, dimension) == dimension

    with pytest.raises(ValueError, match="approved"):
        validate_model_id("arbitrary/remote-model")
    with pytest.raises(ValueError, match="dimension"):
        validate_dimension("intfloat/multilingual-e5-small", 1024)


def test_semantic_function_is_bounded_and_security_definer_safe():
    sql = " ".join(build_semantic_function_sql().lower().split())

    assert "security definer" in sql
    assert "set search_path=pg_catalog,public" in sql
    assert "least(greatest(coalesce(max_rows, 1), 1), 10)" in sql
    assert "where c.embedding is not null" in sql
    assert "expected_model_id" in sql
    assert "phone" not in sql
    assert "description" not in sql


def test_readiness_function_exposes_exact_contract_version():
    sql = " ".join(build_readiness_function_sql().lower().split())

    assert "contract_version" in sql
    assert VECTOR_CONTRACT_VERSION == "radar-ask-vector-v1"
