# Deployment Configuration

## Reverse Proxy

Two reverse proxy configurations are provided:

- **Caddyfile** — Recommended for new deployments. Simpler configuration with
  automatic TLS certificate management via Let's Encrypt.
  
- **nginx.conf** — For existing nginx setups. Requires manual TLS configuration
  and server block setup. Note: the nginx config references an external include
  file (`argus_server.conf`) that must be created separately.

Choose ONE proxy — do not run both simultaneously.
