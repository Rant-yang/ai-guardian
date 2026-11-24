"""Cheap service health; never infer client protection from server liveness."""


def snapshot(storage, semantic, revision, capacity=None):
    storage_ready=storage.get('status')=='ready'
    return {
        'service':'agent-guardian', 'api_version':1, 'health_schema_version':2,
        'status':'stopping' if (capacity or {}).get('draining') else 'ready' if storage_ready else 'degraded',
        'health_scope':'local_service_only',
        'rules':'ready', 'storage':storage,
        'backend_source_at_start':revision,
        'semantic':'experimental_scoped_pretool' if semantic.get('enabled') else 'not_in_pretool_path',
        'semantic_health':'not_probed',
        'model_review':'on_demand_local_advisory',
        'client_connected':'unknown',
        'verification':'not_inferred_from_service_health',
        'client_diagnostics_endpoint':'/api/overview',
        'checks':{
            'http':{'status':'responding',**(capacity or {})},
            'storage':{'status':storage.get('status','unknown'),'scope':'last_observed_storage_state'},
            'rules':{'status':'loaded','scope':'not_detection_accuracy'},
        },
        'limitations':['client_configuration_not_checked','client_execution_not_verified',
                       'model_availability_not_probed'],
    }
