import logging
import time
from typing import Any

from psycopg.types.json import Jsonb

from .config import load_config
from .db import connect
from .kinesis_client import (
    create_client,
    describe_stream,
    get_shard_iterator,
    list_stream_shards,
)
from .utils import custom_properties, extract_payload, parse_record_data, to_text, to_utc_naive


LOGGER = logging.getLogger(__name__)


INSERT_RAW_SQL = """
INSERT INTO raw.kinesis_events (
    shard_id,
    sequence_number,
    partition_key,
    object_type,
    store_code,
    fiscal_id,
    order_code,
    event_datetime,
    payload
)
VALUES (
    %(shard_id)s,
    %(sequence_number)s,
    %(partition_key)s,
    %(object_type)s,
    %(store_code)s,
    %(fiscal_id)s,
    %(order_code)s,
    %(event_datetime)s,
    %(payload)s
)
ON CONFLICT (shard_id, sequence_number) DO NOTHING
"""


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    config = load_config()
    kinesis_client = create_client(config.kinesis)
    summary = describe_stream(kinesis_client, config.kinesis.stream_name)
    LOGGER.info(
        "Stream encontrado: %s status=%s shards=%s",
        summary.get("StreamName"),
        summary.get("StreamStatus"),
        summary.get("OpenShardCount"),
    )
    shards = list_stream_shards(kinesis_client, config.kinesis.stream_name)
    shard_iterators = {
        shard["ShardId"]: get_shard_iterator(
            kinesis_client,
            config.kinesis.stream_name,
            shard["ShardId"],
            config.kinesis.shard_iterator_type,
        )
        for shard in shards
    }
    with connect(config.postgres) as conn:
        LOGGER.info("Collector RAW iniciado com %s shard(s).", len(shard_iterators))
        while True:
            found_records = False
            for shard_id, shard_iterator in list(shard_iterators.items()):
                if not shard_iterator:
                    LOGGER.warning("Shard %s sem proximo iterator.", shard_id)
                    continue
                response = kinesis_client.get_records(
                    ShardIterator=shard_iterator,
                    Limit=config.kinesis.max_records_per_read,
                )
                shard_iterators[shard_id] = response.get("NextShardIterator")
                records = response.get("Records", [])
                if not records:
                    continue
                found_records = True
                LOGGER.info("%s evento(s) lido(s) no shard %s.", len(records), shard_id)
                for record in records:
                    try:
                        insert_raw_event(conn, shard_id, record)
                        conn.commit()
                    except Exception:
                        conn.rollback()
                        LOGGER.exception(
                            "Falha ao salvar evento shard=%s sequence=%s.",
                            shard_id,
                            record.get("SequenceNumber"),
                        )
            if not found_records:
                time.sleep(config.collector_sleep_seconds)


def insert_raw_event(conn, shard_id: str, record: dict[str, Any]) -> None:
    payload, raw_payload, payload_kind = parse_record_data(record["Data"])
    stored_payload = raw_payload
    if payload_kind != "json":
        stored_payload = {"payload_kind": payload_kind, "data": _json_safe(raw_payload)}
        payload = extract_payload(stored_payload)
    if payload is None:
        payload = {}

    props = custom_properties(payload)
    params = {
        "shard_id": shard_id,
        "sequence_number": to_text(record.get("SequenceNumber")),
        "partition_key": to_text(record.get("PartitionKey")),
        "object_type": to_text(payload.get("objectType")),
        "store_code": to_text(payload.get("storeCode")),
        "fiscal_id": to_text(props.get("FISCAL_ID")),
        "order_code": to_text(payload.get("orderCode")),
        "event_datetime": to_utc_naive(payload.get("creationDttm")),
        "payload": Jsonb(stored_payload),
    }
    with conn.cursor() as cur:
        cur.execute(INSERT_RAW_SQL, params)


def _json_safe(value: Any) -> Any:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


if __name__ == "__main__":
    main()
