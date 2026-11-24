"""Discover built-in packages; extensions register without editing Engine or UI."""
from dataclasses import asdict, dataclass, field
from importlib import import_module
from pkgutil import iter_modules
from threading import RLock
import re


@dataclass(frozen=True)
class Field:
    key: str
    label: str
    default: str = ''
    kind: str = 'text'
    help: str = ''
    choices: tuple = ()


@dataclass(frozen=True)
class DemoPackage:
    id: str
    title: str
    kind: str
    description: str
    cases: tuple
    prepare: object
    execute: object
    plan: object
    source: object
    fields: tuple = ()
    case_fields: dict = field(default_factory=dict)
    execution_cases: tuple = ()
    prerequisites: tuple = ()
    outcome: str = ''
    config_action: str = ''
    validate: object = None
    validate_config: object = None
    visualizer: str = ''
    recommended: bool = False
    view: object = None
    resource_state_keys: dict = field(default_factory=dict)

    def public(self):
        return dict(id=self.id, title=self.title, kind=self.kind,
                    description=self.description, prerequisites=list(self.prerequisites),
                    outcome=self.outcome, fields=[asdict(f) for f in self.fields],
                    config_action=self.config_action, visualizer=self.visualizer,recommended=self.recommended,
                    steps=[dict(id=c[0], title=c[1], description=c[3]) for c in self.cases])


class Registry:
    def __init__(self, packages):
        self.packages, self.actions, self.fields = {}, {}, {}
        for package in packages:
            if not re.fullmatch('[a-z][a-z0-9_]*', package.id):
                raise ValueError('Invalid package id: ' + package.id)
            if package.id in self.packages or package.kind not in ('capability', 'scenario'):
                raise ValueError('Duplicate package or invalid kind: ' + package.id)
            for hook in (package.prepare, package.execute, package.plan, package.source):
                if not callable(hook):
                    raise ValueError('Package hooks must be callable: ' + package.id)
            if package.view is not None and not callable(package.view):
                raise ValueError('Package view must be callable: ' + package.id)
            self.packages[package.id] = package
            local_fields = {f.key for f in package.fields}
            for f in package.fields:
                if f.kind not in ('text','url','number','secret','select'):
                    raise ValueError('Invalid field kind: ' + f.key)
                if f.kind == 'select':
                    values = [v[0] for v in f.choices if len(v)==2]
                    if len(values)!=len(f.choices) or len(set(values))!=len(values) or f.default not in values:
                        raise ValueError('Invalid field choices: ' + f.key)
                if (not re.fullmatch('[a-z][a-z0-9_]*', f.key) or f.key in
                        ('api_url','api_key','gateway_url','gateway_id','region','ready_template_id')):
                    raise ValueError('Reserved or invalid configuration field: ' + f.key)
                if f.kind == 'secret' and f.default:
                    raise ValueError('Secret defaults must be empty: ' + f.key)
                if f.key in self.fields:
                    raise ValueError('Duplicate configuration field: ' + f.key)
                self.fields[f.key] = f
            for row in package.cases:
                key, title, group, desc, prereq, expected = row
                if not re.fullmatch('[a-z][a-z0-9_]*', key):
                    raise ValueError('Invalid action id: ' + key)
                if key in self.actions:
                    raise ValueError('Duplicate action: ' + key)
                settings = tuple(package.case_fields.get(key, tuple(local_fields)))
                if not set(settings) <= local_fields:
                    raise ValueError('Unknown scoped fields: ' + key)
                self.actions[key] = dict(id=key, title=title, group=group, description=desc,
                    prerequisite=prereq, expected=expected, package=package.id,
                    kind=package.kind, settings=list(settings),
                    resource_state_key=package.resource_state_keys.get(key),
                    execution_params=key in package.execution_cases)
            if set(package.case_fields) - set(c[0] for c in package.cases):
                raise ValueError('Unknown case configuration scope: ' + package.id)
            if package.config_action and package.config_action not in {c[0] for c in package.cases}:
                raise ValueError('Unknown config action: ' + package.id)

    def package_for(self, action):
        return self.packages[self.actions[action]['package']]

    def scenarios(self):
        return [p.public() for p in self.packages.values() if p.kind == 'scenario']


_registry = None
_lock = RLock()


def get_registry():
    global _registry
    with _lock:
        if _registry is None:
            packages = []
            for root in ('studio.capabilities', 'studio.scenarios'):
                parent = import_module(root)
                for item in sorted(iter_modules(parent.__path__), key=lambda x: x.name):
                    if item.ispkg and not item.name.startswith('_'):
                        module = import_module(root + '.' + item.name)
                        if hasattr(module, 'DEFINITION'):
                            packages.append(module.DEFINITION)
            _registry = Registry(packages)
        return _registry
