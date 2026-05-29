---
id: "kubelab-troubleshooting-services-apps"
type: troubleshooting
status: active
tags: [troubleshooting, kubelab]
created: "2026-02-08"
owner: manu
---

# Self-Hosted Application Troubleshooting

Service-specific troubleshooting for self-hosted applications in KubeLab: Portainer, N8N, Gitea, and Vaultwarden.

## Portainer

### Cannot Access UI

#### Problem

Portainer web interface is unreachable.

#### Diagnostic Steps

```bash
# Check Portainer status
toolkit services logs portainer

# Verify port binding
docker ps | grep portainer
```

#### Solution

```bash
# Reset admin password (within first 5 minutes after start)
curl -X POST http://localhost:9000/api/users/admin/init \
  -H "Content-Type: application/json" \
  -d '{"Username":"admin","Password":"newpassword"}'
```

### Agent Disconnected

#### Problem

Portainer agent loses connection to the Portainer server.

#### Diagnostic Steps

```bash
# Check agent connection
docker logs portainer_agent

# Verify network connectivity
docker exec portainer ping portainer_agent
```

#### Solution

```bash
# Restart both agent and server
toolkit services restart portainer
```

#### Prevention

- Monitor agent connectivity in Portainer dashboard
- Ensure agent and server are on the same Docker network

## N8N

### Workflows Not Executing

#### Problem

N8N workflows fail to trigger or execute.

#### Diagnostic Steps

```bash
# Check N8N logs
toolkit apps logs n8n | grep error

# Verify webhook URLs
curl https://n8n.kubelab.live/webhook-test/

# Check execution queue
docker exec n8n n8n execute --id=workflow_id
```

#### Solution

- Review workflow error details in N8N UI
- Verify external service credentials are still valid
- Check webhook URL accessibility from outside the network

#### Prevention

- Set up workflow execution monitoring
- Use error handling nodes in critical workflows
- Test webhooks after each deployment

### Database Connection Issues

#### Problem

N8N cannot connect to its PostgreSQL database.

#### Diagnostic Steps

```bash
# Verify N8N_DB_TYPE setting
docker exec n8n env | grep N8N_DB

# Test database connectivity
docker exec n8n pg_isready -h postgres -U n8n

# Check migrations
docker exec n8n n8n db:migrate
```

#### Solution

- Verify database credentials in N8N environment variables
- Ensure PostgreSQL container is running and healthy
- Run pending migrations if N8N was updated

## Gitea

### Repository Push/Pull Failing

#### Problem

Git operations (push, pull, clone) fail against Gitea repositories.

#### Diagnostic Steps

```bash
# Check SSH key configuration
ssh -T git@gitea.kubelab.live

# Verify Git credentials
git config --list | grep credential

# Check Gitea SSH container
docker exec gitea /app/gitea/gitea admin auth list
```

#### Solution

- Re-add SSH keys in Gitea user settings
- Verify Git remote URL matches Gitea configuration
- Check Gitea container logs for authentication errors

#### Prevention

- Use SSH keys instead of HTTPS for Git operations
- Document SSH key setup in onboarding documentation

### LFS Issues

#### Problem

Git LFS operations fail or large files are not tracked.

#### Diagnostic Steps

```bash
# Verify LFS is enabled
docker exec gitea cat /data/gitea/conf/app.ini | grep LFS

# Check LFS storage
docker exec gitea du -sh /data/git/lfs
```

#### Solution

```bash
# Re-initialize LFS
git lfs install
git lfs fetch --all
```

#### Prevention

- Monitor LFS storage usage
- Set LFS size limits in Gitea configuration

## Vaultwarden

### Cannot Login

#### Problem

Unable to authenticate to the Vaultwarden web vault.

#### Diagnostic Steps

```bash
# Verify HTTPS (required for web vault)
curl -I https://vault.kubelab.live
```

#### Solution

```bash
# Check admin token
docker exec vaultwarden cat /data/config.json | grep admin_token

# Disable admin token temporarily
docker exec vaultwarden sed -i 's/"admin_token":.*/"admin_token": null,/' /data/config.json
toolkit services restart vaultwarden
```

#### Prevention

- Store Vaultwarden admin token securely
- Ensure HTTPS is always configured (required for WebCrypto API)

### Sync Issues

#### Problem

Bitwarden clients fail to sync with the Vaultwarden server.

#### Diagnostic Steps

```bash
# Check WebSocket connection
curl -I https://vault.kubelab.live/notifications/hub

# Verify Traefik WebSocket config
grep -A 5 "websocket" edge/traefik/templates/app-vaultwarden.template.yml
```

#### Solution

```bash
# Force resync from client
# Settings > Sync > Sync Vault Now
```

#### Prevention

- Ensure WebSocket support is configured in Traefik
- Monitor Vaultwarden container health
- Keep Vaultwarden updated for compatibility with Bitwarden clients
