# Dicionário Kinesis para Banco 3S

Base de análise: `kinesis_dump`, com 1.911 arquivos JSON de evento.

Evento principal encontrado:

| Campo | Valor observado |
|---|---|
| `objectType` | `order_picture` |

## Regras gerais

### Data e hora

O campo `creationDttm` vem em UTC, por exemplo:

```text
2026-05-14T00:00:03.294+00:00
```

Para data/hora local do Brasil/Fortaleza, converter de UTC para `America/Fortaleza` usando timezone real, como `zoneinfo`.

Nao fazer subtracao manual fixa de horas.

Para data comercial/movimento do DW, usar a data da hora local convertida:

```text
DATE(creationDttm convertido para America/Fortaleza)
```

Nao usar `businessDt` como chave/data operacional oficial do DW, pois ele pode divergir do dia correto apos a conversao de UTC para Fortaleza.

### Número do cupom

Há dois identificadores úteis:

| Uso | Campo Kinesis |
|---|---|
| Cupom fiscal/NFC-e | `customProperties.FISCAL_ID` |
| Número interno do pedido/venda | `orderCode` |

Para o banco, quando o campo se chamar `numero do cupom`, usar `customProperties.FISCAL_ID`.

Importante: `customProperties.FISCAL_ID` nao deve ser usado como chave principal da venda, pois pode nascer vazio e aparecer apenas em um evento posterior do Kinesis.

### Chave lógica da venda

A venda deve ser localizada e atualizada por:

```text
storeCode + DATE(creationDttm convertido para America/Fortaleza) + orderCode
```

Mapeamento:

| Uso | Campo Kinesis |
|---|---|
| loja | `storeCode` |
| data movimento | data de `creationDttm` convertido para `America/Fortaleza` |
| numero do pedido | `orderCode` |

Essa chave alimenta o indice unico `uq_vendas_loja_data_pedido` em `dw.vendas(loja, data_movimento, numero_pedido)`.

`FISCAL_ID` passa a ser apenas informacao fiscal complementar. Quando chegar depois, deve atualizar `numero_cupom` na venda existente.

### Canal de venda

Ordem sugerida:

1. `customProperties.DISPLAY_PARTNER`
2. `customProperties.PARTNER`
3. `saleLines[0].customProperties.saleType`
4. `saleTypeId`

Em pedidos iFood, os campos `DISPLAY_PARTNER` e `PARTNER` aparecem como `ifood`.

### Tipo de PDV

Ordem sugerida:

1. `customProperties.POS_TYPE`
2. `podType`
3. `posCode`

## Tabela `venda`

| Campo banco | Campo Kinesis | Observação |
|---|---|---|
| loja | `storeCode` | Código da loja. |
| data e hora | `creationDttm` convertido para horário Brasil | `creationDttm` vem em UTC. |
| data movimento | data de `creationDttm` convertido para `America/Fortaleza` | Nao usar `businessDt` como chave operacional do DW. |
| numero do cupom | `customProperties.FISCAL_ID` | Cupom fiscal/NFC-e. |
| numero do pedido | `orderCode` | Identificador interno da venda. |
| canal de venda | `customProperties.DISPLAY_PARTNER` / `customProperties.PARTNER` / `saleLines[0].customProperties.saleType` | Ver regra de canal. |
| tipo de pdv | `customProperties.POS_TYPE` / `podType` / `posCode` | Ver regra de tipo de PDV. |
| atendente | `posUser` | Nome/login do atendente quando disponível. |
| atendente_id | `posUserId` | Código do atendente. |
| total de venda | `totalAfterDiscount` | Total líquido após desconto. |
| total bruto | `totalGross` ou `totalAmount` | Útil para conciliação. |
| desconto | `discountAmount` | Desconto total do pedido. |
| desconto pedido | `orderDiscountAmount` | Desconto no nível do pedido. |
| codigo cupom desconto | `benefitData[0].code` | Quando houver `benefitData`. |
| nome cupom desconto | `benefitData[0].name` | Na amostra, costuma repetir o código. |
| valor benefício | `benefitData[0].benefitTotalValue` | Valor monetário do benefício. |
| status | `stateId` | Ver opções observadas. |

## Tabela `pagamentos`

Criar uma linha por item de `tenders[]`.

| Campo banco | Campo Kinesis | Observação |
|---|---|---|
| loja | `storeCode` | Herdado da venda. |
| data e hora | `creationDttm` convertido para horário Brasil | Herdado da venda. |
| data movimento | data de `creationDttm` convertido para `America/Fortaleza` | Herdado da venda. |
| numero do cupom | `customProperties.FISCAL_ID` | Herdado da venda. |
| numero do pedido | `orderCode` | Herdado da venda. |
| forma de pagamento | `tenders[].tenderDesc` | Descrição da forma. |
| codigo forma pagamento | `tenders[].tenderType` | Código da forma. |
| valor pagamento | `tenders[].tenderAmount` | Valor do pagamento. |
| troco | `tenders[].changeAmount` | Quando aplicável. |
| nsu | `tenders[].details.Nsu` | Quando TEF/cartão. |
| nsu host | `tenders[].details.NsuHost` | Quando TEF/cartão. |
| autorização | `tenders[].details.AuthCode` | Quando TEF/cartão. |
| bandeira/mídia | `tenders[].details.Media` | Quando disponível. |
| código fiscal pagamento | `tenders[].details.tPag` | Código fiscal da forma de pagamento. |
| processadora | `tenders[].details.TransactionProcessor` | Ex.: `SITEF`. |

## Tabela `produtos`

Criar uma linha por item de `saleLines[]`.

| Campo banco | Campo Kinesis | Observação |
|---|---|---|
| loja | `storeCode` | Herdado da venda. |
| data e hora | `creationDttm` convertido para horário Brasil | Herdado da venda. |
| data movimento | data de `creationDttm` convertido para `America/Fortaleza` | Herdado da venda. |
| numero do cupom | `customProperties.FISCAL_ID` | Herdado da venda. |
| numero do pedido | `orderCode` | Herdado da venda. |
| canal de venda | `customProperties.DISPLAY_PARTNER` / `customProperties.PARTNER` / `saleLines[].customProperties.saleType` | Ver regra de canal. |
| tipo de pdv | `customProperties.POS_TYPE` / `podType` / `posCode` | Ver regra de tipo de PDV. |
| código produto | `saleLines[].partCode` | Código do produto/componente. |
| descrição produto | `saleLines[].name` | Nome do item. |
| itemType | `saleLines[].itemType` | Ex.: `PRODUCT`, `COMBO`, `OPTION`, `CANADD`. |
| itemID | `saleLines[].itemId` | Identificador/caminho pelo qual o item foi acessado. |
| família do item | `saleLines[].tags` com prefixo `PLUFamilyGroup=` | Extrair somente o valor após `=`. |
| quantidade | `saleLines[].multipliedQty` | Quantidade efetiva do item, ja multiplicada em combos/adicionais. |
| quantidade original | `saleLines[].qty` | Quantidade direta da linha no pedido. |
| preco_item | `saleLines[].itemPrice` | Valor total decimal da linha do item; gravar NULL quando ausente/nulo. |
| preço item | `saleLines[].itemPrice` | Valor do item. |
| preço unitário | `saleLines[].unitPrice` | Valor unitário. |
| desconto item | `saleLines[].itemDiscount` | Desconto do item. |
| nível | `saleLines[].level` | Hierarquia dentro de combo/opções. |
| linha | `saleLines[].lineNumber` | Sequência da linha. |

## Tabela `cancelamentos`

Usar a mesma estrutura base de venda. Identificar cancelamentos principalmente pela presença dos campos de XML de cancelamento/inutilização.

| Campo banco | Campo Kinesis | Observação |
|---|---|---|
| loja | `storeCode` | Código da loja. |
| data e hora | `updateDttm` ou `creationDttm` convertido para horário Brasil | Usar `updateDttm` se vier preenchido; senão `creationDttm`. |
| data movimento | data de `creationDttm` convertido para `America/Fortaleza` | Nao usar `businessDt` como chave operacional do DW. |
| numero do cupom | `customProperties.FISCAL_ID` | Cupom fiscal/NFC-e. |
| numero do pedido | `orderCode` | Identificador interno. |
| canal de venda | `customProperties.DISPLAY_PARTNER` / `customProperties.PARTNER` / `saleLines[0].customProperties.saleType` | Ver regra de canal. |
| tipo de pdv | `customProperties.POS_TYPE` / `podType` / `posCode` | Ver regra de tipo de PDV. |
| atendente | `posUser` | Nome/login quando disponível. |
| atendente_id | `posUserId` | Código do atendente. |
| total de venda | `totalAfterDiscount` | Total líquido. |
| desconto | `discountAmount` | Desconto total. |
| status | `stateId` | Ver opções observadas. |
| xml cancelamento | `fiscalXmlCancel` | Presença indica cancelamento fiscal. |
| xml nfe cancelamento | `fiscalXmlNfeCancel` | Quando aplicável. |
| xml inutilização | `fiscalXmlDisable` | Quando aplicável. |
| xml nfe inutilização | `fiscalXmlNfeDisable` | Quando aplicável. |

Campos que ajudam a identificar cancelamento/inutilização:

```text
fiscalXmlCancel
fiscalXmlNfeCancel
fiscalXmlDisable
fiscalXmlNfeDisable
stateId
```

## Opções observadas nos JSONs

Os números entre parênteses são contagens dentro da amostra de 1.911 eventos.

### `customProperties.POS_TYPE`

| Valor | Qtde |
|---|---:|
| `FC` | 1296 |
| `DL` | 350 |
| `TT` | 265 |

### `podType`

| Valor | Qtde |
|---|---:|
| `FL` | 1296 |
| `FC` | 350 |
| `TT` | 265 |

### `posCode`

| Valor | Qtde |
|---|---:|
| `1` | 1225 |
| `0` | 350 |
| `4` | 265 |
| `2` | 71 |

### `originatorCode`

| Valor | Qtde |
|---|---:|
| `1` | 1225 |
| `0` | 350 |
| `4` | 265 |
| `2` | 71 |

### `saleTypeId`

| Valor | Qtde |
|---|---:|
| `0` | 1561 |
| `3` | 350 |

### `saleLines[].customProperties.saleType`

| Valor | Qtde |
|---|---:|
| `EAT_IN` | 13845 |
| `DELIVERY` | 3939 |

### `customProperties.DISPLAY_PARTNER`

| Valor | Qtde |
|---|---:|
| `ifood` | 350 |

### `customProperties.PARTNER`

| Valor | Qtde |
|---|---:|
| `ifood` | 350 |

### `customProperties.CLASSIFICATION`

| Valor | Qtde |
|---|---:|
| `$DELIVERY` | 350 |

### `customProperties.DELIVERY_BY`

| Valor | Qtde |
|---|---:|
| `IFOOD` | 246 |
| `MERCHANT` | 104 |

### `customProperties.ORDER_TYPE`

| Valor | Qtde |
|---|---:|
| `N` | 349 |
| `A` | 1 |

### `customProperties.TENDER_TYPE`

| Valor | Qtde |
|---|---:|
| `online` | 345 |
| `offline` | 5 |

### `customProperties.IFOOD_ONLINE_METHOD`

| Valor | Qtde |
|---|---:|
| `CREDIT` | 135 |
| `PIX` | 81 |
| `DIGITAL_WALLET` | 69 |
| `OTHER` | 32 |
| `DEBIT` | 18 |
| `MEAL_VOUCHER` | 10 |

### `customProperties.IFOOD_ONLINE_BRAND`

| Valor | Qtde |
|---|---:|
| `MASTERCARD` | 111 |
| `PIX` | 81 |
| `VISA` | 73 |
| `NUBANK` | 32 |
| `MASTERCARD_MAESTRO` | 24 |
| `ELO` | 7 |
| `VISA_ELECTRON` | 5 |
| `TICKET` | 5 |
| `SODEXO` | 3 |
| `MOVILE_PAY` | 2 |
| `VR` | 2 |

### `saleLines[].itemType`

| Valor | Qtde |
|---|---:|
| `OPTION` | 8891 |
| `PRODUCT` | 3246 |
| `COMBO` | 2974 |
| `CANADD` | 2673 |

### Família do item (`saleLines[].tags`, `PLUFamilyGroup=...`)

| Valor | Qtde |
|---|---:|
| `BROWNIE` | 1351 |
| `TOPPING E ADICIONAL` | 695 |
| `DELICIA NO POTE E MILKSHAKE` | 676 |
| `COOKIE` | 469 |
| `BEM CASADO` | 375 |
| `DOCINHO E BRIGADEIRO FESTA` | 197 |
| `CHOCOLATE E BOMBOM` | 194 |
| `BOLO, TORTA E SOBREMESA` | 173 |
| `EMBALAGEM` | 144 |
| `BEBIDA` | 127 |
| `CUPCAKE E BROWNIECAKE` | 124 |
| `CAFE` | 105 |
| `GELATO` | 26 |
| `PRODUTO SAZONAL` | 16 |
| `SALGADO` | 6 |

### `tenders[].tenderDesc`

| Valor | Qtde |
|---|---:|
| `TEF Crédito` | 577 |
| `TEF Débito` | 470 |
| `iFood` | 345 |
| `Carteiras digitais` | 291 |
| `Dinheiro` | 96 |
| `Cupom Parceiro` | 80 |
| `POS DEBITO` | 12 |
| `POS VOUCHER` | 9 |
| `PIX ENCOMENDA` | 5 |
| `Pagamento Delivery` | 5 |
| `POS ENCOMENDA` | 4 |
| `POS PIX` | 4 |
| `POS CREDITO` | 4 |
| `LINK ENCOMENDA` | 3 |

### `tenders[].tenderType`

| Valor | Qtde |
|---|---:|
| `1` | 577 |
| `2` | 470 |
| `121` | 345 |
| `4` | 291 |
| `0` | 96 |
| `200` | 80 |
| `21` | 12 |
| `26` | 9 |
| `29` | 5 |
| `128` | 5 |
| `33` | 4 |
| `25` | 4 |
| `20` | 4 |
| `30` | 3 |

### `tenders[].details.tPag`

| Valor | Qtde |
|---|---:|
| `03` | 577 |
| `04` | 450 |
| `17` | 291 |
| `11` | 18 |
| `10` | 2 |

### `tenders[].details.Media`

| Valor | Qtde |
|---|---:|
| `MASTERCARD CREDITO` | 318 |
| `PIX` | 291 |
| `MAESTRO DÉBITO` | 260 |
| `VISA CREDITO` | 218 |
| `VISAELECTRON DÉBITO` | 146 |
| `Elo` | 33 |
| `ELO DÉBITO` | 29 |
| `VR ALIMENTAÇÃO VOUCHER` | 12 |
| `TICKET RESTAURANTE` | 9 |
| `SODEXO REFEIÇÃO` | 9 |
| `AMEX CREDITO` | 8 |
| `Ticket` | 5 |

### `tenders[].details.TransactionProcessor`

| Valor | Qtde |
|---|---:|
| `SITEF` | 1338 |

### `tenders[].details.eletronicType`

| Valor | Qtde |
|---|---:|
| `1` | 473 |
| `2` | 398 |
| `4` | 259 |
| `0` | 137 |

### `benefitData[].code`

| Valor | Qtde |
|---|---:|
| `4` | 15 |
| `1` | 14 |
| `16` | 6 |
| `3` | 6 |
| `2` | 5 |
| `13` | 2 |
| `14` | 1 |

### `benefitData[].name`

| Valor | Qtde |
|---|---:|
| `4` | 15 |
| `1` | 14 |
| `16` | 6 |
| `3` | 6 |
| `2` | 5 |
| `13` | 2 |
| `14` | 1 |

### `stateId`

| Valor | Qtde |
|---|---:|
| `5` | 1795 |
| `4` | 116 |

### `typeId`

| Valor | Qtde |
|---|---:|
| `0` | 1911 |

### `customProperties.VOID_TYPE`

Valores encontrados em eventos de cancelamento operacional no PDV:

| Valor | Qtde | Interpretacao |
|---|---:|---|
| `VOID_CURRENT_ORDER` | 55 | Pedido atual cancelado antes de virar venda fiscal. Na amostra, nao houve outro evento relacionado com o mesmo `storeCode + orderCode`, nao havia `FISCAL_ID` e nao havia `fiscalXmlCancel`. |
| `VOID_PAID_ORDER` | 4 | Venda ja paga/fiscalizada cancelada depois. Na amostra, veio com `FISCAL_ID` preenchido e `fiscalXmlCancel` preenchido. |

Motivos observados em `customProperties.VOID_REASON_DESCR`:

| `VOID_TYPE` | Motivo | Qtde |
|---|---|---:|
| `VOID_CURRENT_ORDER` | `Cancelamento do usuario` | 55 |
| `VOID_PAID_ORDER` | `Mudou de ideia` | 2 |
| `VOID_PAID_ORDER` | `Cancelamento` | 1 |
| `VOID_PAID_ORDER` | `Venda Errada` | 1 |

## Regras finais para alimentar o banco

Estas sao as regras definidas para construir o script que vai ler os eventos `order_picture` e alimentar as tabelas do banco de dados.

### Regras gerais de extracao

- O numero do cupom deve vir de `customProperties.FISCAL_ID`.
- A chave oficial da venda deve ser `storeCode + DATE(creationDttm convertido para America/Fortaleza) + orderCode`, mapeada para `loja + data_movimento + numero_pedido`.
- Nunca usar `customProperties.FISCAL_ID` como chave principal da venda; ele e apenas informacao fiscal complementar e pode chegar depois.
- A coluna `data_hora` deve vir de `creationDttm` convertido para `America/Fortaleza`.
- A coluna `data_movimento` deve ser derivada de `DATE(data_hora)`.
- Nunca usar `businessDt` como chave principal/data operacional oficial do DW.
- O tipo de PDV deve vir de `customProperties.POS_TYPE`.
- O tipo de venda deve vir de `saleLines[].customProperties.saleType`.
- Para a tabela `venda`, usar o primeiro `saleType` encontrado em `saleLines[]`.
- Para a tabela `produtos`, usar o `saleType` da propria linha do item em `saleLines[]`.
- O atendente deve vir de `posUser.name`.
- O codigo do desconto deve juntar todos os valores de `benefitData[].code` separados por virgula.
- A familia do item deve ser extraida de `saleLines[].tags[]`, procurando a tag com prefixo `PLUFamilyGroup=` e mantendo somente o valor depois do `=`.
- A tabela `pagamentos` deve gerar uma linha para cada item de `tenders[]`.
- A tabela `produtos` deve gerar uma linha para cada item de `saleLines[]`.
- A tabela `cancelamentos` deve receber apenas eventos onde `fiscalXmlCancel` estiver preenchido.
- Eventos com `customProperties.VOID_TYPE = VOID_CURRENT_ORDER` devem ser ignorados nas tabelas principais `venda`, `pagamentos` e `produtos`, pois representam pedido cancelado antes de virar venda fiscal. Se necessario, gravar apenas em uma tabela/log de pedidos cancelados antes da venda.
- Eventos com `customProperties.VOID_TYPE = VOID_PAID_ORDER` devem ser tratados como cancelamento de venda ja emitida/paga, atualizando a venda existente e alimentando `cancelamentos` quando `fiscalXmlCancel` estiver preenchido.
- A venda deve aceitar `numero_cupom` vazio/nulo e atualizar esse campo quando `FISCAL_ID` aparecer em evento posterior.
- Cancelamento tem precedencia sobre venda aprovada: se a venda ja estiver marcada como cancelada, um evento posterior/reprocessado sem cancelamento nao deve reverter o status para aprovado.

### Tabela `venda`

Uma linha por venda/evento `order_picture`, exceto eventos `VOID_CURRENT_ORDER`, que nao devem entrar como venda.

| Campo banco | Campo Kinesis / regra |
|---|---|
| loja | `storeCode` |
| data e hora | `creationDttm` convertido para `America/Fortaleza` |
| data movimento | data de `creationDttm` convertido para `America/Fortaleza` |
| numero do cupom | `customProperties.FISCAL_ID` |
| tipo de venda | primeiro valor encontrado em `saleLines[].customProperties.saleType` |
| tipo de pdv | `customProperties.POS_TYPE` |
| atendente | `posUser.name` |
| total de venda | `vNF` dentro do XML fiscal (`fiscalXml`) |
| desconto | `discountAmount` |
| codigo do desconto | juntar `benefitData[].code` separado por virgula |

### Tabela `pagamentos`

Uma linha por item de `tenders[]`.

| Campo banco | Campo Kinesis / regra |
|---|---|
| loja | `storeCode` |
| data e hora | `creationDttm` |
| numero do cupom | `customProperties.FISCAL_ID` |
| forma de pagamento | `tenders[].tenderDesc` |
| valor pagamento | `tenders[].tenderAmount` |

### Tabela `produtos`

Uma linha por item de `saleLines[]`.

| Campo banco | Campo Kinesis / regra |
|---|---|
| loja | `storeCode` |
| data e hora | `creationDttm` |
| numero do cupom | `customProperties.FISCAL_ID` |
| tipo de venda | `saleLines[].customProperties.saleType` |
| tipo de pdv | `customProperties.POS_TYPE` |
| codigo produto | `saleLines[].partCode` |
| descricao produto | `saleLines[].name` |
| itemType | `saleLines[].itemType` |
| itemID | `saleLines[].itemId` |
| familia do item | valor de `saleLines[].tags[]` com prefixo `PLUFamilyGroup=` |
| quantidade | `saleLines[].multipliedQty` |
| preco_item | `saleLines[].itemPrice` |

### Tabela `cancelamentos`

Uma linha por venda cancelada. Considerar venda cancelada quando `fiscalXmlCancel` estiver preenchido. Eventos `VOID_PAID_ORDER` com `fiscalXmlCancel` preenchido devem atualizar a venda existente como cancelada; eventos `VOID_CURRENT_ORDER` nao entram aqui, salvo se no futuro vierem acompanhados de cancelamento fiscal.

| Campo banco | Campo Kinesis / regra |
|---|---|
| loja | `storeCode` |
| data e hora | `creationDttm` |
| numero do cupom | `customProperties.FISCAL_ID` |
| tipo de venda | primeiro valor encontrado em `saleLines[].customProperties.saleType` |
| tipo de pdv | `customProperties.POS_TYPE` |
| atendente | `posUser.name` |
| total de venda | `vNF` dentro do XML fiscal (`fiscalXml`) |
