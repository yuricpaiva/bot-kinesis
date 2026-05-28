import argparse
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
DEFAULT_CAUGHT_UP_IDLE_ROUNDS = 3


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
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--until-caught-up",
        action="store_true",
        help="Le ate alcancar o fim do stream e encerra. Use com SHARD_ITERATOR_TYPE=TRIM_HORIZON.",
    )
    parser.add_argument(
        "--caught-up-idle-rounds",
        type=int,
        default=DEFAULT_CAUGHT_UP_IDLE_ROUNDS,
        help="Rodadas sem registros e sem atraso antes de encerrar no modo --until-caught-up.",
    )
    args = parser.parse_args()

    collect_raw(
        until_caught_up=args.until_caught_up,
        caught_up_idle_rounds=args.caught_up_idle_rounds,
    )


def collect_raw(until_caught_up: bool = False, caught_up_idle_rounds: int = DEFAULT_CAUGHT_UP_IDLE_ROUNDS) -> None:
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
        idle_caught_up_rounds = 0
        while True:
            found_records = False
            max_millis_behind_latest = 0
            for shard_id, shard_iterator in list(shard_iterators.items()):
                if not shard_iterator:
                    LOGGER.warning("Shard %s sem proximo iterator.", shard_id)
                    continue
                response = kinesis_client.get_records(
                    ShardIterator=shard_iterator,
                    Limit=config.kinesis.max_records_per_read,
                )
                shard_iterators[shard_id] = response.get("NextShardIterator")
                millis_behind_latest = response.get("MillisBehindLatest")
                if millis_behind_latest is not None:
                    max_millis_behind_latest = max(max_millis_behind_latest, millis_behind_latest)
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
            if until_caught_up:
                active_iterators = [iterator for iterator in shard_iterators.values() if iterator]
                if not found_records and max_millis_behind_latest == 0:
                    idle_caught_up_rounds += 1
                    LOGGER.info(
                        "Sem novos eventos e sem atraso no Kinesis (%s/%s).",
                        idle_caught_up_rounds,
                        caught_up_idle_rounds,
                    )
                else:
                    idle_caught_up_rounds = 0
                if not active_iterators or idle_caught_up_rounds >= caught_up_idle_rounds:
                    LOGGER.info("Collector RAW alcancou o fim disponivel do Kinesis e sera encerrado.")
                    break
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
