#!/bin/bash
# Troca a senha do painel: gera o hash novo, regrava FINLAB_SENHA_HASH no
# deploy/.env e sobe o proxy com ela. A senha é digitada sem aparecer na tela
# e não fica gravada em lugar nenhum — só o hash bcrypt.
#
#   cd /root/FINLAB/deploy && bash trocar-senha.sh
#
# Depois, se o Hermes usa o painel, rode também hermes/instalar-hermes.sh
# para ele receber a senha nova.
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -f .env ]; then echo "[ERRO] deploy/.env não existe — rode instalar.sh."; exit 1; fi

while true; do
    read -r -s -p "Senha nova (mínimo 12 caracteres): " SENHA; echo
    read -r -s -p "Repita a senha: " SENHA2; echo
    if [ "$SENHA" != "$SENHA2" ]; then echo "As senhas não conferem, tente de novo."; continue; fi
    if [ ${#SENHA} -lt 12 ]; then echo "Senha muito curta, use pelo menos 12 caracteres."; continue; fi
    break
done

echo "-> gerando o hash"
HASH=$(docker run --rm caddy:2-alpine caddy hash-password --plaintext "$SENHA")
unset SENHA SENHA2

# O hash bcrypt tem '$' e '/': troca via awk com a variável de ambiente, sem
# passar o hash por uma expressão do sed. Aspas simples no .env, para o
# compose não interpretar o '$'.
cp .env .env.bak
NOVO_HASH="$HASH" awk '
    /^FINLAB_SENHA_HASH=/ { print "FINLAB_SENHA_HASH='\''" ENVIRON["NOVO_HASH"] "'\''"; feito=1; next }
    { print }
    END { if (!feito) print "FINLAB_SENHA_HASH='\''" ENVIRON["NOVO_HASH"] "'\''" }
' .env.bak > .env
chmod 600 .env .env.bak
echo "-> deploy/.env atualizado (a versão anterior ficou em deploy/.env.bak)"

echo "-> aplicando"
docker compose up -d
echo "-> pronto. Entre no painel com a senha nova."
