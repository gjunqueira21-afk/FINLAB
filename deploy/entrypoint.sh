#!/bin/sh
# Sobe o FinLab dentro do contêiner. Na primeira execução (volume de dados
# vazio), baixa e processa as demonstrações da CVM antes de abrir o painel —
# leva alguns minutos e acontece uma vez só; depois os parquets vivem no
# volume e sobrevivem a rebuilds.
set -e
cd /app

# O repositório traz os parquets anuais (DFP); os trimestrais (ITR) são
# baixados aqui na primeira subida — por isso a checagem olha os dois.
ANO=$(date +%Y)
if [ ! -f valuation_cvm/data/processed/dre_dfp.parquet ] \
   || [ ! -f valuation_cvm/data/processed/dre_itr.parquet ]; then
    echo "==> Primeira execução: baixando as demonstrações da CVM (2016-$ANO)."
    echo "    Isso leva alguns minutos e só acontece uma vez."
    (cd valuation_cvm && python -m src.main --start-year 2016 --end-year "$ANO")
fi

# Fundamentos pré-calculados (data/fundamentos.json): refeitos só quando a
# CVM no disco mudou ou o formato mudou. Feito ANTES do painel subir, num
# processo que termina — a memória que o pandas usa para montar os números
# volta ao sistema, e o painel nunca carrega a CVM inteira.
python -m finlab.backend.tarefas gerar-fundamentos --se-preciso \
    || echo "==> aviso: fundamentos pré-calculados não gerados; o painel calcula direto."

echo "==> FinLab no ar (porta interna 8777; o proxy — Caddy ou Traefik — publica com HTTPS e senha)."
exec python -m uvicorn finlab.backend.app:app --host 0.0.0.0 --port 8777
