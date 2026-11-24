"""Compatibility facade for the shared package registry."""
from .core.registry import get_registry

REGISTRY=get_registry()
CATALOG=REGISTRY.actions
CASES=[(r['id'],r['title'],r['group'],r['description'],r['prerequisite'],r['expected']) for r in CATALOG.values()]
EXECUTION_CASES={key for key,row in CATALOG.items() if row['execution_params']}
SCENARIO_FIELDS={key:set(row['settings']) for key,row in CATALOG.items() if row['settings']}
