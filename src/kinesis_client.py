import boto3
from botocore.exceptions import BotoCoreError, ClientError

from .config import KinesisConfig


class KinesisAccessError(RuntimeError):
    pass


def create_client(config: KinesisConfig):
    return boto3.client("kinesis", region_name=config.aws_region)


def describe_stream(kinesis_client, stream_name: str) -> dict:
    try:
        response = kinesis_client.describe_stream_summary(StreamName=stream_name)
    except ClientError as exc:
        _raise_friendly_error(exc, "DescribeStreamSummary")
    except BotoCoreError as exc:
        raise RuntimeError(f"Erro ao acessar stream {stream_name}: {exc}") from exc
    return response["StreamDescriptionSummary"]


def list_stream_shards(kinesis_client, stream_name: str) -> list[dict]:
    shards = []
    next_token = None
    while True:
        try:
            if next_token:
                response = kinesis_client.list_shards(NextToken=next_token)
            else:
                response = kinesis_client.list_shards(StreamName=stream_name)
        except ClientError as exc:
            _raise_friendly_error(exc, "ListShards")
        shards.extend(response.get("Shards", []))
        next_token = response.get("NextToken")
        if not next_token:
            break
    return shards


def get_shard_iterator(
    kinesis_client,
    stream_name: str,
    shard_id: str,
    iterator_type: str,
) -> str:
    try:
        response = kinesis_client.get_shard_iterator(
            StreamName=stream_name,
            ShardId=shard_id,
            ShardIteratorType=iterator_type,
        )
    except ClientError as exc:
        _raise_friendly_error(exc, "GetShardIterator")
    return response["ShardIterator"]


def _raise_friendly_error(exc: ClientError, operation: str) -> None:
    error_code = exc.response.get("Error", {}).get("Code", "")
    if error_code in {"AccessDeniedException", "AccessDenied"}:
        raise KinesisAccessError(
            "Credencial AWS carregada, mas sem permissao para "
            f"kinesis:{operation}."
        ) from exc
    raise
