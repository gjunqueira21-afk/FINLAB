# FinLab na VPS (Docker + Caddy)

Dois contêineres: o **painel** (uvicorn, só na rede interna) e o **Caddy**
na frente, com HTTPS automático do Let's Encrypt e **senha** — nada fica
aberto na internet. Feito para a VPS da Hostinger, mas funciona em qualquer
Ubuntu/Debian com Docker.

## O que você precisa antes

1. **DNS**: um registro `A` do seu domínio (ex.: `finlab.seusite.com`)
   apontando para o IP da VPS. Na Hostinger: *Domínios → Gerenciador de DNS*.
2. **Token do GitHub** (o repositório é privado): em
   github.com → *Settings → Developer settings → Fine-grained tokens →
   Generate new token* — dê acesso **somente a este repositório**, permissão
   *Contents: Read-only*, validade de 1 ano. Guarde o token.

## Instalar

No terminal da VPS (SSH ou o Web console da Hostinger), como root:

```bash
cd /root
git clone https://github.com/gjunqueira21-afk/FINLAB.git
#  usuário: gjunqueira21-afk   ·   senha: cole o TOKEN

cd FINLAB/deploy
bash instalar.sh
```

O instalador pergunta domínio, e-mail e a senha do painel, e sobe tudo.
A primeira subida demora: além do build, o painel **baixa as demonstrações
da CVM** (2016 até o ano corrente). Acompanhe com:

```bash
docker compose logs -f finlab
```

Quando aparecer `FinLab no ar`, acesse `https://seu-dominio` e faça login.

## Rotina

| Para… | Rode (em `FINLAB/deploy`) |
|---|---|
| Atualizar o código (depois de um PR aceito) | `bash atualizar.sh` |
| Atualizar as demonstrações da CVM | `bash atualizar-dados.sh` |
| Atualizar as carteiras acompanhadas (cota, alertas, lâminas) | `bash atualizar-carteiras.sh` |
| Ver os logs | `docker compose logs -f finlab` |
| Parar / subir | `docker compose down` / `docker compose up -d` |

Para os dados se atualizarem sozinhos toda segunda às 6h:

```bash
crontab -e
# adicione a linha:
0 6 * * 1  cd /root/FINLAB/deploy && bash atualizar-dados.sh >> /var/log/finlab-dados.log 2>&1
# e, meia hora depois, as carteiras acompanhadas (cota, alertas de banda e lâminas):
30 6 * * 1  cd /root/FINLAB/deploy && bash atualizar-carteiras.sh >> /var/log/finlab-carteiras.log 2>&1
```

O cron das carteiras roda **sem chave de IA nenhuma** (as chaves ficam no
navegador): ele recalcula cota, pesos, alertas de banda e regrava a lâmina
`.md` de cada carteira. Research e análise continuam sendo pedidos pela
interface. Os deep researches pedidos no chat ficam em
`finlab/data/deep empresas/` (dentro do volume `finlab_dados_app` — o nome
tem espaço, cite-o entre aspas em scripts).

## Como as coisas ficam guardadas

- Parquets da CVM e caches: **volumes Docker** (`finlab_dados_cvm`,
  `finlab_dados_app`) — sobrevivem a rebuild e a `docker compose down`.
- Certificados HTTPS: volume `finlab_caddy_data`.
- Configuração (domínio, usuário, hash da senha): `deploy/.env` — fica só
  na VPS, nunca no git. A senha em si não é gravada em lugar nenhum;
  o arquivo guarda apenas o hash bcrypt.
- **Chaves de API dos LLMs**: continuam no `localStorage` do SEU navegador,
  como no uso local — o servidor nunca as vê nem as guarda. Configure-as de
  novo no ⚙ do painel na primeira visita pelo domínio.

## Espaço e memória

~1,5 GB de disco (imagem + dados da CVM) e ~1 GB de RAM em uso normal.

## Se as portas 80/443 já estiverem ocupadas

Outra aplicação Docker da VPS pode já estar usando 80/443 (o instalador
avisa). Nesse caso o Caddy do FinLab não sobe — é só dizer qual aplicação
ocupa as portas que o deploy é adaptado para se pendurar no proxy existente
ou usar outras portas.
