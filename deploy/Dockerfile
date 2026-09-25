# FinLab — imagem de produção.
# Contexto de build = a raiz do repositório (ver docker-compose.yml).
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    TZ=America/Sao_Paulo \
    FINLAB_DOCKER=1

WORKDIR /app

# Dependências primeiro, para o cache de camadas valer entre git pulls.
# tqdm não está no requirements do painel, mas o downloader do pipeline
# da CVM importa — sem ele a primeira carga de dados falharia.
COPY finlab/requirements.txt /app/finlab/requirements.txt
RUN pip install -r /app/finlab/requirements.txt tqdm

COPY . /app
RUN chmod +x /app/deploy/entrypoint.sh

# O uvicorn só escuta dentro da rede do compose; quem fala com a
# internet é o proxy — o Caddy do projeto ou o Traefik da VPS (HTTPS + senha).
EXPOSE 8777

ENTRYPOINT ["/app/deploy/entrypoint.sh"]
