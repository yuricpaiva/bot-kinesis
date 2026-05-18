import argparse
import logging
import time
from typing import Any

from .config import load_config
from .db import connect
from .mappers import MappedOrder, map_order_picture
from .utils import extract_payload


LOGGER = logging.getLogger(__name__)


FETCH_RAW_SQL = """
SELECT id
FROM raw.kinesis_events
WHERE processed = false
ORDER BY id
LIMIT %s
"""

LOCK_RAW_SQL = """
SELECT id, object_type, payload
FROM raw.kinesis_events
WHERE id = %s AND processed = false
FOR UPDATE
"""

MARK_PROCESSED_SQL = """
UPDATE raw.kinesis_events
SET processed = true,
    processed_at = NOW(),
    error_message = NULL
WHERE id = %s
"""

MARK_ERROR_SQL = """
UPDATE raw.kinesis_events
SET error_message = %s
WHERE id = %s
"""

UPSERT_VENDA_SQL = """
INSERT INTO dw.vendas (
    loja,
    data_hora,
    data_movimento,
    numero_cupom,
    numero_pedido,
    tipo_venda,
    tipo_pdv,
    atendente,
    total_venda,
    desconto,
    codigo_desconto,
    cancelado,
    updated_at
)
VALUES (
    %(loja)s,
    %(data_hora)s,
    %(data_movimento)s,
    %(numero_cupom)s,
    %(numero_pedido)s,
    %(tipo_venda)s,
    %(tipo_pdv)s,
    %(atendente)s,
    %(total_venda)s,
    %(desconto)s,
    %(codigo_desconto)s,
    %(cancelado)s,
    NOW()
)
ON CONFLICT (loja, data_movimento, numero_pedido)
DO UPDATE SET
    data_hora = EXCLUDED.data_hora,
    numero_cupom = COALESCE(EXCLUDED.numero_cupom, dw.vendas.numero_cupom),
    tipo_venda = EXCLUDED.tipo_venda,
    tipo_pdv = EXCLUDED.tipo_pdv,
    atendente = EXCLUDED.atendente,
    total_venda = EXCLUDED.total_venda,
    desconto = EXCLUDED.desconto,
    codigo_desconto = EXCLUDED.codigo_desconto,
    cancelado = dw.vendas.cancelado OR EXCLUDED.cancelado,
    updated_at = NOW()
RETURNING id, cancelado
"""


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true", help="Processa um lote e encerra.")
    args = parser.parse_args()

    config = load_config()
    with connect(config.postgres) as conn:
        LOGGER.info("Processor DW iniciado.")
        while True:
            processed_count = process_batch(conn, config.raw_batch_size, config.timezone_name)
            if args.once:
                break
            if processed_count == 0:
                time.sleep(config.processor_sleep_seconds)


def process_batch(conn, batch_size: int, timezone_name: str) -> int:
    with conn.cursor() as cur:
        cur.execute(FETCH_RAW_SQL, (batch_size,))
        ids = [row["id"] for row in cur.fetchall()]

    processed_count = 0
    for raw_id in ids:
        try:
            process_one(conn, raw_id, timezone_name)
            processed_count += 1
        except Exception as exc:
            conn.rollback()
            mark_error(conn, raw_id, str(exc))
            LOGGER.exception("Falha ao processar raw.kinesis_events id=%s.", raw_id)
    return processed_count


def process_one(conn, raw_id: int, timezone_name: str) -> None:
    with conn.cursor() as cur:
        cur.execute(LOCK_RAW_SQL, (raw_id,))
        raw_event = cur.fetchone()
        if raw_event is None:
            conn.rollback()
            return

        object_type = raw_event["object_type"]
        payload = extract_payload(raw_event["payload"])
        if object_type != "order_picture":
            cur.execute(MARK_PROCESSED_SQL, (raw_id,))
            conn.commit()
            LOGGER.info("RAW id=%s ignorado por object_type=%s.", raw_id, object_type)
            return
        if payload is None:
            raise ValueError("Payload RAW sem objeto JSON processavel.")

        mapped = map_order_picture(payload, timezone_name)
        if mapped.skip_dw:
            cur.execute(MARK_PROCESSED_SQL, (raw_id,))
            conn.commit()
            LOGGER.info("RAW id=%s ignorado no DW: %s.", raw_id, mapped.skip_reason)
            return

        save_mapped_order(cur, mapped)
        cur.execute(MARK_PROCESSED_SQL, (raw_id,))
        conn.commit()
        LOGGER.info("RAW id=%s processado no DW.", raw_id)


def save_mapped_order(cur, mapped: MappedOrder) -> int:
    if mapped.venda is None:
        raise ValueError("Mapeamento sem venda para salvar.")
    cur.execute(UPSERT_VENDA_SQL, mapped.venda)
    venda_id = cur.fetchone()["id"]

    cur.execute("DELETE FROM dw.pagamentos WHERE venda_id = %s", (venda_id,))
    for pagamento in mapped.pagamentos:
        cur.execute(
            """
            INSERT INTO dw.pagamentos (
                venda_id,
                loja,
                data_hora,
                numero_cupom,
                numero_pedido,
                forma_pagamento,
                valor_pagamento
            )
            VALUES (
                %(venda_id)s,
                %(loja)s,
                %(data_hora)s,
                %(numero_cupom)s,
                %(numero_pedido)s,
                %(forma_pagamento)s,
                %(valor_pagamento)s
            )
            """,
            {"venda_id": venda_id, **pagamento},
        )

    cur.execute("DELETE FROM dw.produtos WHERE venda_id = %s", (venda_id,))
    for produto in mapped.produtos:
        cur.execute(
            """
            INSERT INTO dw.produtos (
                venda_id,
                loja,
                data_hora,
                numero_cupom,
                numero_pedido,
                tipo_venda,
                tipo_pdv,
                codigo_produto,
                descricao_produto,
                item_type,
                item_id,
                familia_item
            )
            VALUES (
                %(venda_id)s,
                %(loja)s,
                %(data_hora)s,
                %(numero_cupom)s,
                %(numero_pedido)s,
                %(tipo_venda)s,
                %(tipo_pdv)s,
                %(codigo_produto)s,
                %(descricao_produto)s,
                %(item_type)s,
                %(item_id)s,
                %(familia_item)s
            )
            """,
            {"venda_id": venda_id, **produto},
        )

    if mapped.cancelamento is not None:
        cur.execute(
            "SELECT id FROM dw.cancelamentos WHERE venda_id = %s LIMIT 1",
            (venda_id,),
        )
        if cur.fetchone() is None:
            cur.execute(
                """
                INSERT INTO dw.cancelamentos (
                    venda_id,
                    loja,
                    data_hora,
                    numero_cupom,
                    numero_pedido,
                    tipo_venda,
                    tipo_pdv,
                    atendente,
                    total_venda
                )
                VALUES (
                    %(venda_id)s,
                    %(loja)s,
                    %(data_hora)s,
                    %(numero_cupom)s,
                    %(numero_pedido)s,
                    %(tipo_venda)s,
                    %(tipo_pdv)s,
                    %(atendente)s,
                    %(total_venda)s
                )
                """,
                {"venda_id": venda_id, **mapped.cancelamento},
            )
    return venda_id


def mark_error(conn, raw_id: int, message: str) -> None:
    with conn.cursor() as cur:
        cur.execute(MARK_ERROR_SQL, (message[:2000], raw_id))
    conn.commit()


if __name__ == "__main__":
    main()
