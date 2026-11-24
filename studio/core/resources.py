"""Attach account/scope provenance to the existing resource ledger."""
import hashlib
import uuid


class ResourceLedger:
    def __init__(self, state, config):
        self.state, self.config = state, config

    def identity(self):
        keys = ('api_url', 'api_key', 'gateway_id', 'gateway_url')
        return hashlib.sha256('\0'.join(self.config.data[k] for k in keys).encode()).hexdigest()

    def record(self, kind, resource, scope='basic', run_id=None):
        self.stamp(resource, scope, run_id)
        self.state['sandboxes' if kind == 'sandbox' else 'templates'].append(resource)
        return resource

    def stamp(self, resource, scope, run_id=None):
        resource.setdefault('scope', scope)
        resource.setdefault('run_id', run_id or uuid.uuid4().hex[:12])
        resource.setdefault('account_fingerprint', self.identity())
        resource.setdefault('region', self.config.data['region'])
        resource.setdefault('gateway_id', self.config.data['gateway_id'])

    def assert_owned(self, kind, resource):
        rows = self.state['sandboxes' if kind == 'sandbox' else 'templates']
        if not resource or not resource.get('owned') or resource not in rows:
            raise RuntimeError('仅允许操作本工具记录的自有资源')
        if resource.get('account_fingerprint') not in (None, self.identity()):
            raise RuntimeError('资源属于其他账号或 Gateway，拒绝操作')
