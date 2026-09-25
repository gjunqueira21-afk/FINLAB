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

# --- quem atende as portas 80/443? -------------------------------------------
# Se a VPS já tem um Traefik (o proxy padrão da Hostinger), o FinLab entra na
# rede dele por labels. Sem proxy nenhum, sobe o Caddy próprio.
TRAEFIK=$(docker ps --format '{{.Names}} {{.Image}}' | awk '$2 ~ /(^|\/)traefik(:|$)/ {print $1; exit}')
MODO=caddy
if [ -n "$TRAEFIK" ]; then
    MODO=traefik
    echo "-> Traefik encontrado ($TRAEFIK): o FinLab vai entrar nele, sem Caddy próprio."

    # Rede: a do Traefik; havendo várias, a que tem 'traefik' ou 'proxy' no nome.
    REDES=$(docker inspect -f '{{range $k, $v := .NetworkSettings.Networks}}{{println $k}}{{end}}' "$TRAEFIK" | sed '/^$/d')
    TRAEFIK_REDE=$(echo "$REDES" | grep -Ei 'traefik|proxy' | head -1 || true)
    if [ -z "$TRAEFIK_REDE" ]; then TRAEFIK_REDE=$(echo "$REDES" | head -1); fi

    # Entrypoint HTTPS e resolvedor de certificado: primeiro nos argumentos do
    # Traefik; se ele usa arquivo de configuração, nas labels das aplicações
    # que ele já publica — o que funciona para elas funciona para o FinLab.
    ARGS=$(docker inspect -f '{{join .Args "\n"}}' "$TRAEFIK" 2>/dev/null || true)
    TRAEFIK_ENTRYPOINT=$(echo "$ARGS" | sed -n 's/^--entrypoints\.\([^.]*\)\.address=:443$/\1/p' | head -1)
    TRAEFIK_CERTRESOLVER=$(echo "$ARGS" | sed -n 's/^--certificatesresolvers\.\([^.]*\)\..*/\1/p' | head -1)
    LABELS=$(docker ps -q | xargs -r docker inspect -f '{{range $k, $v := .Config.Labels}}{{printf "%s=%s\n" $k $v}}{{end}}' 2>/dev/null || true)
    if [ -z "$TRAEFIK_ENTRYPOINT" ]; then
        TRAEFIK_ENTRYPOINT=$(echo "$LABELS" | sed -n 's/^traefik\.http\.routers\.[^.]*\.entrypoints=//p' | tr ',' '\n' | grep -vx web | head -1 || true)
    fi
    if [ -z "$TRAEFIK_CERTRESOLVER" ]; then
        TRAEFIK_CERTRESOLVER=$(echo "$LABELS" | sed -n 's/^traefik\.http\.routers\.[^.]*\.tls\.certresolver=\(.*\)/\1/p' | head -1 || true)
    fi
    TRAEFIK_ENTRYPOINT=${TRAEFIK_ENTRYPOINT:-websecure}
    TRAEFIK_CERTRESOLVER=${TRAEFIK_CERTRESOLVER:-letsencrypt}

    echo "   rede: $TRAEFIK_REDE · entrypoint HTTPS: $TRAEFIK_ENTRYPOINT · certificado: $TRAEFIK_CERTRESOLVER"
    read -r -p "   Está certo? [S/n] " OK
    if [ "${OK:-S}" != "S" ] && [ "${OK:-S}" != "s" ]; then
        read -r -p "   Rede do Traefik [$TRAEFIK_REDE]: " X; TRAEFIK_REDE=${X:-$TRAEFIK_REDE}
        read -r -p "   Entrypoint HTTPS [$TRAEFIK_ENTRYPOINT]: " X; TRAEFIK_ENTRYPOINT=${X:-$TRAEFIK_ENTRYPOINT}
        read -r -p "   Resolvedor de certificado [$TRAEFIK_CERTRESOLVER]: " X; TRAEFIK_CERTRESOLVER=${X:-$TRAEFIK_CERTRESOLVER}
    fi
    echo
else
    ocupadas=$(ss -ltn 2>/dev/null | awk '$4 ~ /:(80|443)$/ {print $4}' | sort -u || true)
    if [ -n "$ocupadas" ]; then
        echo "[ATENÇÃO] Já existe algo escutando em: $ocupadas — e não é um Traefik."
        echo "          O Caddy do FinLab vai falhar ao subir. Descubra quem ocupa com:"
        echo "              ss -ltnp | grep -E ':80 |:443 '"
        echo "          e me diga, que eu adapto o deploy."
        exit 1
    fi
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
# O hash bcrypt tem '$' — entre aspas simples, o compose não o interpreta.
cat > .env <<FIM
# Gerado por instalar.sh — NÃO comitar (deploy/.env está no .gitignore).
FINLAB_DOMINIO=$DOMINIO
ACME_EMAIL=$EMAIL
FINLAB_USUARIO=$USUARIO
FINLAB_SENHA_HASH='$HASH'
FIM
if [ "$MODO" = traefik ]; then
    cat >> .env <<FIM
# Modo Traefik: o FinLab se pendura no proxy que já atende 80/443.
COMPOSE_FILE=docker-compose.yml:docker-compose.traefik.yml
TRAEFIK_REDE=$TRAEFIK_REDE
TRAEFIK_ENTRYPOINT=$TRAEFIK_ENTRYPOINT
TRAEFIK_CERTRESOLVER=$TRAEFIK_CERTRESOLVER
FIM
else
    cat >> .env <<FIM
# Modo Caddy: HTTPS e senha pelo Caddy próprio do FinLab.
COMPOSE_PROFILES=caddy
FIM
fi
cat >> .env <<FIM
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
