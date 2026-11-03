#!/usr/bin/env python3
"""Verify the outcome-blind structured external-factor source registry."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from fx_system.external_factor_eligibility import (
    ExternalFactorDefinitionCatalog,
    ExternalFactorSourceRegistry,
    audit_external_factor_definitions,
    audit_external_factor_sources,
    write_external_factor_source_audit,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--registry",
        type=Path,
        default=Path("configs/external_factor_source_registry.yaml"),
    )
    parser.add_argument(
        "--factor-catalog",
        type=Path,
        default=Path("configs/external_factor_definitions.yaml"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("outputs/external_factor_eligibility_20260719/source_audit.json"),
    )
    args = parser.parse_args()
    root = Path(__file__).parents[1]
    registry = ExternalFactorSourceRegistry.from_yaml(args.registry)
    audit = audit_external_factor_sources(registry, project_root=root)
    factor_catalog = ExternalFactorDefinitionCatalog.from_yaml(args.factor_catalog)
    audit["factor_dependency_audit"] = audit_external_factor_definitions(
        factor_catalog, audit
    )
    write_external_factor_source_audit(audit, args.output)
    print(json.dumps(audit, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
