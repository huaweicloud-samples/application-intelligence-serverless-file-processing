"""
Sentiment Function - 华为云 FunctionGraph 版本
对 Markdown 文件进行情感分析，结果存入 GaussDB Tbase。
从 DMS RocketMQ 队列消费 OBS 事件消息。
"""

import json
import logging
import os
import tempfile
from datetime import datetime

from aws_lambda_powertools import Logger
from aws_lambda_powertools import Tracer

# 华为云 SDK
import obsutil.auth as obs_auth
from cassandra.cluster import Cluster
from cassandra.auth import PlainTextAuthProvider

# ModelArts 情感分析适配器
from adapter.model_adapter import create_comprehend_client

# 配置
max_object_size = 104857600  # 100MB

huawei_region = os.environ['HUAWEI_REGION']
s_table = os.getenv('SENTIMENT_TABLE')
s_queue = os.getenv('SENTIMENT_QUEUE')
log_level = os.getenv('LOG_LEVEL', 'INFO')
rocketmq_instance_id = os.getenv('ROCKETMQ_INSTANCE_ID')

# 华为云 OBS Client
obs_client = obs_auth.ObsClient(
    access_key_id=os.environ.get('HUAWEI_ACCESS_KEY', ''),
    access_key_secret=os.environ.get('HUAWEI_SECRET_KEY', ''),
    server=f'https://obs.{huawei_region}.myhuaweicloud.com'
)

# 华为云 GaussDB Cassandra 连接
cassandra_contact_points = os.environ.get('CASSANDRA_CONTACT_POINTS', '').split(',')
cassandra_username = os.environ.get('CASSANDRA_USERNAME', 'root')
cassandra_password = os.environ.get('CASSANDRA_PASSWORD', '')

_auth_provider = PlainTextAuthProvider(username=cassandra_username, password=cassandra_password)
_cassandra_cluster = Cluster(cassandra_contact_points, auth_provider=_auth_provider)
_cassandra_session = _cassandra_cluster.connect()

# 情感分析适配器
comprehend_client = create_comprehend_client(region_name=huawei_region)

logger = Logger()
tracer = Tracer()


@tracer.capture_method
def check_obs_object_size(bucket, key_name):
    """获取 OBS 对象大小"""
    tracer.put_metadata('object', f'obs://{bucket}/{key_name}')

    try:
        resp = obs_client.getObjectMetadata(bucket, key_name)
        size = int(resp.body.contentLength)
        tracer.put_metadata('object_size', size)
    except Exception as e:
        logger.error(f'Error: {str(e)}')
        size = 'NaN'
        tracer.put_metadata('object_size', size)

    return size


@tracer.capture_method
def get_obs_object(bucket, key_name, local_file):
    """从 OBS 下载对象到本地文件"""
    tracer.put_metadata('object', f'obs://{bucket}/{key_name}')

    try:
        obs_client.getObject(bucket, key_name, downloadPath=local_file)
        result = 'ok'
        tracer.put_annotation('OBJECT_DOWNLOAD', 'SUCCESS')
    except Exception as e:
        tracer.put_annotation('OBJECT_DOWNLOAD', 'FAILURE')
        result = f'Error: obs://{bucket}/{key_name} - {str(e)}'

    return result


@tracer.capture_method
def put_sentiment(obs_object, sentiment):
    """将情感分析结果存入 GaussDB Cassandra"""
    try:
        keyspace, table_name = s_table.split(':')[0], s_table.split(':')[1].split('.')[-1]

        query = f"""
        INSERT INTO {keyspace}.{table_name}
        (obs_object, last_modified, overall_sentiment, positive, negative, neutral, mixed)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """
        prepared = _cassandra_session.prepare(query)
        _cassandra_session.execute(prepared, (
            obs_object,
            datetime.utcnow().isoformat(),
            sentiment['Sentiment'],
            str(sentiment['SentimentScore']['Positive']),
            str(sentiment['SentimentScore']['Negative']),
            str(sentiment['SentimentScore']['Neutral']),
            str(sentiment['SentimentScore']['Mixed'])
        ))

        tracer.put_annotation('PUT_SENTIMENT_TO_DB', 'SUCCESS')
        result = 'ok'
    except Exception as e:
        tracer.put_annotation('PUT_SENTIMENT_TO_DB', 'FAILURE')
        result = f'Error: {str(e)}'
        logger.error(result)

    return result


@tracer.capture_method
@logger.inject_lambda_context
def handler(event, context):
    """
    FunctionGraph 入口，接收 DMS RocketMQ 消息。
    """
    tmpdir = tempfile.mkdtemp()

    try:
        records = event.get('Records', [])
        for record in records:
            try:
                json_body = json.loads(record.get('body', '{}'))
            except json.JSONDecodeError:
                json_body = {'Records': [record]}

            for rec in json_body.get('Records', []):
                bucket_name = rec.get('s3', {}).get('bucket', {}).get('name', '')
                key_name = rec.get('s3', {}).get('object', {}).get('key', '')

                if not bucket_name or not key_name:
                    continue

                size = check_obs_object_size(bucket_name, key_name)

                if size == 'NaN':
                    logger.error(f'Could not get size for obs://{bucket_name}/{key_name}')
                    continue

                if size >= max_object_size:
                    error_message = f'Source OBS object obs://{bucket_name}/{key_name} '
                    error_message += f'is larger than {max_object_size} (max bytes)'
                    logger.error(error_message)
                    raise Exception(error_message)

                local_file = os.path.join(tmpdir, key_name)

                download_status = get_obs_object(bucket_name, key_name, local_file)

                if download_status != 'ok':
                    logger.error(f'Download failure to {local_file}: {download_status}')
                    raise Exception(f'Download failure: {download_status}')

                logger.info(f'Download to {local_file} for sentiment analysis')

                # 读取文件内容
                with open(local_file, 'r') as f:
                    md_contents = f.read()

                # 情感分析（通过 ModelArts 适配器）
                sentiment_result = comprehend_client.detect_sentiment(
                    Text=md_contents,
                    LanguageCode='en'
                )

                overall_sentiment = sentiment_result['Sentiment']
                sentiment_score = sentiment_result['SentimentScore']

                logger.info(f'{overall_sentiment} ({sentiment_score})')

                source_obs_object = f'obs://{bucket_name}/{key_name}'

                put_result = put_sentiment(source_obs_object, sentiment_result)

                if put_result == 'ok':
                    logger.info(f'Put sentiment to {s_table}')
                    # RocketMQ 自动 ack
                else:
                    logger.error(f'Could not put sentiment to {s_table}: {put_result}')
                    raise Exception(put_result)

    finally:
        import os as _os
        for f in os.listdir(tmpdir):
            try:
                _os.remove(os.path.join(tmpdir, f))
            except OSError as e:
                logger.error(f'Could not delete file: {str(e)}')
        try:
            _os.rmdir(tmpdir)
        except OSError:
            pass

    return 'ok'
