# CubeLab

Este repositorio contiene la configuración y documentación de un homelab diseñado para emular un entorno de nube, utilizando hardware de bajo costo y software optimizado. El objetivo es crear un entorno de pruebas para servicios en la nube, con un enfoque en la eficiencia energética y el uso de recursos.

## Hardware

El coste total del homelab es de aproximadamente $525 USD, incluyendo adaptadores de corriente, cables y almacenamiento. A continuación se detalla la configuración del hardware:

| Hardware                | Almacenamiento | CPU/GPU                                   | Precio |
|-------------------------|----------------|-------------------------------------------|--------|
| Raspberry Pi 4-B       | 32GB SD        | 64-bit Quad-Core ARM A72 8GB-LPDDR4     | $100   |
| Jetson Nano P3450      | 64GB SD        | 64-bit Quad-core 128-Core GPU ARM A57 4GB-LPDDR4 | $200   |
| Jetson Nano P3450      | 128GB SD       | 64-bit Quad-core 128-Core GPU ARM A57 4GB-LPDDR4 | $200   |
| TP-Link TLSD10059      | 5 ports        | 1GigE                                     | $25    |

Este homelab está compuesto por un Raspberry Pi 4-B y dos Jetson Nano P3450, conectados a un switch TP-Link TLSD10059. El Raspberry Pi actúa como puerta de enlace y nodo de borde, mientras que los Jetson Nano funcionan como nodos de control y de trabajo.

El consumo energético estimado para el homelab es de aproximadamente 43.2 kWh al mes, lo que equivale a un coste menor de $10 USD, considerando un precio de $0.2 USD por kWh. Esto suponiendo un uso continuo de 24 horas al día, 7 días a la semana.

| Hardware                | Consumo (W)    | Consumo mensual (kWh) | Costo mensual (USD) |
|-------------------------|----------------|------------------------|---------------------|
| Raspberry Pi 4-B       | 15W            | 10.8 kWh               | $2.16               |
| Jetson Nano P3450      | 20W            | 14.4 kWh               | $2.88              |
| Jetson Nano P3450      | 20W            | 14.4 kWh               | $2.88               |
| TP-Link TLSD10059      | 5W             | 3.6 kWh                | $0.72               |
| **Total**              |                | **43.2 kWh**           | **$8.64**          |

## Software

| Hardware                | Almacenamiento | Rol/Función                     | Software                                      |
|-------------------------|----------------|----------------------------------|-----------------------------------------------|
| Raspberry Pi 4-B       | 32GB SD        | API Gateway/Edge Node           | OpenWrt (ARM64)       |
| Jetson Nano P3450      | 64GB SD        | Control Plane/Kubernetes Master  | Ubuntu Server 20.04 LTS (ARM64) + k3s |
| Jetson Nano P3450      | 128GB SD       | Multi-purpose Worker Node       | BalenaOS (Jetson ARM64) + Docker |

El dispositivo Raspberry Pi 4-B se utiliza como puerta de enlace y nodo de borde, mientras que los Jetson Nano P3450 funcionan como nodos de control y de trabajo. A continuación se detallan las configuraciones de software para cada nodo:

La raspberry Pi 4-B será el punto natural de entrada para los usuarios, actuando como un API Gateway y nodo de borde. Implementa los siguientes servicios:

- Kong o Traefik como gateway para gestionar el tráfico de API.
- Keycloak para la autenticación y autorización de usuarios.
- Un portal web para la gestión de servicios y usuarios.
- Mensajería SQS o ServiceBus para la comunicación entre servicios.
- Grafana Agent para la recolección de métricas y logs.
- Un dashboard frontend para la visualización de métricas y logs.

Los Jetson Nano P3450 se utilizan para diferentes propósitos:

1. **Control Plane/Kubernetes Master**: Este nodo gestiona el clúster de Kubernetes y los servicios asociados.
   - Servicios: K3s Control Plane, CoreDNS, Ingress, Grafana, Alertmanager, Prometheus, Loki (logs).
2. **Multi-purpose Worker Node**: Este nodo se utiliza para cargas de trabajo de computación intensiva y almacenamiento.
   - Servicios: MinIO (S3/Blob), emulación Lambda/Functions, DynamoDB/CosmosDB. emulación de CDN.
   - Servicios adicionales: Redis, MongoDB, PostgreSQL, RabbitMQ, etc.

## Acceso

Para acceder a los nodos del homelab, puedes utilizar SSH. Primero hay que descubrir la IP de cada nodo. Para ello, puedes utilizar el siguiente comando en la terminal:

```bash
sudo nmap -O $(hostname -I | awk '{print $1}' | cut -d. -f1-3).0/24
```

Esto te mostrará una lista de dispositivos conectados a la red local, junto con sus direcciones IP. A partir de este punto, podrás identificar la dirección IP de cada uno de los nodos del homelab (Raspberry Pi 4-B y Jetson Nano P3450). Es interesante mapearlos a una variable de entorno para facilitar su acceso posterior. como por ejemplo en un archivo `.env`:

```bash
# .env
RPI_IP=<IP_DEL_RASPBERRY_PI>
JETSON1_IP=<IP_DEL_JETSON_NANO_1>
JETSON2_IP=<IP_DEL_JETSON_NANO_2>
# Acceso a los nodos
export RPI_IP
export JETSON1_IP
export JETSON2_IP
```

Para cargar las variables de entorno, puedes usar el siguiente comando en la terminal:

```bash
source .env
# O simplemente exportarlas directamente en la terminal
```

Una vez que tengas la dirección IP de cada nodo, puedes acceder a ellos utilizando SSH. Por ejemplo, para acceder al Raspberry Pi 4-B, utiliza el siguiente comando:

```bash
ssh pi@${RPI_IP}
ssh ubuntu@${JETSON1_IP}
ssh ubuntu@${JETSON2_IP}
```

Por defecto, la contraseña del usuario `pi` en el Raspberry Pi es `raspberry`. Para los Jetson Nano, el usuario por defecto es `ubuntu` y la contraseña también es `ubuntu`.