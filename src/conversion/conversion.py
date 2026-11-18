"""
Conversion Function - 华为云 FunctionGraph 版本
将 Markdown 文件转换为 HTML 并上传到 OBS 输出桶。
从 DMS RocketMQ 队列消费 OBS 事件消息。
"""

import json
import logging
import os
import sys
import tempfile

from aws_lambda_powertools import Logger
from aws_lambda_powertools import Tracer
import markdown

# 华为云 SDK
import obsutil.auth as obs_auth
import obsutil.bucket as obs_bucket

# RocketMQ 消费者
from rocketmq_python.consumer import PushConsumer, ConsumeStatus

# 配置
max_object_size = 104857600  # 100MB

huawei_region = os.environ['HUAWEI_REGION']
conversion_queue = os.getenv('CONVERSION_QUEUE')
target_bucket = os.getenv('TARGET_BUCKET')
log_level = os.getenv('LOG_LEVEL', 'INFO')
rocketmq_instance_id = os.getenv('ROCKETMQ_INSTANCE_ID')

# 华为云 OBS Client
obs_client = obs_auth.ObsClient(
    access_key_id=os.environ.get('HUAWEI_ACCESS_KEY', ''),
    access_key_secret=os.environ.get('HUAWEI_SECRET_KEY', ''),
    server=f'https://obs.{huawei_region}.myhuaweicloud.com'
)

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
        resp = obs_client.getObject(bucket, key_name, downloadPath=local_file)
        result = 'ok'
        tracer.put_annotation('OBJECT_DOWNLOAD', 'SUCCESS')
    except Exception as e:
        tracer.put_annotation('OBJECT_DOWNLOAD', 'FAILURE')
        result = f'Error: obs://{bucket}/{key_name} - {str(e)}'

    return result


@tracer.capture_method
def convert_to_html(file):
    """将 Markdown 文件转换为 HTML"""
    tracer.put_metadata('file', file)

    try:
        with open(file, 'r') as f:
            file_string = f.read()
        tracer.put_annotation('MARKDOWN_CONVERSION', 'SUCCESS')
        return markdown.markdown(file_string)
    except Exception as e:
        logger.error(f'Could not open or read {file}: {str(e)}')
        tracer.put_annotation('MARKDOWN_CONVERSION', 'FAILURE')
        raise


@tracer.capture_method
def upload_html(bucket, key, source_file):
    """上传本地文件到 OBS 桶"""
    tracer.put_metadata('object', f'obs://{bucket}/{key}')

    try:
        resp = obs_client.putFile(bucket, key, source_file)
        if resp.status < 300:
            result = 'ok'
            tracer.put_annotation('OBJECT_UPLOAD', 'SUCCESS')
        else:
            result = f'Error: {resp.errorMessage}'
            tracer.put_annotation('OBJECT_UPLOAD', 'FAILURE')
    except Exception as e:
        tracer.put_annotation('OBJECT_UPLOAD', 'FAILURE')
        logger.error(f'Could not upload {source_file} to {bucket}: {str(e)}')
        result = 'fail'

    return result


def delete_message_from_queue(receipt_handle):
    """从 RocketMQ 队列中删除已消费的消息"""
    # RocketMQ 消费完成后自动 ack，无需手动 delete_message
    # 保留此接口以兼容原代码逻辑
    pass


@tracer.capture_method
@logger.inject_lambda_context
def handler(event, context):
    """
    FunctionGraph 入口，接收 DMS RocketMQ 消息。
    event 格式为 RocketMQ 消息体（JSON 解析）。
    """
    tmpdir = tempfile.mkdtemp()

    try:
        # RocketMQ 推送的消息体
        records = event.get('Records', [])
        for record in records:
            # RocketMQ 消息体格式（JSON 解析）
            try:
                json_body = json.loads(record.get('body', '{}'))
            except json.JSONDecodeError:
                json_body = {'Records': [record]}

            for rec in json_body.get('Records', []):
                bucket_name = rec.get('s3', {}).get('bucket', {}).get('name', '')
                key_name = rec.get('s3', {}).get('object', {}).get('key', '')
                receipt_handle = rec.get('receiptHandle', '')

                if not bucket_name or not key_name:
                    continue

                # 大小检查
                size = check_obs_object_size(bucket_name, key_name)
                if size == 'NaN':
                    logger.error(f'Could not get size for obs://{bucket_name}/{key_name}')
                    continue

                if size >= max_object_size:
                    error_message = f'Source OBS object obs://{bucket_name}/{key_name} '
                    error_message += f'is larger than {max_object_size} (max bytes)'
                    logger.error(error_message)
                    raise Exception('Source OBS object too large')

                local_file = os.path.join(tmpdir, key_name)

                download_status = get_obs_object(bucket_name, key_name, local_file)

                if download_status != 'ok':
                    logger.error(f'Download failure to {local_file}: {download_status}')
                    raise Exception(f'Download failure: {download_status}')

                logger.info(f'Success: Download to {local_file} for conversion')

                # Markdown → HTML
                html_content = convert_to_html(local_file)
                html_filename = os.path.splitext(key_name)[0] + '.html'
                local_html_file = os.path.join(tmpdir, html_filename)

                with open(local_html_file, 'w') as outfile:
                    outfile.write(html_content)

                logger.info(f'Success: Converted obs://{bucket_name}/{key_name} to {local_html_file}')

                # 上传 HTML 到输出桶
                html_upload = upload_html(target_bucket, html_filename, local_html_file)

                if html_upload == 'ok':
                    dst_obs_object = f'obs://{target_bucket}/{html_filename}'
                    logger.info(f'Success: Uploaded {local_html_file} to {dst_obs_object}')
                    # RocketMQ 自动 ack，无需手动删除消息
                else:
                    error_message = f'Could not upload file to obs://{target_bucket}/{html_filename}'
                    logger.error(error_message)
                    raise Exception(error_message)

    finally:
        # 清理临时文件
        import os as _os
        for f in os.listdir(tmpdir):
            try:
                _os.remove(os.path.join(tmpdir, f))
            except OSError as e:
                logger.error(f'Could not delete file: {str(e)}')
        try:
            _os.rmdir(tmpdir)
        except OSError as e:
            logger.debug(f'Could not delete temp dir: {str(e)}')

    return 'ok'
