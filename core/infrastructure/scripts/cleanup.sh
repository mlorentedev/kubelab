#!/bin/bash
# cleanup.sh

# Stop all running containers
docker stop $(docker ps -a -q)

# Remove all containers
docker rm $(docker ps -a -q)

# Remove all networks
docker network prune -f

# Remove unused volumes
docker volume prune -f

# Recreate the Traefik network
docker network create traefik_network