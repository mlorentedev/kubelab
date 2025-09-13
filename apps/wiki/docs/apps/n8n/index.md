# 1.7 n8n - Workflow Automation

Powerful workflow automation platform for connecting services, APIs, and databases with a visual node-based editor. Automates routine tasks and integrates different systems seamlessly.

## What it is

n8n handles all the automation workflows for the mlorente.dev ecosystem. It connects different services together, automates deployments, monitors system health, and sends notifications. I use it because it's self-hosted, has a great visual interface, and can integrate with virtually any API or service.

## Tech stack

- **n8n** - Self-hosted workflow automation platform
- **Node.js** - JavaScript runtime for custom functions
- **PostgreSQL** - Database for workflow storage (optional)
- **Docker** - Containerized deployment

## Key features

### Visual workflow editor
- **Node-based interface** - Drag and drop workflow creation
- **Pre-built integrations** - 200+ service connectors
- **Custom code** - JavaScript functions for complex logic
- **Conditional branching** - Logic-based workflow paths

### Automation capabilities
- **API integration** - Connect any REST/GraphQL API
- **Database operations** - Query and update databases
- **File processing** - Handle files and data transformation
- **Scheduled execution** - Cron-based workflow triggers

### Monitoring and debugging
- **Execution history** - Track all workflow runs
- **Error handling** - Catch and handle failures
- **Live debugging** - Step-through workflow execution
- **Performance metrics** - Monitor execution times

## Configuration

### Docker Compose setup

```yaml
services:
  n8n:
    image: n8nio/n8n:latest
    container_name: n8n
    restart: unless-stopped
    ports:
      - "5678:5678"
    environment:
      - N8N_BASIC_AUTH_ACTIVE=true
      - N8N_BASIC_AUTH_USER=${N8N_USER}
      - N8N_BASIC_AUTH_PASSWORD=${N8N_PASSWORD}
      - N8N_HOST=n8n.mlorente.dev
      - N8N_PROTOCOL=https
      - N8N_PORT=5678
      - WEBHOOK_URL=https://n8n.mlorente.dev/
    volumes:
      - n8n_data:/home/node/.n8n
    networks:
      - proxy
    labels:
      - "traefik.enable=true"
      - "traefik.http.routers.n8n.rule=Host(`n8n.mlorente.dev`)"
      - "traefik.http.routers.n8n.entrypoints=websecure"
      - "traefik.http.routers.n8n.tls=true"
      - "traefik.http.routers.n8n.tls.certresolver=letsencrypt"
      - "traefik.http.services.n8n.loadbalancer.server.port=5678"

volumes:
  n8n_data:

networks:
  proxy:
    external: true
```

## Running n8n

### Development setup

```bash
# Start n8n
make up-n8n

# Access web interface
open http://n8n.mlorentedev.test

# Login with configured credentials
```

### Environment variables

```bash
# n8n configuration
N8N_USER=admin
N8N_PASSWORD=secure_password_here
N8N_ENCRYPTION_KEY=your_encryption_key
N8N_HOST=n8n.mlorente.dev
N8N_PROTOCOL=https
```

## Common workflows

### Deployment notification workflow

```json
{
  "nodes": [
    {
      "name": "Webhook Trigger",
      "type": "n8n-nodes-base.webhook",
      "parameters": {
        "path": "deploy-notification",
        "httpMethod": "POST"
      }
    },
    {
      "name": "Parse Deployment Data",
      "type": "n8n-nodes-base.function",
      "parameters": {
        "functionCode": "const data = items[0].json;\nreturn [{\n  json: {\n    service: data.service,\n    version: data.version,\n    status: data.status,\n    timestamp: new Date().toISOString()\n  }\n}];"
      }
    },
    {
      "name": "Send Slack Notification",
      "type": "n8n-nodes-base.slack",
      "parameters": {
        "channel": "#deployments",
        "text": "🚀 Deployment completed: {{$json['service']}} v{{$json['version']}}"
      }
    }
  ]
}
```

### Health monitoring workflow

```json
{
  "nodes": [
    {
      "name": "Schedule",
      "type": "n8n-nodes-base.cron",
      "parameters": {
        "rule": {
          "minute": "*/5"
        }
      }
    },
    {
      "name": "Check API Health",
      "type": "n8n-nodes-base.httpRequest",
      "parameters": {
        "url": "https://api.mlorente.dev/health",
        "method": "GET"
      }
    },
    {
      "name": "Check Response",
      "type": "n8n-nodes-base.if",
      "parameters": {
        "conditions": {
          "string": [
            {
              "value1": "={{$json['status']}}",
              "operation": "notEqual",
              "value2": "200"
            }
          ]
        }
      }
    },
    {
      "name": "Send Alert",
      "type": "n8n-nodes-base.emailSend",
      "parameters": {
        "to": "admin@mlorente.dev",
        "subject": "🚨 API Health Check Failed",
        "text": "The API health check failed. Please investigate."
      }
    }
  ]
}
```

## Local development URLs

When running locally with `make up-n8n`:
- **n8n Interface**: http://n8n.mlorentedev.test
- **Direct access**: http://localhost:5678
- **Webhook base**: http://n8n.mlorentedev.test/webhook/

Add `127.0.0.1 n8n.mlorentedev.test` to your `/etc/hosts` file.

## Best practices

- **Workflow organization** - Use clear naming and folder structure
- **Error handling** - Add error nodes to handle failures gracefully
- **Testing** - Test workflows thoroughly before production use
- **Documentation** - Document complex workflows and their purpose
- **Security** - Never expose sensitive data in workflow configurations
- **Monitoring** - Set up alerts for critical workflow failures

n8n provides powerful automation capabilities that help reduce manual work and improve system reliability through automated processes and integrations.