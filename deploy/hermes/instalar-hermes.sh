#!/bin/bash
# Dá ao Hermes (agente rodando nesta VPS) acesso às carteiras do FinLab.
#
#   1. copia a skill finlab-carteiras para a pasta de skills do Hermes;
#   2. grava o login do painel num arquivo netrc (chmod 600) que o curl do
#      Hermes lê — a senha é digitada aqui, sem aparecer na tela, e nunca
#      passa pelo chat nem pela linha de comando do agente.
#
# Rode como o MESMO usuário que roda o Hermes (em geral root):
#   bash /root/FINLAB/deploy/hermes/instalar-hermes.sh
set -euo pipefail
cd "$(dirname "$0")"

HERMES_DIR="${HERMES_HOME:-$HOME/.hermes}"
if [ ! -d "$HERMES_DIR" ]; then
    echo "[ERRO] Não achei a pasta do Hermes em $HERMES_DIR."
    echo "       Se ela estiver em outro lugar: HERMES_HOME=/caminho bash $0"
    exit 1
fi

# --- skill --------------------------------------------------------------------
mkdir -p "$HERMES_DIR/skills/finlab-carteiras"
cp finlab-carteiras/SKILL.md "$HERMES_DIR/skills/finlab-carteiras/SKILL.md"
echo "-> skill copiada para $HERMES_DIR/skills/finlab-carteiras/"

# --- credencial ---------------------------------------------------------------
ENV_FILE=../.env
DOMINIO=$(grep -E '^FINLAB_DOMINIO=' "$ENV_FILE" 2>/dev/null | cut -d= -f2- || true)
USUARIO=$(grep -E '^FINLAB_USUARIO=' "$ENV_FILE" 2>/dev/null | cut -d= -f2- || true)
read -r -p "Domínio do painel [${DOMINIO:-finlab.marketwatchrf.com}]: " D
DOMINIO=${D:-${DOMINIO:-finlab.marketwatchrf.com}}
read -r -p "Usuário do painel [${USUARIO:-ADMIN}]: " U
USUARIO=${U:-${USUARIO:-ADMIN}}
read -r -s -p "Senha do painel (não aparece na tela): " SENHA; echo
if [ -z "$SENHA" ]; then echo "[ERRO] Senha vazia."; exit 1; fi

NETRC="$HERMES_DIR/finlab.netrc"
umask 077
printf 'machine %s\nlogin %s\npassword %s\n' "$DOMINIO" "$USUARIO" "$SENHA" > "$NETRC"
chmod 600 "$NETRC"
unset SENHA
echo "-> credencial gravada em $NETRC (só o dono lê)"

# --- teste --------------------------------------------------------------------
CODIGO=$(curl -s -o /dev/null -w '%{http_code}' --netrc-file "$NETRC" \
         "https://$DOMINIO/api/carteiras" || true)
if [ "$CODIGO" = 200 ]; then
    echo "-> teste OK: o Hermes já consegue ler e editar as carteiras."
    echo "   Reinicie o Hermes (ou abra uma conversa nova) para ele carregar a skill."
else
    echo "[ATENÇÃO] O teste devolveu HTTP $CODIGO (esperado 200)."
    echo "          401 = usuário ou senha errados: rode este script de novo."
fi
