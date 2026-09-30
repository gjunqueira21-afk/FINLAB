#!/bin/bash
# Dá ao Hermes acesso às carteiras do FinLab.
#
#   1. copia a skill finlab-carteiras para a pasta de skills do Hermes;
#   2. grava o login do painel num arquivo netrc (chmod 600) que o curl do
#      Hermes lê — a senha é digitada aqui, sem aparecer na tela, e nunca
#      passa pelo chat nem pela linha de comando do agente.
#
# Funciona com o Hermes em contêiner Docker (o caso da Hostinger: um ou mais
# contêineres hermes-agent-*) e com o Hermes instalado direto na VPS:
#
#   bash /root/FINLAB/deploy/hermes/instalar-hermes.sh
#
# Com contêineres, instala em TODOS os que tiverem "hermes" no nome. Para
# escolher: HERMES_CONTAINERS="hermes-agent-abcd-hermes-agent-1" bash ...
# Sem contêiner, usa ~/.hermes (ou HERMES_HOME=/caminho bash ...).
set -euo pipefail
cd "$(dirname "$0")"

SKILL=finlab-carteiras/SKILL.md
[ -f "$SKILL" ] || { echo "[ERRO] Não achei $SKILL."; exit 1; }

# --- onde instalar ------------------------------------------------------------
CONTEINERES=${HERMES_CONTAINERS:-}
if [ -z "$CONTEINERES" ] && [ -z "${HERMES_HOME:-}" ] && command -v docker >/dev/null 2>&1; then
    CONTEINERES=$(docker ps --format '{{.Names}}' | grep -i hermes || true)
fi
HOST_DIR=""
if [ -z "$CONTEINERES" ]; then
    HOST_DIR="${HERMES_HOME:-$HOME/.hermes}"
    if [ ! -d "$HOST_DIR" ]; then
        echo "[ERRO] Não achei o Hermes: nenhum contêiner com 'hermes' no nome e"
        echo "       nenhuma pasta $HOST_DIR. Se ela estiver em outro lugar:"
        echo "       HERMES_HOME=/caminho bash $0"
        exit 1
    fi
fi

# --- credencial ---------------------------------------------------------------
ENV_FILE=../.env
DOMINIO=$(grep -E '^FINLAB_DOMINIO=' "$ENV_FILE" 2>/dev/null | cut -d= -f2- || true)
USUARIO=$(grep -E '^FINLAB_USUARIO=' "$ENV_FILE" 2>/dev/null | cut -d= -f2- || true)
read -r -p "Domínio do painel [${DOMINIO:-finlab.marketwatchrf.com}]: " D
DOMINIO=${D:-${DOMINIO:-finlab.marketwatchrf.com}}
read -r -p "Usuário do painel [${USUARIO:-ADMIN}]: " U
USUARIO=${U:-${USUARIO:-ADMIN}}
read -r -s -p "Senha do painel (não aparece na tela): " SENHA; echo
[ -n "$SENHA" ] || { echo "[ERRO] Senha vazia."; exit 1; }
netrc() { printf 'machine %s\nlogin %s\npassword %s\n' "$DOMINIO" "$USUARIO" "$SENHA"; }

URL="https://$DOMINIO/api/carteiras"
FALHAS=0

relata_teste() {  # $1 = rótulo, $2 = código HTTP
    case "$2" in
        200) echo "   teste OK: lê e edita as carteiras." ;;
        401) echo "   [ATENÇÃO] HTTP 401: usuário ou senha errados — rode de novo."; FALHAS=1 ;;
        sem-curl) echo "   [ATENÇÃO] não há curl em $1; a skill precisa dele."; FALHAS=1 ;;
        *)   echo "   [ATENÇÃO] teste devolveu '$2' (esperado 200): $1 não alcançou $URL."; FALHAS=1 ;;
    esac
}

# --- Hermes direto na VPS -----------------------------------------------------
if [ -n "$HOST_DIR" ]; then
    echo "-> Hermes em $HOST_DIR"
    mkdir -p "$HOST_DIR/skills/finlab-carteiras"
    cp "$SKILL" "$HOST_DIR/skills/finlab-carteiras/SKILL.md"
    ( umask 077; netrc > "$HOST_DIR/finlab.netrc" ); chmod 600 "$HOST_DIR/finlab.netrc"
    echo "   skill e credencial gravadas"
    relata_teste "a VPS" "$(curl -s -o /dev/null -w '%{http_code}' --netrc-file \
                           "$HOST_DIR/finlab.netrc" "$URL" || true)"
fi

# --- Hermes em contêineres ------------------------------------------------------
# Tudo é resolvido DENTRO de cada contêiner: a pasta do Hermes (HERMES_HOME,
# ~/.hermes ou /opt/data) e o curl. A senha entra pelo stdin do docker exec —
# não aparece em argumento de processo nem no histórico.
ACHA_DIR='for d in "$HERMES_HOME" "$HOME/.hermes" /opt/data/.hermes /opt/data /root/.hermes; do
    [ -n "$d" ] && [ -d "$d" ] && { echo "$d"; exit 0; }
done; exit 1'

for c in $CONTEINERES; do
    echo "-> contêiner $c"
    if ! DIR=$(docker exec "$c" sh -c "$ACHA_DIR"); then
        echo "   [ATENÇÃO] não achei a pasta do Hermes dentro dele; pulei."
        FALHAS=1; continue
    fi
    docker exec -i "$c" sh -c 'mkdir -p "$1/skills/finlab-carteiras" &&
        cat > "$1/skills/finlab-carteiras/SKILL.md"' _ "$DIR" < "$SKILL"
    netrc | docker exec -i "$c" sh -c 'umask 077; cat > "$1/finlab.netrc" &&
        chmod 600 "$1/finlab.netrc"' _ "$DIR"
    # O docker exec grava como root, mas o Hermes costuma rodar como um
    # usuário próprio ("hermes"): com o netrc em root:root 600 ele não lê o
    # login. Os arquivos passam para o usuário do Hermes — ou, sem esse
    # usuário, para o dono da pasta dele.
    DONO=$(docker exec "$c" sh -c '
        if id hermes >/dev/null 2>&1; then echo "$(id -u hermes):$(id -g hermes)"
        else stat -c %u:%g "$1" 2>/dev/null; fi' _ "$DIR" || true)
    if [ -n "$DONO" ]; then
        docker exec "$c" chown -R "$DONO" "$DIR/skills/finlab-carteiras" "$DIR/finlab.netrc"
        # a pasta skills/ pode ter nascido agora, como root: devolve ao Hermes
        docker exec "$c" chown "$DONO" "$DIR/skills"
    fi
    echo "   skill e credencial gravadas em $DIR (dono ${DONO:-inalterado})"

    # Fica no disco da VPS (volume) ou só dentro do contêiner? Só no
    # contêiner some se ele for recriado (atualização do Hermes).
    PERSISTE=nao
    while read -r destino; do
        [ -n "$destino" ] || continue   # contêiner sem volume: linha vazia
        case "$DIR/" in "${destino%/}/"*) PERSISTE=sim ;; esac
    done < <(docker inspect "$c" --format '{{range .Mounts}}{{.Destination}}{{println}}{{end}}')
    [ "$PERSISTE" = sim ] || echo "   [aviso] $DIR não está num volume: se o contêiner for recriado, rode este script de novo."

    COMO=(); [ -n "$DONO" ] && COMO=(-u "$DONO")
    CODIGO=$(docker exec "${COMO[@]}" "$c" sh -c 'command -v curl >/dev/null || { echo sem-curl; exit 0; }
        curl -s -o /dev/null -w "%{http_code}" --max-time 20 --netrc-file "$1/finlab.netrc" "$2" || true' \
        _ "$DIR" "$URL")
    relata_teste "$c" "$CODIGO"
done
unset SENHA

echo
if [ "$FALHAS" = 0 ]; then
    echo "Pronto. No chat do Hermes, comece uma conversa nova (/new) para ele"
    echo "carregar a skill finlab-carteiras."
else
    echo "Terminou com avisos (acima). Mande o print para ajustar."
fi
