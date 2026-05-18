import os
from dataclasses import dataclass

from dotenv import load_dotenv


@dataclass(frozen=True)
class PostgresConfig:
    host: str
    port: int
    dbname: str
    user: str
    password: str


@dataclass(frozen=True)
class KinesisConfig:
    aws_region: str
    stream_name: str
    shard_iterator_type: str
    max_records_per_read: int


@dataclass(frozen=True)
class AppConfig:
    postgres: PostgresConfig
    kinesis: KinesisConfig
    raw_batch_size: int
    processor_sleep_seconds: int
    collector_sleep_seconds: int
    timezone_name: str


def load_config() -> AppConfig:
    load_dotenv()
    return AppConfig(
        postgres=PostgresConfig(
            host=_env("POSTGRES_HOST", "localhost"),
            port=int(_env("POSTGRES_PORT", "5437")),
            dbname=_env("POSTGRES_DB", "brownie_3s"),
            user=_env("POSTGRES_USER", "admin"),
            password=_env("POSTGRES_PASSWORD", "123456"),
        ),
        kinesis=KinesisConfig(
            aws_region=_required_env("AWS_REGION"),
            stream_name=_required_env("KINESIS_STREAM_NAME"),
            shard_iterator_type=_env("SHARD_ITERATOR_TYPE", "LATEST"),
            max_records_per_read=int(_env("MAX_RECORDS_PER_READ", "10")),
        ),
        raw_batch_size=int(_env("RAW_BATCH_SIZE", "100")),
        processor_sleep_seconds=int(_env("PROCESSOR_SLEEP_SECONDS", "5")),
        collector_sleep_seconds=int(_env("COLLECTOR_SLEEP_SECONDS", "3")),
        timezone_name=_env("BUSINESS_TIMEZONE", "America/Fortaleza"),
    )


def _env(name: str, default: str) -> str:
    value = os.getenv(name)
    return value if value not in (None, "") else default


def _required_env(name: str) -> str:
    value = os.getenv(name)
    if value in (None, ""):
        raise ValueError(f"Variavel obrigatoria ausente no .env: {name}")
    return value
