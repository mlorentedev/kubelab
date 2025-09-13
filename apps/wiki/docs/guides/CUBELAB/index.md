# CubeLab

This repository contains the configuration and documentation for a cubelab designed to emulate a cloud environment, using low-cost hardware and optimized software. The goal is to create a testing environment for cloud services, with a focus on energy efficiency and resource usage.

## Hardware

The total cost of the cubelab is approximately $700 USD, including power adapters, cables, and storage. The hardware configuration is detailed below:

| Device                | Storage | CPU/GPU                                   | Price |
|-------------------------|----------------|-------------------------------------------|--------|
| MiniPC Acemagic         | 256GB SSD       | 12th Alder Lake N100 Intel 12GB-LPDDR4 | $150   |
| Raspberry Pi 4-B       | 32GB SD        | 64-bit Quad-Core ARM A72 8GB-LPDDR4     | $100   |
| Jetson Nano P3450      | 64GB SD        | 64-bit Quad-core 128-Core GPU ARM A57 4GB-LPDDR4 | $200   |
| Jetson Nano P3450      | 128GB SD       | 64-bit Quad-core 128-Core GPU ARM A57 4GB-LPDDR4 | $200   |
| TP-Link TLSD10059      | 5 ports        | 1GigE                                     | $25    |

This cubelab consists of an ACEMAGICIAN MiniPC, a Raspberry Pi 4-B, and two Jetson Nano P3450 devices, connected through a TP-Link TLSD10059 switch. The MiniPC acts as the master node and control plane, the Raspberry Pi serves as the gateway and edge node, while the Jetson Nano devices function as worker nodes.

The estimated energy consumption for the cubelab is approximately 64.8 kWh per month, which equals an approximate cost of $13 USD, considering a price of $0.2 USD per kWh. This assumes continuous usage 24 hours a day, 7 days a week.

| Device                | Consumption (W)    | Monthly consumption (kWh) | Monthly cost (USD) |
|-------------------------|----------------|------------------------|---------------------|
| MiniPC Acemagic         | 30W            | 21.6 kWh               | $4.32               |
| Raspberry Pi 4-B       | 15W            | 10.8 kWh               | $2.16               |
| Jetson Nano P3450      | 20W            | 14.4 kWh               | $2.88              |
| Jetson Nano P3450      | 20W            | 14.4 kWh               | $2.88               |
| TP-Link TLSD10059      | 5W             | 3.6 kWh                | $0.72               |
| **Total**              |                | **64.8 kWh**           | **$12.96**           |

## Software
  
| Device                | Storage | Role/Function                     | Software                                      |
|-------------------------|----------------|----------------------------------|-----------------------------------------------|
| MiniPC Acemagician     | 256GB SSD       | Control Plane/Kubernetes Master  | Ubuntu Server 20.04 LTS (x86_64) + k3s      |
| Raspberry Pi 4-B       | 32GB SD        | API Gateway/Edge Node           | OpenWrt (ARM64)       |
| Raspberry Pi 3       | 32GB SD        | NAT bridge          | Raspberry Pi OS Lite (ARM64)       |
| Jetson Nano P3450      | 64GB SD        | Multi-purpose Worker Node      | Ubuntu Server 20.04 LTS (ARM64) + K3s Worker |
| Jetson Nano P3450      | 128GB SD       | Ollama Server      | JetPack 4.6.1 (Ubuntu 18.04) |

## Purposes and Services for Each Node

### MiniPC ACEMAGICIAN - Main Control Plane

The ACEMAGICIAN MiniPC acts as the brain of the CubeLab, leveraging its higher processing power, RAM, and SSD storage to run:

- **Kubernetes Control Plane**:
  - Complete K3s Control Plane (API Server, Scheduler, Controller Manager, etcd)
  - Centralized cluster policy and security management
  - Intelligent workload scheduling

- **Monitoring and Observability**:
  - Prometheus-Grafana-Alertmanager-Loki stack
  - Centralized metrics and logs storage
  - Custom dashboards for cluster status visualization

- **Primary Storage**:
  - PostgreSQL for relational databases
  - MinIO for S3 service emulation
  - Longhorn for persistent volume management

- **CI/CD and Application Management**:
  - Private container registry
  - Integration pipelines with Tekton/Jenkins X
  - ArgoCD and Helm for GitOps deployments

- **Enterprise Cloud Services Emulation**:
  - AWS: EKS, RDS, CloudWatch
  - Azure: AKS, SQL Database, Azure Monitor
  - GCP: GKE, Cloud SQL, Cloud Monitoring

### Raspberry Pi 4-B - Gateway and Edge Processing

The Raspberry Pi 4-B functions as the cluster entry point and edge processor:

- **API Gateway and Routing**:
  - Kong/Traefik for traffic management, load balancing, and transformation
  - Rate limiting and circuit breaking policies
  - API traffic logging and analysis

- **Security and Identity Management**:
  - Keycloak for centralized authentication/authorization
  - OAuth2/OpenID Connect
  - Single Sign-On for cluster applications

- **Administration Portal**:
  - Unified web interface for environment management
  - Centralized dashboard with role-based views
  - Console for application deployment and management

- **Edge Computing and Networking**:
  - Edge Functions for local processing
  - CDN-like distributed cache
  - Simulated geolocation-based routing

- **Cloud Edge Services Emulation**:
  - AWS: API Gateway, CloudFront, IoT Edge
  - Azure: API Management, Front Door, IoT Edge
  - GCP: Apigee, Cloud CDN, Edge TPU

### Jetson Nano #1 - GPU Computing and Data Analysis

The first Jetson Nano specializes in workloads that leverage its GPU:

- **GPU Computing and Hardware Acceleration**:
  - AI/ML model inference with GPU acceleration
  - Computer vision processing
  - Multimedia transcoding

- **Machine Learning Platforms**:
  - TensorFlow, PyTorch, and ONNX Runtime
  - Jupyter for experimentation
  - MLflow and Kubeflow for ML workflows

- **Data and Image Processing**:
  - Real-time processing pipelines
  - Image analysis and object detection APIs
  - OCR and embedding generation

- **Cloud AI Services Emulation**:
  - AWS: SageMaker, Rekognition, Comprehend
  - Azure: Cognitive Services, Computer Vision
  - GCP: Vertex AI, Vision AI, Natural Language

### Jetson Nano #2 - Serverless Services and NoSQL Data

The second Jetson Nano is configured as a specialist in serverless services and NoSQL databases:

- **Serverless Infrastructure**:
  - OpenFaaS/Kubeless for FaaS emulation
  - Lambda-compatible environments
  - Event-based triggers

- **NoSQL Databases**:
  - MongoDB for JSON documents
  - Redis for cache and in-memory structures
  - Cassandra/ScyllaDB for time series

- **Messaging and Event Systems**:
  - RabbitMQ/NATS for asynchronous communication
  - Queue and pub/sub system implementation
  - Kafka-like event flows

- **Microservices and Containers**:
  - Reference applications based on microservices
  - API Gateway, Circuit Breaker, Bulkhead patterns
  - Service Mesh with Linkerd

- **Serverless Cloud Services Emulation**:
  - AWS: Lambda, DynamoDB, SQS/SNS, EventBridge
  - Azure: Functions, Cosmos DB, Service Bus
  - GCP: Cloud Functions, Firestore, Pub/Sub

## Access

To access the cubelab nodes, you can use SSH. First, you need to discover the IP address of each node. You can use the following command in the terminal:

```bash
sudo nmap -O $(hostname -I | awk '{print $1}' | cut -d. -f1-3).0/24
```

This will show you a list of devices connected to the local network, along with their IP addresses. From this point, you can identify the IP address of each cubelab node (Raspberry Pi 4-B and Jetson Nano P3450). It's useful to map them to environment variables to facilitate later access, for example in a `.env` file:

```bash
# .env
RPI_IP=<RASPBERRY_PI_IP>
JETSON1_IP=<JETSON_NANO_1_IP>
JETSON2_IP=<JETSON_NANO_2_IP>
# Node access
export RPI_IP
export JETSON1_IP
export JETSON2_IP
```

To load the environment variables, you can use the following command in the terminal:

```bash
source .env
# Or simply export them directly in the terminal
```

Once you have the IP address of each node, you can access them using SSH. For example, to access the Raspberry Pi 4-B, use the following command:

```bash
ssh pi@${RPI_IP}
ssh ubuntu@${JETSON1_IP}
ssh ubuntu@${JETSON2_IP}
```

By default, the password for the `pi` user on the Raspberry Pi is `raspberry`. For the Jetson Nano devices, the default user is `ubuntu` and the password is also `ubuntu`.

# Raspberry Pi setup as NAT bridge

Download rpi-imager from the official website: https://www.raspberrypi.com/software/

```bash
sudo apt update
sudo apt install rpi-imager
```

Install OS lite image using rpi-imager since we do not need a desktop environment in the SD card. Do not forget to configure the Wi-Fi and SSH settings as customization options.

If everything is set up correctly, you should be able to boot your Raspberry Pi and access it via SSH.

First we need to check the IP address of the Raspberry Pi. You can do this by logging into your router and looking for connected devices, or by using a network scanning tool like `nmap`.

```bash
➜  ~ nmap -sn 10.0.0.0/24
Starting Nmap 7.94SVN ( https://nmap.org ) at 2025-08-30 19:28 MDT
Nmap scan report for _gateway (10.0.0.1)
Host is up (0.024s latency).
Nmap scan report for msi (10.0.0.9)
Host is up (0.00013s latency).
Nmap scan report for 10.0.0.54
Host is up (0.019s latency).
Nmap scan report for 10.0.0.144
Host is up (0.020s latency).
Nmap scan report for 10.0.0.157
Host is up (0.035s latency).
Nmap scan report for 10.0.0.201
Host is up (0.088s latency).
Nmap done: 256 IP addresses (6 hosts up) scanned in 3.75 seconds

```

Replace `10.0.0.0/24` with your local network range.

or ping directly to the Raspberry Pi's hostname (usually `raspberrypi`):

```bash
➜  ~ ping raspberrypi.local
PING raspberrypi.local (10.0.0.157) 56(84) bytes of data.
64 bytes from 10.0.0.157: icmp_seq=1 ttl=64 time=17.7 ms
64 bytes from 10.0.0.157: icmp_seq=2 ttl=64 time=15.4 ms
64 bytes from 10.0.0.157: icmp_seq=3 ttl=64 time=37.6 ms
64 bytes from 10.0.0.157: icmp_seq=4 ttl=64 time=35.4 ms
64 bytes from 10.0.0.157: icmp_seq=5 ttl=64 time=18.8 ms
^C
--- raspberrypi.local ping statistics ---
5 packets transmitted, 5 received, 0% packet loss, time 4006ms
rtt min/avg/max/mdev = 15.436/24.967/37.569/9.479 ms
```

Then you can SSH into the Raspberry Pi using the following command (default password is `raspberry`) and update the password.

```bash
➜  ~ ssh pi@raspberrypi.local
The authenticity of host 'raspberrypi.local (10.0.0.157)' can't be established.
ED25519 key fingerprint is SHA256:TPy0IZb9Q1pSP4Im8fvmoaDlbxNgFqgGAGmv2f373t0.
This key is not known by any other names.
Are you sure you want to continue connecting (yes/no/[fingerprint])? yes
Warning: Permanently added 'raspberrypi.local' (ED25519) to the list of known hosts.
pi@raspberrypi.local's password: 
Linux raspberrypi 6.12.25+rpt-rpi-v8 #1 SMP PREEMPT Debian 1:6.12.25-1+rpt1 (2025-04-30) aarch64

The programs included with the Debian GNU/Linux system are free software;
the exact distribution terms for each program are described in the
individual files in /usr/share/doc/*/copyright.

Debian GNU/Linux comes with ABSOLUTELY NO WARRANTY, to the extent
permitted by applicable law.

SSH is enabled and the default password for the 'pi' user has not been changed.
This is a security risk - please login as the 'pi' user and type 'passwd' to set a new password.

pi@raspberrypi:~ $ passwd
Changing password for pi.
(current) UNIX password: raspberry
New UNIX password: 
Retype new UNIX password: 
passwd: password updated successfully
```

Lets update the system and change the hostname.

```bash
sudo apt update
sudo apt upgrade
sudo hostnamectl set-hostname rpi-nat
```

Need to change `/etc/hosts` to reflect the new hostname.

```bash
sudo nano /etc/hosts
```

Now we need to deactivate useless services.

```bash
sudo systemctl disable bluetooth hciuart wpa_supplicant
```

And install network management tools:

```bash
sudo apt install net-tools iptables iptables-persistent nmap isc-dhcp-server dhcpcd5
```

And some other useful tools:

```bash
sudo apt install nano
```

Now we need to enable the IP forwarding:

```bash
sudo sysctl -w net.ipv4.ip_forward=1 | sudo tee -a /etc/sysctl.conf
```

```bash
sudo sysctl -w net.ipv6.conf.all.forwarding=1 | sudo tee -a /etc/sysctl.conf
```

Now we need to configure the rpi as gateway/router. First we need to assign a static IP address to the new subnet.

```bash
pi@rpi-bridge:~ $ sudo ip addr add 192.168.2.1/24 dev eth0
pi@rpi-bridge:~ $ ip addr show eth0
2: eth0: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 qdisc pfifo_fast state UP group default qlen 1000
    link/ether b8:27:eb:68:db:01 brd ff:ff:ff:ff:ff:ff
    inet 192.168.2.1/24 scope global eth0
       valid_lft forever preferred_lft forever
```

Now need to configure the NAT (Network Address Translation) settings.

```bash
# Flush existing rules
sudo iptables -F
sudo iptables -t nat -F
# Configure the firewall on the Raspberry Pi to allow traffic from the new subnet.
sudo iptables -t nat -A POSTROUTING -o wlan0 -j MASQUERADE
sudo iptables -A FORWARD -i eth0 -o wlan0 -j ACCEPT
sudo iptables -A FORWARD -i wlan0 -o eth0 -m state --state RELATED,ESTABLISHED -j ACCEPT
# Make it persistent
sudo iptables-save | sudo tee /etc/iptables/rules.v4
```

Now lets check everything is working as expected.

```bash
pi@rpi-bridge:~ $ ip route show
default via 10.0.0.1 dev wlan0 proto dhcp src 10.0.0.157 metric 3003 
10.0.0.0/24 dev wlan0 proto dhcp scope link src 10.0.0.157 metric 3003 
192.168.2.0/24 dev eth0 proto dhcp scope link src 192.168.2.1 metric 1002           
```

Now enable `dhcpcd`.

```bash
sudo systemctl start dhcpcd
```

Now we need to check that Rpi has visibility to the new subnet. And need to get the MAC address of the rpi-staging server.

```bash
pi@rpi-bridge:~ $ sudo nmap -sn 192.168.2.0/24
Starting Nmap 7.93 ( https://nmap.org ) at 2025-08-30 21:22 MDT
Nmap scan report for 192.168.2.10
Host is up (0.00033s latency).
MAC Address: E4:5F:01:FD:B0:81 (Raspberry Pi Trading)
Nmap scan report for 192.168.2.20
Host is up (0.00073s latency).
MAC Address: 00:04:4B:E5:5F:28 (Nvidia)
Nmap scan report for 192.168.2.21
Host is up (0.00054s latency).
MAC Address: 00:04:4B:EC:91:DA (Nvidia)
Nmap scan report for 192.168.2.1
Host is up.
Nmap done: 256 IP addresses (4 hosts up) scanned in 4.61 seconds

```

Now we need to configure DHCP with static mappings for the new subnet.

```bash
sudo nano /etc/dhcp/dhcpd.conf
```

With this content.

```text
default-lease-time 600;
max-lease-time 7200;
authoritative;
ddns-update-style none;

# Subnet for eth0
subnet 192.168.2.0 netmask 255.255.255.0 {
    range 192.168.2.20 192.168.2.50;  # Dynamic pool for other devices
    option routers 192.168.2.1;
    option subnet-mask 255.255.255.0;
    option broadcast-address 192.168.2.255;
    option domain-name-servers 8.8.8.8, 8.8.4.4;
    option domain-name "local";

    # Static address for rpi-staging server     
    host rpi-staging {
        hardware ethernet E4:5F:01:FD:B0:81;
        fixed-address 192.168.2.10;
        option host-name "rpi-staging";
    }

    host jetson-1 {
        hardware ethernet 00:04:4b:e5:5f:28;
        fixed-address 192.168.2.11;
        option host-name "jetson-1";
    }

    host jetson-2 {
        hardware ethernet 00:04:4b:ec:91:da;
        fixed-address 192.168.2.12;
        option host-name "jetson-2";
    }

    # Future workers                  
    # host worker-1 {
    #     hardware ethernet b8:27:eb:yy:yy:yy;
    #     fixed-address 192.168.2.13;
    # }
}

```

Clean leases and restart the DHCP server.

```bash
sudo rm /var/lib/dhcp/dhcpd.leases
sudo touch /var/lib/dhcp/dhcpd.leases
sudo systemctl restart isc-dhcp-server
```

Check that `/etc/dhcpcd.conf` has the correct settings.

```text
# Static configuration for eth0 (gateway)
interface eth0
static ip_address=192.168.2.1/24
static domain_name_servers=8.8.8.8 8.8.4.4
nohook wpa_supplicant

# wlan0 uses DHCP from the router
interface wlan0
```

Now we configure the interface.

```bash
echo 'INTERFACESv4="eth0"' | sudo tee /etc/default/isc-dhcp-server
sudo systemctl start isc-dhcp-server
# Check the status and enable
sudo systemctl status isc-dhcp-server
sudo systemctl enable isc-dhcp-server
```

Now we need to configure route in the laptop to the static IP of the Raspberry Pi acting as a gateway.

```bash
sudo ip route add 192.168.2.0/24 via 10.0.0.157
# Check
ip route show | grep 192.168.2
```

# rpi-staging

