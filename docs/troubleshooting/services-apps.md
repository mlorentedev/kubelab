---
id: "kubelab-troubleshooting-services-apps"
type: troubleshooting
status: active
tags: [troubleshooting, kubelab]
created: "2026-02-08"
owner: manu
---

# Self-Hosted Application Troubleshooting

Service-specific troubleshooting for self-hosted applications in KubeLab: N8N and Gitea.

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
