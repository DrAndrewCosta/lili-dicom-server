# LILI DICOM v6.3 — pronto para imprimir
- Login UI: **admin / admin**
- Impressão direta: **ativada** (usa impressora padrão do macOS; para fixar uma impressora, edite `PRINTER_NAME` no `run_prod.sh`)
- Acesso: `http://127.0.0.1:8080/browse`




LILI DICOM — LOGIQe DICOM Server & UI (macOS)

Servidor DICOM de recepção (C-STORE) com interface web simples para visualizar estudos, gerar PDFs de contato (série/estudo), imprimir (via CUPS) e baixar ZIP.
Projetado e testado com GE LOGIQe (linha 2024, portátil) enviando as imagens diretamente para um Mac.

AE Title configurável (padrão PACSANDREW)

Porta DICOM (padrão 11112)

UI web em http://127.0.0.1:8080/browse com auth básica (admin/admin por padrão)

PDF por estudo e por série (layouts grade 4×2 ou mosaico preset)

Impressão: “sugerir impressão” (via navegador) e impressão direta (CUPS lp)

Geração de PDF sob demanda (não dá 500 se faltam miniaturas; cria “preview on-the-fly”)

Sumário

Arquitetura & Diretórios

Requisitos

Instalação (projeto)

Execução

Variáveis de ambiente

Interface Web

Configuração do LOGIQe

Redes recomendadas (Mac ↔ LOGIQe)

Impressão

FAQ / Troubleshooting

Comandos úteis

Notas de segurança

Licença

Arquitetura & Diretórios
LILI_DICOM_server/
├─ app/
│  ├─ dicom_server.py        # servidor DICOM + UI Flask + rotas PDF/print
│  ├─ templates/
│  │  ├─ base.html
│  │  ├─ browse.html
│  │  └─ study.html
│  └─ static/                # assets (se precisar)
├─ storage/                  # onde os DICOMs e PDFs são armazenados
├─ requirements.txt
├─ run_prod.sh               # iniciar servidor web+dicom
└─ README.md


Os estudos são salvos em storage/YYYY/MM/DD/<StudyUID>/<SeriesUID>/...

PDFs:

Série: SeriesContactSheet.pdf (dentro da pasta da série)

Estudo: StudyContactSheet.pdf (dentro da pasta do estudo)

Requisitos

macOS (testado em Apple Silicon, Python 3.12+)

Python 3 + venv

CUPS instalado (vem no macOS) para impressão direta (lp)

Firewal do macOS permitindo o Python escutar nas portas 11112 (DICOM) e 8080 (UI)

Instalação (projeto)
# 1) clone/baixe o projeto
cd /Users/andrew/LILI_DICOM_server

# 2) crie e ative o ambiente
python3 -m venv .venv
source .venv/bin/activate

# 3) dependências
pip install -r requirements.txt


Observação: o projeto usa pydicom, pynetdicom, reportlab, Pillow, numpy e plugins de decodificação (pylibjpeg*).

Execução
cd /Users/andrew/LILI_DICOM_server
source .venv/bin/activate

# configurações básicas (ajuste se quiser)
export AE_TITLE="PACSANDREW"
export DICOM_PORT="11112"
export WEB_PORT="8080"

# branding e PDF
export BRAND_TITLE="LILI DICOM"
export BRAND_COLOR="#255375"
export PDF_HEADER="Dr. Andrew Costa - ultrassomdermatologico.com"
export PDF_COLS="4"              # colunas na grade
export PDF_ROWS="2"              # linhas na grade
export PDF_STUDY="1"             # gera PDF único por estudo

# auth e impressão
export BASIC_AUTH_USER="admin"
export BASIC_AUTH_PASS="admin"
export PRINT_DIRECT="1"          # habilita impressão direta via /print/*
export ALLOW_IPS="127.0.0.1,::1" # IPs autorizados a usar impressão direta
# export PRINTER_NAME="Minha_Impressora"  # opcional

# iniciar (Flask + DICOM)
./run_prod.sh


A UI abrirá em:

http://127.0.0.1:8080/browse


Login padrão: admin / admin

Variáveis de ambiente
Variável	Padrão	Descrição
AE_TITLE	PACSANDREW	AE do servidor DICOM
DICOM_PORT	11112	Porta C-STORE/C-ECHO
WEB_PORT	8080	Porta da UI
STORE_DIR	app/storage	Raiz de armazenamento
BASIC_AUTH_USER	admin	Usuário HTTP Basic
BASIC_AUTH_PASS	admin	Senha HTTP Basic
BRAND_TITLE	LILI DICOM	Título no topo
BRAND_COLOR	#255375	Cor da marca
PDF_HEADER	Dr. Andrew Costa ...	Cabeçalho do PDF
PDF_COLS	4	Colunas grade padrão
PDF_ROWS	2	Linhas grade padrão
PDF_STUDY	1	1 PDF por estudo
PRINT_DIRECT	1	Habilita /print/* direto
PRINTER_NAME	(vazio)	Força uma impressora do CUPS
ALLOW_IPS	127.0.0.1,::1	IPs permitidos p/ impressão direta
Interface Web

/browse: lista estudos recentes (últimos 7 dias por padrão), com busca rápida.

Abrir PDF: gera/abre StudyContactSheet.pdf ao voar, se não existir.

Imprimir PDF: abre o PDF numa nova aba e chama window.print() (diálogo do navegador).

Imprimir direto: envia o PDF ao CUPS (lp). Requer PRINT_DIRECT=1 e IP permitido.

Ver séries: página do estudo com tabela de séries e PDFs por série.

Baixar ZIP: cria um .zip do estudo inteiro.

Rotas usadas pelos botões:

/pdf/study/<StudyUID>
/pdf/series/<SeriesUID>
/print/study/<StudyUID>?direct=1
/print/series/<SeriesUID>?direct=1


Quando não existem miniaturas, o servidor cria uma prévia on-the-fly a partir de 1 DICOM por série.
Se mesmo assim não for possível renderizar, é gerado um PDF de diagnóstico (sem 500).

Configuração do LOGIQe

No LOGIQe (DICOM Storage SCP destino):

IP/FQDN: IP do Mac (veja cenário de rede abaixo)

Porta: 11112

Called AE Title: PACSANDREW (igual ao AE_TITLE)

Compressão: Nenhum (para teste inicial)

C-ECHO (Verify): deve retornar ✓ no equipamento e log mostrar 0x0000

Redes recomendadas (Mac ↔ LOGIQe)
Opção A — Ethernet direta (mais estável, recomendada)

Conecte LOGIQe ↔ Mac com cabo Ethernet (ou adaptador USB-Ethernet no Mac).

No Mac (interface Ethernet/USB-Ethernet):

IPv4: Manual

IP: 10.10.10.1

Máscara: 255.255.255.0

Gateway/Router: deixe em branco (o Mac continua usando Wi-Fi para internet)

Em Ordem de Serviços, deixe Wi-Fi acima de Ethernet (rota padrão pela Wi-Fi).

No LOGIQe:

IP: 10.10.10.2

Máscara: 255.255.255.0

Gateway: em branco; se obrigatório, use 10.10.10.1

No LOGIQe, destino DICOM:

IP: 10.10.10.1, Porta: 11112, Called AE: PACSANDREW

Se sua Wi-Fi já usa 192.168.10.x, não use essa mesma rede no enlace direto.
Ex.: 10.10.10.0/24 no enlace direto evita conflito de rota.

Opção B — Mesma Wi-Fi

Mac e LOGIQe no mesmo Wi-Fi/roteador (DHCP).

Descubra o IP do Mac em Preferências > Rede (ou ipconfig getifaddr en0).

Use este IP no LOGIQe como destino.

Pode variar conforme a rede (menos previsível/estável que a Ethernet direta).

Impressão

Imprimir PDF (UI): abre o PDF e chama o diálogo de impressão do navegador.

Imprimir direto: GET /print/study/<StudyUID>?direct=1 → CUPS lp
Requer:

PRINT_DIRECT=1

Seu IP na lista ALLOW_IPS (p.ex. 127.0.0.1,::1 para local)

(Opcional) PRINTER_NAME para escolher a impressora. Sem definir, usa padrão.

Exemplo de teste no terminal:

lpstat -p -d         # lista impressoras e padrão
lp -d NOME "arquivo.pdf"

FAQ / Troubleshooting
“Ping ☹️” no LOGIQe

Verifique se Mac e LOGIQe estão na mesma rede/sub-rede (ver seção de redes).

Em Ethernet direta, use os IPs 10.10.10.1 (Mac) e 10.10.10.2 (LOGIQe).

Confirme no Mac: ifconfig (ou “Rede” nas Preferências).

C-ECHO falha

No Mac, confirme que o servidor está de pé e ouvindo:

lsof -nP -iTCP:11112 -sTCP:LISTEN


Verifique o log: app/dicom_server.log.

Firewal do macOS deve permitir o Python receber conexões (ver abaixo).

Porta 8080 ocupada
lsof -nP -iTCP:8080 -sTCP:LISTEN
kill -9 <PID>

“Not Found” ao abrir PDF

Agora as rotas /pdf/study/<StudyUID> e /pdf/series/<SeriesUID> geram o PDF se ele não existir.

Se ainda aparecer 404, confira se o <StudyUID>/<SeriesUID> existem em storage/.

“Internal Server Error”

Não deve mais ocorrer por falta de miniaturas: o servidor gera “on-the-fly” ou cria PDF de diagnóstico.

Olhe app/dicom_server.log para detalhes da série/instância com compressão não suportada.

Firewal do macOS (liberar Python)

O macOS normalmente pergunta na primeira execução. Se precisar liberar manualmente:

sudo /usr/libexec/ApplicationFirewall/socketfilterfw --add "/Users/andrew/LILI_DICOM_server/.venv/bin/python"
sudo /usr/libexec/ApplicationFirewall/socketfilterfw --unblockapp "/Users/andrew/LILI_DICOM_server/.venv/bin/python"

Autenticação não aceita

Padrão: admin/admin (pode mudar com BASIC_AUTH_USER/PASS).

Se mexeu nas variáveis, reinicie o servidor (encerrar processo atual e ./run_prod.sh novamente).

Impressão direta falha

Verifique se seu IP está em ALLOW_IPS.

Teste lp no terminal com um PDF qualquer.

Defina PRINTER_NAME se a impressora padrão não for a desejada.

Comandos úteis

Logs (últimas linhas):

tail -f app/dicom_server.log


Portas:

lsof -nP -iTCP:8080 -sTCP:LISTEN
lsof -nP -iTCP:11112 -sTCP:LISTEN


Matar processos na 8080:

for pid in $(lsof -ti tcp:8080); do kill -9 $pid; done

Notas de segurança

Troque a senha padrão (admin/admin) em produção.

Use ALLOW_IPS conservador para impressão direta.

Se publicar a UI em rede, avalie HTTPS (reverse proxy) e usuários por host/IP.

Licença

Uso interno/educacional. Revise requisitos institucionais antes de uso clínico formal.
GE, LOGIQe e nomes relacionados são marcas de seus respectivos titulares.

Créditos & Contato

Projeto configurado para o fluxo de Dr. Andrew Costa — ultrassomdermatologico.com.
Dúvidas/ajustes de layout (mosaico/grade), impressão e rede: abrir issue no repositório.
