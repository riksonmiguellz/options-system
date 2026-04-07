# Sistema de Análise de Opções - Deploy

## Rodar localmente (sem Docker)

```bash
# Instalar dependências
pip install -r requirements.txt

# Definir usuário e senha (opcional, padrão: admin / admin123)
export APP_USER=admin
export APP_PASS=sua_senha_aqui

# No Windows (PowerShell):
# $env:APP_USER="admin"
# $env:APP_PASS="sua_senha_aqui"

# Rodar
streamlit run streamlit_app.py
```

O app abre em `http://localhost:8501`.

---

## Rodar com Docker

```bash
# Build
docker build -t options-system .

# Run (com senha customizada)
docker run -d -p 8501:8501 \
  -e APP_USER=admin \
  -e APP_PASS=sua_senha_segura \
  --name options-system \
  options-system
```

Acesse `http://localhost:8501`.

---

## Deploy em servidor (VPS / cloud)

### Opção 1: Docker em VPS (DigitalOcean, AWS EC2, etc.)

1. Suba o projeto para o servidor (git clone ou scp)
2. Instale Docker no servidor
3. Rode os comandos de build e run acima
4. Configure um reverse proxy (Nginx) para HTTPS:

```nginx
server {
    listen 80;
    server_name seu-dominio.com;

    location / {
        proxy_pass http://localhost:8501;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

### Opção 2: Streamlit Community Cloud (grátis)

1. Suba o projeto para um repositório GitHub
2. Acesse [share.streamlit.io](https://share.streamlit.io)
3. Conecte o repositório
4. Nas configurações do app, adicione os secrets:
   - `APP_USER = "admin"`
   - `APP_PASS = "sua_senha"`
5. Deploy automático

### Opção 3: Railway / Render

1. Conecte o repositório GitHub
2. Configure as variáveis de ambiente `APP_USER` e `APP_PASS`
3. Deploy automático via Dockerfile

---

## Variáveis de ambiente

| Variável   | Descrição        | Padrão     |
|------------|------------------|------------|
| `APP_USER` | Usuário de login | `admin`    |
| `APP_PASS` | Senha de login   | `admin123` |

---

## Estrutura do projeto

```
options-system/
├── streamlit_app.py      # App principal com autenticação
├── trades_log.csv        # Histórico de operações
├── requirements.txt      # Dependências Python
├── Dockerfile            # Container Docker
├── .dockerignore         # Arquivos ignorados no build
└── README_DEPLOY.md      # Este arquivo
```
