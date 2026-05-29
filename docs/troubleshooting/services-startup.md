---
id: "kubelab-troubleshooting-services-startup"
type: troubleshooting
status: active
tags: [troubleshooting, kubelab]
created: "2026-02-08"
owner: manu
---

# Services Startup Issues

Problems preventing KubeLab services from starting.

## Docker Daemon Not Running

### Problem

Services fail to start because the Docker daemon is not running.

### Diagnostic Steps

```bash
# Check Docker daemon status
sudo systemctl status docker
```

### Solution

```bash
sudo systemctl start docker
```

### Prevention

- Enable Docker to start on boot: `sudo systemctl enable docker`
- Monitor Docker daemon health in your system monitoring

## Port Conflicts

### Problem

Services cannot bind to their expected ports because another process is using them.

### Diagnostic Steps

```bash
# Check what's using a specific port
sudo netstat -tulpn | grep :<PORT>

# Common ports to check
sudo netstat -tulpn | grep :80
sudo netstat -tulpn | grep :443
```

### Solution

```bash
# Stop conflicting services
sudo systemctl stop nginx apache2
```

### Prevention

- Document all port assignments in infrastructure configuration
- Use non-standard ports in development to avoid conflicts with system services

## Permission Issues

### Problem

Docker commands fail with permission errors.

### Diagnostic Steps

```bash
# Check current user groups
groups $USER

# Check file ownership
ls -la .
```

### Solution

```bash
# Fix file ownership
sudo chown -R $USER:$USER .

# Add user to docker group
sudo usermod -aG docker $USER
# Logout and login again for group changes to take effect
```

### Prevention

- Always add developers to the `docker` group during onboarding
- Use consistent file ownership in project directories
