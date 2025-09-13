# 2.3 Ansible - Deployment Automation

Automation and orchestration tools for deploying applications to production environments using Ansible playbooks and infrastructure as code.

## What it is

This Ansible setup handles all server configuration and application deployment for the mlorente.dev project. It configures servers from scratch, deploys Docker applications, manages secrets, and ensures consistent environments across staging and production. I use Ansible because it's agentless, uses simple YAML syntax, and makes deployments repeatable and reliable.

## Tech stack

- **Ansible 2.9+** - Configuration management and deployment automation
- **YAML playbooks** - Declarative infrastructure configuration
- **Jinja2 templates** - Dynamic configuration generation
- **SSH communication** - Agentless remote execution

## Project structure

```
infra/ansible/
├── README.md                    # This documentation
├── inventories/                 # Server inventories
│   ├── production/
│   │   ├── hosts.yml           # Production server list
│   │   └── group_vars/         # Production-specific variables
│   └── staging/
│       ├── hosts.yml           # Staging server list
│       └── group_vars/         # Staging variables
├── playbooks/                  # Ansible playbooks
│   ├── site.yml               # Main deployment playbook
│   ├── setup.yml              # Server initial setup
│   ├── deploy.yml             # Application deployment
│   ├── backup.yml             # Backup procedures
│   └── rollback.yml           # Rollback procedures
├── roles/                      # Reusable Ansible roles
│   ├── docker/                # Docker installation
│   ├── nginx/                 # Nginx configuration
│   ├── app-deploy/            # Application deployment
│   └── monitoring/            # Monitoring setup
├── templates/                  # Configuration templates
│   ├── docker-compose.j2      # Dynamic compose files
│   ├── nginx.conf.j2         # Nginx configuration
│   └── traefik.yml.j2        # Traefik configuration
├── vars/                       # Variable files
│   ├── secrets.yml           # Encrypted secrets (Ansible Vault)
│   └── common.yml            # Common variables
└── ansible.cfg               # Ansible configuration
```

## Key features

### Server management
- **Initial setup** - Complete server configuration from Ubuntu base
- **Docker installation** - Automated Docker and Docker Compose setup
- **User management** - Deploy user creation and SSH key management
- **Security hardening** - Basic firewall and security configurations

### Application deployment
- **Docker deployment** - Deploy applications using Docker Compose
- **Environment management** - Stage-specific variable handling
- **Health checks** - Verify deployments after completion
- **Rollback capability** - Quick rollback to previous versions

### Configuration management
- **Template rendering** - Dynamic configuration generation
- **Secret management** - Encrypted secrets with Ansible Vault
- **Variable hierarchy** - Environment-specific overrides
- **Idempotent operations** - Safe to run multiple times

## Configuration

### Ansible configuration (ansible.cfg)

```ini
[defaults]
host_key_checking = False
inventory = inventories/production/hosts.yml
remote_user = mlorente-deployer
private_key_file = ~/.ssh/mlorente-deploy
stdout_callback = yaml
timeout = 30

[ssh_connection]
ssh_args = -o ControlMaster=auto -o ControlPersist=60s
pipelining = True
control_path = /tmp/ansible-ssh-%%h-%%p-%%r
```

### Production inventory (inventories/production/hosts.yml)

```yaml
all:
  children:
    web_servers:
      hosts:
        mlorente-prod-01:
          ansible_host: 1.2.3.4
          ansible_user: mlorente-deployer
          server_role: primary
          
    monitoring:
      hosts:
        mlorente-monitoring:
          ansible_host: 5.6.7.8
          ansible_user: mlorente-deployer
          server_role: monitoring

  vars:
    environment: production
    domain: mlorente.dev
    docker_network: proxy
    backup_enabled: true
    monitoring_enabled: true
```

### Group variables (inventories/production/group_vars/all.yml)

```yaml
# Environment settings
environment: production
domain: mlorente.dev
backup_retention_days: 30

# Application settings
apps:
  - name: api
    port: 8080
    replicas: 1
    env_file: api.env
  - name: web
    port: 4321
    replicas: 1
    env_file: web.env
  - name: blog
    port: 4000
    replicas: 1
    env_file: blog.env
  - name: wiki
    port: 8000
    replicas: 1
    env_file: wiki.env

# Docker settings
docker_compose_version: "2.24.0"
docker_network: proxy
docker_data_path: /opt/mlorente-dev

# Backup settings
backup_enabled: true
backup_path: /opt/backups
backup_retention_days: 30

# Monitoring
monitoring_enabled: true
log_level: info
```

## Playbooks

### Main deployment playbook (playbooks/site.yml)

```yaml
---
- name: Deploy mlorente.dev applications
  hosts: web_servers
  become: yes
  gather_facts: yes
  
  pre_tasks:
    - name: Update package cache
      apt:
        update_cache: yes
        cache_valid_time: 300
      tags: ['setup']

  roles:
    - { role: docker, tags: ['docker', 'setup'] }
    - { role: app-deploy, tags: ['deploy'] }
    - { role: monitoring, tags: ['monitoring'], when: monitoring_enabled }

  post_tasks:
    - name: Verify services are running
      uri:
        url: "http://localhost:{{ item.port }}/health"
        method: GET
        status_code: 200
      with_items: "{{ apps }}"
      tags: ['verify']

    - name: Create deployment log
      lineinfile:
        path: /var/log/deployments.log
        line: "{{ ansible_date_time.iso8601 }} - Deployed {{ apps | length }} applications"
        create: yes
      tags: ['logging']
```

### Server setup playbook (playbooks/setup.yml)

```yaml
---
- name: Initial server setup
  hosts: web_servers
  become: yes
  gather_facts: yes

  tasks:
    - name: Create deploy user
      user:
        name: "{{ ansible_user }}"
        groups: docker,sudo
        shell: /bin/bash
        create_home: yes
      tags: ['users']

    - name: Setup SSH keys
      authorized_key:
        user: "{{ ansible_user }}"
        key: "{{ item }}"
        state: present
      with_items: "{{ ssh_public_keys }}"
      tags: ['ssh']

    - name: Configure sudo without password
      lineinfile:
        path: /etc/sudoers.d/{{ ansible_user }}
        line: "{{ ansible_user }} ALL=(ALL) NOPASSWD:ALL"
        create: yes
        mode: '0440'
      tags: ['sudo']

    - name: Install required packages
      apt:
        name:
          - docker.io
          - docker-compose
          - git
          - curl
          - htop
          - vim
          - ufw
        state: present
        update_cache: yes
      tags: ['packages']

    - name: Configure firewall
      ufw:
        rule: allow
        port: "{{ item }}"
        proto: tcp
      with_items:
        - 22    # SSH
        - 80    # HTTP
        - 443   # HTTPS
      tags: ['firewall']

    - name: Enable firewall
      ufw:
        state: enabled
        policy: deny
      tags: ['firewall']
```

## Roles

### Application deployment role (roles/app-deploy/tasks/main.yml)

```yaml
---
- name: Create application directories
  file:
    path: "{{ docker_data_path }}/{{ item.name }}"
    state: directory
    owner: "{{ ansible_user }}"
    group: docker
    mode: '0755'
  with_items: "{{ apps }}"

- name: Generate docker-compose files
  template:
    src: docker-compose.j2
    dest: "{{ docker_data_path }}/{{ item.name }}/docker-compose.yml"
    owner: "{{ ansible_user }}"
    group: docker
    mode: '0644'
  with_items: "{{ apps }}"
  register: compose_files

- name: Generate environment files
  template:
    src: "{{ item.env_file }}.j2"
    dest: "{{ docker_data_path }}/{{ item.name }}/.env"
    owner: "{{ ansible_user }}"
    group: docker
    mode: '0600'
  with_items: "{{ apps }}"
  register: env_files

- name: Pull latest images
  docker_compose:
    project_src: "{{ docker_data_path }}/{{ item.name }}"
    pull: yes
  with_items: "{{ apps }}"

- name: Deploy applications
  docker_compose:
    project_src: "{{ docker_data_path }}/{{ item.name }}"
    state: present
    restarted: "{{ compose_files.changed or env_files.changed }}"
  with_items: "{{ apps }}"
```

### Docker role (roles/docker/tasks/main.yml)

```yaml
---
- name: Install Docker dependencies
  apt:
    name:
      - apt-transport-https
      - ca-certificates
      - curl
      - gnupg
      - lsb-release
    state: present

- name: Add Docker GPG key
  apt_key:
    url: https://download.docker.com/linux/ubuntu/gpg
    state: present

- name: Add Docker repository
  apt_repository:
    repo: "deb [arch=amd64] https://download.docker.com/linux/ubuntu {{ ansible_distribution_release }} stable"
    state: present

- name: Install Docker
  apt:
    name:
      - docker-ce
      - docker-ce-cli
      - containerd.io
    state: present
    update_cache: yes

- name: Start and enable Docker
  systemd:
    name: docker
    state: started
    enabled: yes

- name: Add user to docker group
  user:
    name: "{{ ansible_user }}"
    groups: docker
    append: yes

- name: Install Docker Compose
  pip:
    name: docker-compose
    version: "{{ docker_compose_version }}"
    state: present
```

## Deployment

### Development/staging deployment

```bash
# Setup staging server
ansible-playbook -i inventories/staging/hosts.yml playbooks/setup.yml

# Deploy applications to staging
ansible-playbook -i inventories/staging/hosts.yml playbooks/site.yml

# Check deployment status
ansible-playbook -i inventories/staging/hosts.yml playbooks/site.yml --tags verify
```

### Production deployment

```bash
# Deploy to production with confirmation
ansible-playbook -i inventories/production/hosts.yml playbooks/site.yml --check

# Execute deployment
ansible-playbook -i inventories/production/hosts.yml playbooks/site.yml

# Verify deployment
ansible-playbook -i inventories/production/hosts.yml playbooks/site.yml --tags verify
```

### Rollback deployment

```yaml
# playbooks/rollback.yml
---
- name: Rollback to previous version
  hosts: web_servers
  become: yes
  vars_prompt:
    - name: rollback_version
      prompt: "Enter version to rollback to"
      private: no

  tasks:
    - name: Stop current services
      docker_compose:
        project_src: "{{ docker_data_path }}/{{ item.name }}"
        state: absent
      with_items: "{{ apps }}"

    - name: Restore previous configuration
      copy:
        src: "{{ backup_path }}/{{ rollback_version }}/{{ item.name }}/"
        dest: "{{ docker_data_path }}/{{ item.name }}/"
        remote_src: yes
      with_items: "{{ apps }}"

    - name: Start services with previous version
      docker_compose:
        project_src: "{{ docker_data_path }}/{{ item.name }}"
        state: present
      with_items: "{{ apps }}"
```

## Secret management

### Using Ansible Vault

```bash
# Create encrypted secrets file
ansible-vault create vars/secrets.yml

# Edit encrypted secrets
ansible-vault edit vars/secrets.yml

# View encrypted secrets
ansible-vault view vars/secrets.yml

# Deploy with vault password
ansible-playbook site.yml --ask-vault-pass

# Use vault password file
ansible-playbook site.yml --vault-password-file ~/.ansible-vault-pass
```

### Sample secrets file (vars/secrets.yml)

```yaml
$ANSIBLE_VAULT;1.1;AES256
encrypted_content_here_that_contains:
  database_password: super_secure_password
  api_secret_key: very_long_random_string
  ssl_private_key: |
    -----BEGIN PRIVATE KEY-----
    encrypted_private_key_content
    -----END PRIVATE KEY-----
```

## Monitoring and maintenance

### Health checks

```bash
# Check all services
ansible web_servers -m uri -a "url=http://localhost:8080/health"

# Check specific application
ansible web_servers -m docker_container -a "name=api state=started"

# System status
ansible web_servers -m setup -a "filter=ansible_mounts"
```

### Backup operations

```bash
# Create backup before deployment
ansible-playbook playbooks/backup.yml

# Restore from backup
ansible-playbook playbooks/backup.yml --tags restore -e backup_date=2024-01-15
```

### Log collection

```bash
# Collect application logs
ansible web_servers -m fetch -a "src=/opt/mlorente-dev/logs/ dest=./logs/"

# View recent deployment logs
ansible web_servers -m shell -a "tail -n 50 /var/log/deployments.log"
```

## Troubleshooting

### Common deployment issues

**Connection failures:**
```bash
# Test SSH connectivity
ansible all -m ping

# Check SSH configuration
ssh -v mlorente-deployer@server-ip
```

**Docker issues:**
```bash
# Check Docker daemon
ansible web_servers -m service -a "name=docker state=started"

# Verify Docker permissions
ansible web_servers -m shell -a "docker ps"
```

**Application failures:**
```bash
# Check application logs
ansible web_servers -m shell -a "docker logs api"

# Restart specific service
ansible web_servers -m shell -a "cd /opt/mlorente-dev/api && docker-compose restart"
```

### Debug commands

```bash
# Run playbook in check mode
ansible-playbook site.yml --check --diff

# Run with verbose output
ansible-playbook site.yml -vvv

# Run specific tags only
ansible-playbook site.yml --tags "docker,deploy"

# Limit to specific hosts
ansible-playbook site.yml --limit "mlorente-prod-01"
```

## Best practices

### Security
- **SSH keys only** - Never use password authentication
- **Vault secrets** - Always encrypt sensitive variables
- **Limited sudo** - Only grant necessary privileges
- **Firewall rules** - Restrict access to required ports only

### Deployment
- **Check mode first** - Always run with --check before deployment
- **Backup before deploy** - Create backups before major changes
- **Incremental deployment** - Deploy to staging first
- **Health verification** - Always verify deployment success

### Maintenance
- **Regular updates** - Keep Ansible and dependencies updated
- **Documentation** - Document custom variables and procedures
- **Version control** - Track all playbook changes in git
- **Testing** - Test playbooks in staging environment

## Local development

For local testing and development:

```bash
# Install Ansible locally
pip install ansible

# Lint playbooks
ansible-lint playbooks/site.yml

# Test on local VM
vagrant up
ansible-playbook -i inventories/vagrant/hosts.yml playbooks/site.yml
```