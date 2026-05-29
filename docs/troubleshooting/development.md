---
id: "kubelab-troubleshooting-development"
type: troubleshooting
status: active
tags: [troubleshooting, kubelab]
created: "2026-02-08"
owner: manu
---

# Development Environment Issues

Problems specific to the KubeLab local development workflow.

## Hot Reload Not Working

### Problem

File changes are not detected and the development server does not reload.

### Diagnostic Steps

```bash
# Check inotify watch limit
cat /proc/sys/fs/inotify/max_user_watches
```

### Solution

```bash
# Increase file watching limits
echo fs.inotify.max_user_watches=524288 | sudo tee -a /etc/sysctl.conf
sudo sysctl -p

# Restart dev server
make web-dev
```

### Prevention

- Set inotify limits system-wide during dev machine setup
- Document this in onboarding checklist

## Port Already In Use

### Problem

Development server cannot bind to its configured port.

### Diagnostic Steps

```bash
# Find process using port
lsof -i :3000
```

### Solution

```bash
# Kill the process
kill -9 <PID>

# Or change port in docker-compose.dev.yml
```

### Prevention

- Use distinct port ranges for each service in development
- Add port conflict checks to the `make dev` target

## Local DNS for Development

### Problem

Development services are not reachable by hostname.

### Diagnostic Steps

```bash
# Check /etc/hosts
cat /etc/hosts | grep localhost
```

### Solution

```bash
# Add local development hostnames
echo "127.0.0.1 api.localhost web.localhost blog.localhost" | sudo tee -a /etc/hosts
```

### Prevention

- Use `.localhost` domains for development to avoid conflicts with production
- Document all required `/etc/hosts` entries in project setup guide
