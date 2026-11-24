"""Record our adapter operations without modifying the upstream SDK."""
from functools import wraps
from time import perf_counter


def serializable(value):
    if isinstance(value, dict): return {str(k): serializable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)): return [serializable(v) for v in value]
    if isinstance(value, str): return value
    if isinstance(value, bytes): return {'bytes': len(value), 'content_omitted': True}
    if value is None or isinstance(value, (bool, int, float)): return value
    if hasattr(value, 'pid'): return {'pid': value.pid}
    return {'type': type(value).__name__}


def recorded(function):
    @wraps(function)
    def call(self, *args, **kwargs):
        recorder = getattr(self, 'recorder', None)
        if recorder is None:
            return function(self, *args, **kwargs)
        started = perf_counter()
        name = function.__name__
        # File payloads are not copied into exported telemetry.
        inputs = {'args': list(args[:2] if name not in ('read', 'write') else args[:1]),
                  'kwargs': {k: v for k, v in kwargs.items() if k not in ('value', 'data')}}
        if name in ('write', 'read') and len(args) > 1:
            inputs['path'] = args[1]
        if name=='build_template_async':
            inputs={'build_options_omitted':True}
        if name=='create_sandbox' and 'envs' in inputs['kwargs']:
            inputs['kwargs']['envs']={'values_omitted':True}
        event = {'layer': 'sdk_adapter', 'operation': name, 'input': inputs}
        try:
            result = function(self, *args, **kwargs)
            event.update(status='passed', result=({'content_omitted': True} if name in ('read', 'write') else result))
            return result
        except Exception as exc:
            event.update(status='failed', error=type(exc).__name__+': '+str(exc))
            details = {k: getattr(exc, k) for k in ('stdout','stderr','exit_code') if hasattr(exc,k)}
            if details: event['error_details'] = details
            raise
        finally:
            event['elapsed_s'] = perf_counter()-started
            try:
                recorder(serializable(event))
            except Exception as exc:
                # Telemetry cannot hide an already-created resource from its caller.
                self.recording_error = type(exc).__name__+': '+str(exc)
    return call
