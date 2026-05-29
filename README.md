# Pipeline Kinesis 3S -> PostgreSQL

Projeto Python para consumir eventos do AWS Kinesis da 3S/e-Deploy, gravar o bruto no PostgreSQL e alimentar tabelas tratadas para BI.

Fluxo:

```text
Kinesis
-> raw.kinesis_events
-> processor_dw.py
-> dw.vendas / dw.pagamentos / dw.produtos / dw.cancelamentos
-> Power BI
```

## Instalar Dependencias

```bash
pip install -r requirements.txt
```

## Configurar Ambiente

Crie uma copia do `.env.example`:

```bash
copy .env.example .env
```

Preencha as credenciais AWS e PostgreSQL:

```env
AWS_ACCESS_KEY_ID=
AWS_SECRET_ACCESS_KEY=
AWS_REGION=us-east-2
KINESIS_STREAM_NAME=backoffice-prod-exporter-emporiobrownie
SHARD_ITERATOR_TYPE=LATEST
MAX_RECORDS_PER_READ=10

POSTGRES_HOST=localhost
POSTGRES_PORT=5437
POSTGRES_DB=brownie_3s
POSTGRES_USER=admin
POSTGRES_PASSWORD=123456

RAW_BATCH_SIZE=100
PROCESSOR_SLEEP_SECONDS=5
COLLECTOR_SLEEP_SECONDS=3
BUSINESS_TIMEZONE=America/Fortaleza
```

## Scripts Principais

Coletar eventos do Kinesis para `raw.kinesis_events`:

```bash
python -m src.collector_raw
```

Processar um lote da RAW para o DW e encerrar:

```bash
python -m src.processor_dw --once
```

Processar continuamente:

```bash
python -m src.processor_dw
```

Coletar tudo que ainda esta disponivel na retencao do Kinesis e encerrar:

```bash
SHARD_ITERATOR_TYPE=TRIM_HORIZON MAX_RECORDS_PER_READ=1000 python -m src.collector_raw --until-caught-up
```

Processar a RAW ate nao haver mais eventos pendentes e encerrar:

```bash
python -m src.processor_dw --until-empty
```

Rodar a carga noturna completa:

```bash
bash scripts/run_kinesis_nightly.sh
```

## Responsabilidades

`collector_raw.py`:

- conecta no Kinesis;
- le eventos;
- extrai metadados basicos;
- grava o JSON bruto em `raw.kinesis_events`;
- usa `ON CONFLICT (shard_id, sequence_number) DO NOTHING`;
- nao aplica regra de negocio;
- nao acessa tabelas `dw.*`.

`processor_dw.py`:

- le `raw.kinesis_events` com `processed = false`;
- processa somente `object_type = 'order_picture'`;
- transforma eventos para `dw.vendas`, `dw.pagamentos`, `dw.produtos` e `dw.cancelamentos`;
- marca eventos processados;
- grava `error_message` quando falhar;
- nao acessa o Kinesis.

## Chave da Venda

No DW, a venda e identificada por:

```text
loja + data_movimento + numero_pedido
```

Origem:

```text
loja = storeCode
data_hora = creationDttm convertido para America/Fortaleza
data_movimento = DATE(data_hora)
numero_pedido = orderCode
```

`data_negocio` guarda `businessDt` sem conversao de fuso, apenas como data operacional complementar.

Nao usar `FISCAL_ID`, `numero_cupom`, `businessDt` ou `data_negocio` como chave principal da venda.

`FISCAL_ID` alimenta `numero_cupom`, mas pode nascer vazio e aparecer depois.

## Regras Criticas

- Eventos do Kinesis representam atualizacoes de estado da venda.
- Uma mesma venda pode chegar varias vezes.
- O UPSERT de `dw.vendas` usa `loja + data_movimento + numero_pedido`.
- Antes de recriar pagamentos: `DELETE FROM dw.pagamentos WHERE venda_id = ?`.
- Antes de recriar produtos: `DELETE FROM dw.produtos WHERE venda_id = ?`.
- `VOID_CURRENT_ORDER` e ignorado no DW e marcado como processado na RAW.
- `VOID_PAID_ORDER` com `fiscalXmlCancel` marca venda como cancelada.
- Cancelamento operacional forte (`stateId = 4`, `VOID_AT` ou `MANUAL_CANCELLATION`) marca venda como cancelada mesmo sem `fiscalXmlCancel`.
- Cancelamento tem precedencia: `cancelado=true` nunca volta para `false`.
- Datas do DW sempre usam timezone `America/Fortaleza` via timezone real.

## Documentacao de Mapeamento

As regras completas de campos e cancelamentos estao em:

```text
DICIONARIO_KINESIS_BANCO_3S.md
```

## Testes

Depois de instalar dependencias:

```bash
python -m pytest tests -q
```

## Seguranca

Nao versione credenciais AWS ou PostgreSQL. O arquivo `.gitignore` ja ignora `.env`, dumps do Kinesis, caches e arquivos temporarios.
