#!/usr/bin/env bash
# MetaBot.OS — instalación en un VPS Ubuntu/Debian recién creado.
# Uso (como root en el VPS):
#   curl -fsSL https://raw.githubusercontent.com/Nehorpy-cpu/MetaBot.OS/main/deploy/setup-vps.sh | bash
# o copiar este archivo y ejecutarlo: bash setup-vps.sh
set -euo pipefail

echo "== MetaBot.OS: preparando el servidor =="

# 1. Docker (repositorio oficial)
if ! command -v docker >/dev/null 2>&1; then
  apt-get update -y
  apt-get install -y ca-certificates curl git ufw
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
  chmod a+r /etc/apt/keyrings/docker.asc
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] \
    https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
    > /etc/apt/sources.list.d/docker.list
  apt-get update -y
  apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
fi
echo "Docker: $(docker --version)"

# 2. Firewall básico: SSH + web
ufw allow OpenSSH >/dev/null
ufw allow 80/tcp >/dev/null
ufw allow 443/tcp >/dev/null
ufw --force enable >/dev/null
echo "Firewall activo (22, 80, 443)"

# 3. Código
mkdir -p /opt && cd /opt
if [ -d MetaBot.OS/.git ]; then
  cd MetaBot.OS && git pull
else
  git clone https://github.com/Nehorpy-cpu/MetaBot.OS.git
  cd MetaBot.OS
fi

# 4. Configuración
if [ ! -f .env ]; then
  cp .env.example .env
  echo ""
  echo ">>> FALTA CONFIGURAR: editá /opt/MetaBot.OS/.env con tus API keys"
  echo ">>> (NVIDIA_API_KEY, GROQ_API_KEY, OPENROUTER_API_KEY, BRIDGE_SECRET"
  echo ">>>  y DOMAIN si tenés dominio). Luego ejecutá:"
  echo ">>>   cd /opt/MetaBot.OS && docker compose up -d --build"
  exit 0
fi

# 5. Levantar
docker compose up -d --build
echo ""
echo "== Listo. Estado: =="
docker compose ps
echo ""
echo "Panel: http://$(hostname -I | awk '{print $1}')  (o https://\$DOMAIN si configuraste dominio)"
