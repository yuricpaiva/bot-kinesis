ALTER TABLE dw.vendas
    ADD COLUMN IF NOT EXISTS tipo_atendimento varchar(20),
    ADD COLUMN IF NOT EXISTS valor_gorjeta numeric(14, 2);

COMMENT ON COLUMN dw.vendas.tipo_atendimento IS
    'Tipo de atendimento recebido em order_picture.podType, por exemplo TS para mesa.';

COMMENT ON COLUMN dw.vendas.valor_gorjeta IS
    'Valor da gorjeta/taxa de servico recebido em customProperties.TIP_AMOUNT, com fallback para tip.';
