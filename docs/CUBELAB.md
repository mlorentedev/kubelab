# CubeLab

Este repositorio contiene la configuración y documentación de un cubelab diseñado para emular un entorno de nube, utilizando hardware de bajo costo y software optimizado. El objetivo es crear un entorno de pruebas para servicios en la nube, con un enfoque en la eficiencia energética y el uso de recursos.

## Hardware

El coste total del cubelab es de aproximadamente $700 USD, incluyendo adaptadores de corriente, cables y almacenamiento. A continuación se detalla la configuración del hardware:

| Dispositivo                | Almacenamiento | CPU/GPU                                   | Precio |
|-------------------------|----------------|-------------------------------------------|--------|
| MiniPC Acemagic         | 256GB SSD       | 12th Alder Lake N100 Intel 12GB-LPDDR4 | $150   |
| Raspberry Pi 4-B       | 32GB SD        | 64-bit Quad-Core ARM A72 8GB-LPDDR4     | $100   |
| Jetson Nano P3450      | 64GB SD        | 64-bit Quad-core 128-Core GPU ARM A57 4GB-LPDDR4 | $200   |
| Jetson Nano P3450      | 128GB SD       | 64-bit Quad-core 128-Core GPU ARM A57 4GB-LPDDR4 | $200   |
| TP-Link TLSD10059      | 5 ports        | 1GigE                                     | $25    |

Este cubelab está compuesto por un MiniPC ACEMAGICIAN, un Raspberry Pi 4-B y dos Jetson Nano P3450, conectados a un switch TP-Link TLSD10059. El MiniPC actúa como nodo master y control plane, el Raspberry Pi como puerta de enlace y nodo de borde, mientras que los Jetson Nano funcionan como nodos de trabajo.  

El consumo energético estimado para el cubelab es de aproximadamente 64.8 kWh al mes, lo que equivale a un coste aproximado de $13 USD, considerando un precio de $0.2 USD por kWh. Esto suponiendo un uso continuo de 24 horas al día, 7 días a la semana.

| Dispositivo                | Consumo (W)    | Consumo mensual (kWh) | Costo mensual (USD) |
|-------------------------|----------------|------------------------|---------------------|
| MiniPC Acemagic         | 30W            | 21.6 kWh               | $4.32               |
| Raspberry Pi 4-B       | 15W            | 10.8 kWh               | $2.16               |
| Jetson Nano P3450      | 20W            | 14.4 kWh               | $2.88              |
| Jetson Nano P3450      | 20W            | 14.4 kWh               | $2.88               |
| TP-Link TLSD10059      | 5W             | 3.6 kWh                | $0.72               |
| **Total**              |                | **64.8 kWh**           | **$12.96**           |

## Software

| Dispositivo                | Almacenamiento | Rol/Función                     | Software                                      |
|-------------------------|----------------|----------------------------------|-----------------------------------------------|
| MiniPC Acemagician     | 256GB SSD       | Control Plane/Kubernetes Master  | Ubuntu Server 20.04 LTS (x86_64) + k3s      |
| Raspberry Pi 4-B       | 32GB SD        | API Gateway/Edge Node           | OpenWrt (ARM64)       |
| Jetson Nano P3450      | 64GB SD        | Multi-purpose Worker Node      | Ubuntu Server 20.04 LTS (ARM64) + K3s Worker |
| Jetson Nano P3450      | 128GB SD       | Multi-purpose Worker Node       | BalenaOS (Jetson ARM64) + Docker |

## Propósitos y Servicios de Cada Nodo

### MiniPC ACEMAGICIAN - Control Plane Principal

El MiniPC ACEMAGICIAN actúa como cerebro del CubeLab, aprovechando su mayor potencia de procesamiento, RAM y almacenamiento SSD para ejecutar:

- **Plano de Control Kubernetes**:
  - K3s Control Plane completo (API Server, Scheduler, Controller Manager, etcd)
  - Gestión centralizada de políticas y seguridad del clúster
  - Programación inteligente de cargas de trabajo

- **Monitorización y Observabilidad**:
  - Stack Prometheus-Grafana-Alertmanager-Loki
  - Almacenamiento centralizado de métricas y logs
  - Dashboards personalizados para visualización del estado del clúster

- **Almacenamiento Principal**:
  - PostgreSQL para bases de datos relacionales
  - MinIO para emulación de servicios S3
  - Longhorn para gestión de volúmenes persistentes

- **CI/CD y Gestión de Aplicaciones**:
  - Registry privado de contenedores
  - Pipelines de integración con Tekton/Jenkins X
  - ArgoCD y Helm para despliegues GitOps

- **Emulación de Servicios Cloud Enterprise**:
  - AWS: EKS, RDS, CloudWatch
  - Azure: AKS, SQL Database, Azure Monitor
  - GCP: GKE, Cloud SQL, Cloud Monitoring

### Raspberry Pi 4-B - Gateway y Edge Processing

La Raspberry Pi 4-B funciona como punto de entrada al clúster y procesador de borde:

- **API Gateway y Routing**:
  - Kong/Traefik para gestión de tráfico, balanceo y transformación
  - Políticas de rate limiting y circuit breaking
  - Logging y análisis de tráfico API

- **Seguridad y Gestión de Identidad**:
  - Keycloak para autenticación/autorización centralizada
  - OAuth2/OpenID Connect
  - Single Sign-On para aplicaciones del clúster

- **Portal de Administración**:
  - Interfaz web unificada para gestión del entorno
  - Dashboard centralizado con vistas por roles
  - Consola para despliegue y gestión de aplicaciones

- **Edge Computing y Networking**:
  - Edge Functions para procesamiento local
  - Cache distribuido tipo CDN
  - Enrutamiento basado en geolocalización simulada

- **Emulación de Servicios Cloud Edge**:
  - AWS: API Gateway, CloudFront, IoT Edge
  - Azure: API Management, Front Door, IoT Edge
  - GCP: Apigee, Cloud CDN, Edge TPU

### Jetson Nano #1 - GPU Computing y Análisis de Datos

El primer Jetson Nano se especializa en cargas de trabajo que aprovechan su GPU:

- **Computación GPU y Aceleración Hardware**:
  - Inferencia de modelos IA/ML con aceleración GPU
  - Procesamiento de visión computacional
  - Transcoding multimedia

- **Plataformas de Machine Learning**:
  - TensorFlow, PyTorch y ONNX Runtime
  - Jupyter para experimentación
  - MLflow y Kubeflow para flujos ML

- **Procesamiento de Datos e Imágenes**:
  - Pipelines de procesamiento en tiempo real
  - APIs de análisis de imágenes y detección de objetos
  - OCR y generación de embeddings

- **Emulación de Servicios Cloud AI**:
  - AWS: SageMaker, Rekognition, Comprehend
  - Azure: Cognitive Services, Computer Vision
  - GCP: Vertex AI, Vision AI, Natural Language

### Jetson Nano #2 - Servicios Serverless y Datos NoSQL

El segundo Jetson Nano se configura como especialista en servicios serverless y bases NoSQL:

- **Infraestructura Serverless**:
  - OpenFaaS/Kubeless para emulación FaaS
  - Entornos compatibles con Lambda
  - Triggers basados en eventos

- **Bases de Datos NoSQL**:
  - MongoDB para documentos JSON
  - Redis para caché y estructuras en memoria
  - Cassandra/ScyllaDB para series temporales

- **Sistemas de Mensajería y Eventos**:
  - RabbitMQ/NATS para comunicación asíncrona
  - Implementación de colas y sistemas pub/sub
  - Flujos de eventos tipo Kafka

- **Microservicios y Contenedores**:
  - Aplicaciones de referencia basadas en microservicios
  - Patrones API Gateway, Circuit Breaker, Bulkhead
  - Service Mesh con Linkerd

- **Emulación de Servicios Cloud Serverless**:
  - AWS: Lambda, DynamoDB, SQS/SNS, EventBridge
  - Azure: Functions, Cosmos DB, Service Bus
  - GCP: Cloud Functions, Firestore, Pub/Sub

## Acceso

Para acceder a los nodos del cubelab, puedes utilizar SSH. Primero hay que descubrir la IP de cada nodo. Para ello, puedes utilizar el siguiente comando en la terminal:

```bash
sudo nmap -O $(hostname -I | awk '{print $1}' | cut -d. -f1-3).0/24
```

Esto te mostrará una lista de dispositivos conectados a la red local, junto con sus direcciones IP. A partir de este punto, podrás identificar la dirección IP de cada uno de los nodos del cubelab (Raspberry Pi 4-B y Jetson Nano P3450). Es interesante mapearlos a una variable de entorno para facilitar su acceso posterior. como por ejemplo en un archivo `.env`:

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