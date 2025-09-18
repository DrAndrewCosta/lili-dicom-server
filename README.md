# LILI DICOM — Servidor DICOM + UI (macOS)

Servidor DICOM com interface web para receber estudos via C-STORE, responder C-ECHO, navegar e imprimir PDFs de contato (estudo e série) pensada para o Dr. Andrew utilizar com o GE LOGIQe.

## Principais recursos

* Recepção C-STORE e resposta C-ECHO (pynetdicom) com suporte a **JPEG/JPEG-LS/RLE**.
* Armazenamento automático em `storage/AAAA/MM/DD/<StudyUID>/<SeriesUID>/`.
* Geração de miniaturas e PDFs de contato (layout grade configurável).
* Impressão direta opcional via CUPS (`lp`) e sugestão de impressão pelo navegador.
* UI Flask com autenticação básica (`admin`/`admin` por padrão).
* Rotas HTTP estáveis para navegação, PDFs, impressão, download ZIP e logs.
* Scripts simples para execução em modo "produção" (`run_prod.sh`).

## Requisitos

* macOS 13 ou superior (testado em Apple Silicon).
* Python 3.11+ com `venv`.
* CUPS já incluso no macOS (`lp` no PATH).
* Conexão de rede direta com o GE LOGIQe (recomendado 10.10.10.x).

## Preparação do ambiente

```bash
cd ~/LILI_DICOM_server
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
cp .env.example .env  # ajuste conforme necessário
```

### Variáveis de ambiente

| Variável | Padrão | Descrição |
| --- | --- | --- |
| `AE_TITLE` | `PACSANDREW` | AE Title do servidor DICOM |
| `DICOM_PORT` | `11112` | Porta de recepção C-STORE/C-ECHO |
| `WEB_PORT` | `8080` | Porta HTTP da UI |
| `STORE_DIR` | `./app/storage` | Diretório raiz de armazenamento |
| `PDF_HEADER` | `Dr. Andrew Costa ...` | Cabeçalho impresso nos PDFs |
| `PDF_COLS` / `PDF_ROWS` | `4` / `2` | Layout da grade do PDF |
| `PDF_STUDY` | `1` | `1` para gerar PDF por estudo automaticamente |
| `BASIC_AUTH_USER` / `BASIC_AUTH_PASS` | `admin` / `admin` | Credenciais padrão da UI |
| `PRINT_DIRECT` | `1` | `1` para habilitar impressão direta via `/print/*?direct=1` |
| `ALLOW_IPS` | `127.0.0.1,::1` | Lista de IPs autorizados a usar impressão direta |
| `PRINTER_NAME` | _(vazio)_ | Nome da impressora do CUPS (usa padrão quando vazio) |
| `BRAND_TITLE` / `BRAND_COLOR` | `LILI DICOM` / `#255375` | Branding da UI |

> ⚠️ **Produção:** altere usuário/senha, limite `ALLOW_IPS` e considere publicar por trás de um reverse proxy HTTPS (nginx ou Caddy).

## Executando

```bash
source .venv/bin/activate
./run_prod.sh
```

O script garante que `storage/` exista e inicia `app/dicom_server.py` ouvindo em `0.0.0.0:$WEB_PORT`.

### Verificando serviços

```bash
lsof -nP -iTCP:8080 -sTCP:LISTEN  # UI Flask
lsof -nP -iTCP:11112 -sTCP:LISTEN # Porta DICOM
```

Rotas de saúde (requer autenticação básica):

```bash
curl -u admin:admin http://127.0.0.1:8080/healthz
curl -u admin:admin http://127.0.0.1:8080/readyz
```

### Interface web

Acesse [http://127.0.0.1:8080/browse](http://127.0.0.1:8080/browse). Informe usuário/senha configurados (padrão `admin`/`admin`).

Para cada estudo é possível:

* Abrir o PDF do estudo (`/pdf/study/<StudyUID>`).
* Sugerir impressão (abre nova aba e chama `window.print()`).
* Imprimir direto (`/print/study/<StudyUID>?direct=1`, se IP autorizado).
* Baixar o ZIP do estudo (`/download/study/<yyyymmdd>/<StudyUID>.zip`).
* Navegar pelas séries (`/study/<yyyymmdd>/<StudyUID>`).

Cada série permite gerar/abrir PDF, imprimir pelo navegador ou enviar para a impressora com `lp` (quando permitido).

### Impressão direta (CUPS)

* Configure a impressora padrão do macOS ou exporte `PRINTER_NAME`.
* IPs não listados em `ALLOW_IPS` recebem **403** ao chamar `?direct=1`.
* As rotas retornam JSON (`{"ok": true, "printed": true}`) quando o `lp` conclui com sucesso.

### Logs

* Arquivo: `app/dicom_server.log` (rotas `/logs` devolvem as últimas 500 linhas).
* Inclui C-ECHO, C-STORE, geração de PDFs, falhas de preview e mensagens de diagnóstico.

## Configuração do GE LOGIQe

1. Abra o menu DICOM do equipamento.
2. Cadastre um novo servidor com:
   * **AE Title**: `PACSANDREW` (ou o valor ajustado).
   * **IP**: endereço do Mac (ex.: `10.10.10.2`).
   * **Porta**: `11112`.
3. Teste com C-ECHO; o log exibirá `Verification` no recebimento.
4. Configure o destino de envio padrão para esse servidor.

### Rede recomendada

* Conecte o LOGIQe diretamente ao Mac com cabo Ethernet.
* Defina IP estático `10.10.10.1` no Mac e `10.10.10.2` no LOGIQe (ou vice-versa).
* Garanta que o firewall permita as portas 8080/11112.

## Firewall do macOS

Se o firewall estiver ativado, autorize o Python do ambiente virtual:

```bash
PYTHON_BIN="$PWD/.venv/bin/python"
/usr/libexec/ApplicationFirewall/socketfilterfw --add "$PYTHON_BIN"
/usr/libexec/ApplicationFirewall/socketfilterfw --unblockapp "$PYTHON_BIN"
```

## Troubleshooting

* **Sem previews/PDF vazio:** verifique `app/dicom_server.log`. Plugins `pylibjpeg-*` já estão em `requirements.txt`, mas alguns datasets podem exigir GDCM.
* **C-ECHO falhou:** confirme IP/porta/AE Title e se o `lsof` mostra a porta 11112.
* **PDF demora a gerar:** primeira requisição gera miniaturas "on-the-fly" quando ausentes.
* **Impressão direta retorna 403:** confira `ALLOW_IPS` e se a requisição veio do IP correto (usa `X-Forwarded-For` quando presente).
* **Portas ocupadas:** use `lsof -nP -iTCP:8080`/`11112` para descobrir processos conflitantes.
* **Firewall bloqueando:** confirme comandos `socketfilterfw` acima.

## Dataset de teste rápido

O utilitário `app/util_fake_dataset.py` cria uma árvore fake com 1 estudo/1 série/1 imagem para testar a UI/PDF/ZIP:

```bash
source .venv/bin/activate
python app/util_fake_dataset.py
```

## Segurança

* Troque imediatamente `BASIC_AUTH_PASS` em produção.
* Restrinja `ALLOW_IPS` a máquinas confiáveis (ex.: `127.0.0.1` e IP interno).
* Considere publicar via HTTPS (nginx/Caddy) se for expor fora da rede local.
* Monitore `app/dicom_server.log` e faça backup periódico de `storage/`.

## Licença

Projeto fornecido para uso interno do Dr. Andrew.
