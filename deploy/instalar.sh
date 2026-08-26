#!/bin/bash
# Instalação do FinLab na VPS (Ubuntu/Debian com Docker).
# Rode de dentro da pasta deploy/:  cd FINLAB/deploy && bash instalar.sh
# Pergunta domínio, e-mail e a senha do painel; gera o .env e sobe tudo.
set -euo pipefail
cd "$(dirname "$0")"

echo "==============================================="
echo "  FinLab — instalação na VPS"
echo "==============================================="

# --- pré-requisitos ---------------------------------------------------------
if ! command -v docker >/dev/null 2>&1; then
    echo "[ERRO] Docker não encontrado. Na Hostinger, use o template de SO"
    echo "       'Ubuntu com Docker', ou instale com:"
    echo "       curl -fsSL https://get.docker.com | sh"
    exit 1
fi
if ! docker compose version >/dev/null 2>&1; then
    echo "[ERRO] O plugin 'docker compose' não está disponível."
    echo "       Instale com: apt-get install -y docker-compose-plugin"
    exit 1
fi

# Portas 80/443: se outra aplicação da VPS já ocupa, o Caddy não sobe.
ocupadas=$(ss -ltn 2>/dev/null | awk '$4 ~ /:(80|443)$/ {print $4}' | sort -u || true)
if [ -n "$ocupadas" ]; then
    echo "[ATENÇÃO] Já existe algo escutando em: $ocupadas"
    echo "          Provavelmente outra aplicação Docker desta VPS usa 80/443."
    echo "          A instalação vai continuar, mas o Caddy pode falhar ao subir."
    echo "          Se falhar, me diga qual aplicação ocupa as portas que eu adapto o deploy."
    echo
fi

# --- perguntas --------------------------------------------------------------
read -r -p "Domínio do painel (ex.: finlab.seusite.com): " DOMINIO
if [ -z "$DOMINIO" ]; then echo "[ERRO] Informe o domínio."; exit 1; fi

read -r -p "Seu e-mail (para o certificado Let's Encrypt): " EMAIL
if [ -z "$EMAIL" ]; then echo "[ERRO] Informe o e-mail."; exit 1; fi

read -r -p "Usuário de login do painel [gab]: " USUARIO
USUARIO=${USUARIO:-gab}

while true; do
    read -r -s -p "Senha do painel (mínimo 8 caracteres): " SENHA; echo
    read -r -s -p "Repita a senha: " SENHA2; echo
    if [ "$SENHA" != "$SENHA2" ]; then echo "As senhas não conferem, tente de novo."; continue; fi
    if [ ${#SENHA} -lt 8 ]; then echo "Senha muito curta, use pelo menos 8 caracteres."; continue; fi
    break
done

echo "-> gerando o hash da senha (a senha em si não fica gravada em lugar nenhum)"
HASH=$(docker run --rm caddy:2-alpine caddy hash-password --plaintext "$SENHA")

# --- .env -------------------------------------------------------------------
cat > .env <<FIM
# Gerado por instalar.sh — NÃO comitar (deploy/.env está no .gitignore).
FINLAB_DOMINIO=$DOMINIO
ACME_EMAIL=$EMAIL
FINLAB_USUARIO=$USUARIO
FINLAB_SENHA_HASH=$HASH
# Opcional: token da BRAPI para consenso de analistas e beta
# (https://brapi.dev). Depois de preencher: docker compose up -d
#BRAPI_TOKEN=
FIM
chmod 600 .env
echo "-> deploy/.env criado"

# --- sobe tudo --------------------------------------------------------------
echo "-> construindo e subindo os contêineres (a primeira vez demora:"
echo "   além do build, o painel baixa as demonstrações da CVM)"
docker compose up -d --build

echo
echo "==============================================================="
echo "  Pronto! Acompanhe a primeira carga de dados com:"
echo "      docker compose logs -f finlab"
echo
echo "  Quando aparecer 'FinLab no ar', acesse:"
echo "      https://$DOMINIO   (login: $USUARIO)"
echo
echo "  Antes disso, garanta o DNS: um registro A de"
echo "      $DOMINIO  ->  IP desta VPS"
echo "  (na Hostinger: Domínios -> Gerenciador de DNS)."
echo "==============================================================="
