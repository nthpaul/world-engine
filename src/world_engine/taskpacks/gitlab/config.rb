# Single-user local evaluation configuration, not a production deployment.
external_url ENV.fetch('WORLD_ENGINE_GITLAB_URL')
nginx['listen_port'] = 80
nginx['listen_https'] = false
puma['worker_processes'] = 0
puma['min_threads'] = 1
puma['max_threads'] = 2
sidekiq['concurrency'] = 5
prometheus_monitoring['enable'] = false
gitlab_rails['gitlab_signup_enabled'] = false
gitlab_rails['smtp_enable'] = false
gitlab_rails['usage_ping_enabled'] = false
gitlab_rails['gitlab_default_projects_features_builds'] = false
gitlab_rails['gitlab_default_projects_features_container_registry'] = false
registry['enable'] = false
gitlab_pages['enable'] = false
gitlab_kas['enable'] = false
letsencrypt['enable'] = false
gitlab_rails['env'] = {'MALLOC_CONF' => 'dirty_decay_ms:1000,muzzy_decay_ms:1000'}
