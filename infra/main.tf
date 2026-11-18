# =============================================
# Huawei Cloud Best Practice: Real-time File Processing
# IaC: Terraform + huaweicloud Provider (v1.96.1)
# =============================================

terraform {
  required_version = ">= 1.5.0"
  required_providers {
    huaweicloud = {
      source  = "huaweicloud/huaweicloud"
      version = ">= 1.60"
    }
  }
}

provider "huaweicloud" {
  region = var.region
}

# =====================
# Variables
# =====================
variable "region" {
  description = "Huawei Cloud region"
  type        = string
  default     = "cn-north-4"
}

variable "stack_name" {
  description = "Resource name prefix"
  type        = string
  default     = "file-refarch"
}

variable "alarm_email" {
  description = "Alarm notification email"
  type        = string
  default     = ""
}

variable "modelarts_endpoint" {
  description = "ModelArts NLP API endpoint"
  type        = string
  default     = "https://modelarts.cn-north-4.myhuaweicloud.com"
}

variable "db_password" {
  description = "GaussDB Tbase admin password (8-32 chars, upper+lower+digit+special)"
  type        = string
  sensitive   = true
}

# =====================
# 1. VPC Network
# =====================
resource "huaweicloud_vpc" "main" {
  name = "${var.stack_name}-vpc"
  cidr = "10.0.0.0/16"
}

resource "huaweicloud_vpc_subnet" "main" {
  name          = "${var.stack_name}-subnet"
  vpc_id        = huaweicloud_vpc.main.id
  cidr          = "10.0.1.0/24"
  gateway_ip    = "10.0.1.1"
  primary_dns   = "100.125.1.250"
  secondary_dns = "100.125.129.250"
}

# =====================
# 2. Security Group
# =====================
resource "huaweicloud_networking_secgroup" "main" {
  name        = "${var.stack_name}-sg"
  description = "File Processing Security Group"
}

resource "huaweicloud_networking_secgroup_rule" "allow_internal" {
  direction         = "ingress"
  ethertype         = "IPv4"
  security_group_id = huaweicloud_networking_secgroup.main.id
  remote_ip_prefix  = "10.0.0.0/16"
}

# =====================
# 3. OBS Buckets
# =====================
resource "huaweicloud_obs_bucket" "input" {
  bucket        = "${var.stack_name}-${var.region}-input"
  acl           = "private"
  storage_class = "STANDARD"

  lifecycle_rule {
    name    = "cleanup-old-files"
    enabled = true
    prefix  = ""

    expiration {
      days = 30
    }
  }
}

resource "huaweicloud_obs_bucket" "output" {
  bucket        = "${var.stack_name}-${var.region}-output"
  acl           = "private"
  storage_class = "STANDARD"
}

# =====================
# 4. SMN Topic (OBS event routing)
# =====================
resource "huaweicloud_smn_topic" "main" {
  name         = "${var.stack_name}-obs-notification"
  display_name = "OBS Object Created Notification"
}

# Authorize OBS to publish events to SMN
resource "huaweicloud_obs_bucket_policy" "smn_notify" {
  bucket = huaweicloud_obs_bucket.input.bucket

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "SMNPublish"
        Effect    = "Allow"
        Principal = { Service = "obs.cn-north-4.myhuaweicloud.com" }
        Action    = ["SMN:Publish"]
        Resource  = huaweicloud_smn_topic.main.topic_urn
      }
    ]
  })
}

# =====================
# 5. DMS RocketMQ (message queues)
# =====================
resource "huaweicloud_dms_rocketmq_instance" "main" {
  name               = "${var.stack_name}-rocketmq"
  engine_version     = "4.8.0"
  flavor_id          = "c6.2u4g.cluster"
  broker_num         = 1
  storage_space      = 300
  storage_spec_code  = "dms.physical.storage.high"
  vpc_id             = huaweicloud_vpc.main.id
  subnet_id          = huaweicloud_vpc_subnet.main.id
  security_group_id  = huaweicloud_networking_secgroup.main.id
  availability_zones = ["cn-north-4a", "cn-north-4b"]
}

resource "huaweicloud_dms_rocketmq_topic" "conversion_queue" {
  instance_id = huaweicloud_dms_rocketmq_instance.main.id
  name        = "${var.stack_name}-conversion-queue"
  permission  = "sub"
  queue_num   = 4
}

resource "huaweicloud_dms_rocketmq_topic" "sentiment_queue" {
  instance_id = huaweicloud_dms_rocketmq_instance.main.id
  name        = "${var.stack_name}-sentiment-queue"
  permission  = "sub"
  queue_num   = 4
}

resource "huaweicloud_dms_rocketmq_consumer_group" "conversion" {
  instance_id     = huaweicloud_dms_rocketmq_instance.main.id
  name            = "${var.stack_name}-conversion-group"
  retry_max_times = 5
}

resource "huaweicloud_dms_rocketmq_consumer_group" "sentiment" {
  instance_id     = huaweicloud_dms_rocketmq_instance.main.id
  name            = "${var.stack_name}-sentiment-group"
  retry_max_times = 5
}

# =====================
# 6. GaussDB Cassandra (sentiment result storage)
# =====================
resource "huaweicloud_gaussdb_cassandra_instance" "sentiment_db" {
  name              = "${var.stack_name}-sentiment-db"
  flavor            = "geminidb.cassandra.xlarge.4"
  password          = var.db_password
  vpc_id            = huaweicloud_vpc.main.id
  subnet_id         = huaweicloud_vpc_subnet.main.id
  security_group_id = huaweicloud_networking_secgroup.main.id
  availability_zone = "cn-north-4a"
  volume_size       = 100
  node_num          = 3

  datastore {
    engine         = "cassandra"
    storage_engine = "rocksDB"
    version        = "3.11"
  }
}

# NOTE: GaussDB Cassandra does not support table creation via Terraform.
# After deployment, run the init script manually:
#   cqlsh <db_host> -u root -p <password> -f src/init-db.cql

# =====================
# 7. FunctionGraph Functions
# =====================
resource "huaweicloud_fgs_function" "conversion" {
  name        = "${var.stack_name}-conversion"
  app         = "default"
  runtime     = "Python3.9"
  handler     = "conversion.handler"
  memory_size = 256
  timeout     = 10
  code_type   = "zip"
  code_url    = "https://${huaweicloud_obs_bucket.output.bucket}.obs.${var.region}.myhuaweicloud.com/functions/conversion.zip"

  vpc_id     = huaweicloud_vpc.main.id
  network_id = huaweicloud_vpc_subnet.main.id

  user_data = jsonencode({
    TARGET_BUCKET           = huaweicloud_obs_bucket.output.bucket
    CONVERSION_QUEUE        = huaweicloud_dms_rocketmq_topic.conversion_queue.name
    ROCKETMQ_INSTANCE_ID    = huaweicloud_dms_rocketmq_instance.main.id
    LOG_LEVEL               = "INFO"
    POWERTOOLS_SERVICE_NAME = "conversion-service"
  })
}

resource "huaweicloud_fgs_function" "sentiment" {
  name        = "${var.stack_name}-sentiment"
  app         = "default"
  runtime     = "Python3.9"
  handler     = "sentiment.handler"
  memory_size = 256
  timeout     = 10
  code_type   = "zip"
  code_url    = "https://${huaweicloud_obs_bucket.output.bucket}.obs.${var.region}.myhuaweicloud.com/functions/sentiment.zip"

  vpc_id     = huaweicloud_vpc.main.id
  network_id = huaweicloud_vpc_subnet.main.id

  user_data = jsonencode({
    SENTIMENT_TABLE         = "sentiment_analysis.document_sentiment"
    SENTIMENT_QUEUE         = huaweicloud_dms_rocketmq_topic.sentiment_queue.name
    ROCKETMQ_INSTANCE_ID    = huaweicloud_dms_rocketmq_instance.main.id
    MODELARTS_ENDPOINT      = var.modelarts_endpoint
    LOG_LEVEL               = "INFO"
    POWERTOOLS_SERVICE_NAME = "sentiment-service"
  })
}

# =====================
# 8. FGS Triggers (Kafka/RocketMQ -> FunctionGraph)
# =====================
resource "huaweicloud_fgs_trigger" "conversion" {
  function_urn = huaweicloud_fgs_function.conversion.urn
  type         = "KAFKA"

  kafka {
    instance_id = huaweicloud_dms_rocketmq_instance.main.id
    topic_ids   = [huaweicloud_dms_rocketmq_topic.conversion_queue.name]
  }
}

resource "huaweicloud_fgs_trigger" "sentiment" {
  function_urn = huaweicloud_fgs_function.sentiment.urn
  type         = "KAFKA"

  kafka {
    instance_id = huaweicloud_dms_rocketmq_instance.main.id
    topic_ids   = [huaweicloud_dms_rocketmq_topic.sentiment_queue.name]
  }
}

# =====================
# 9. LTS Log Groups
# =====================
resource "huaweicloud_lts_group" "main" {
  group_name  = "${var.stack_name}-lts-group"
  ttl_in_days = 7
}

resource "huaweicloud_lts_stream" "conversion" {
  group_id    = huaweicloud_lts_group.main.id
  stream_name = "${var.stack_name}-conversion"
}

resource "huaweicloud_lts_stream" "sentiment" {
  group_id    = huaweicloud_lts_group.main.id
  stream_name = "${var.stack_name}-sentiment"
}

# =====================
# 10. IAM Agency (function access to OBS/DMS/GaussDB)
# =====================
resource "huaweicloud_identity_agency" "function_access" {
  name                   = "${var.stack_name}-function-access"
  delegated_service_name = "op_svc_cffg"
  domain_roles = [
    "OBS Operator",
    "DMS FullAccess",
    "GeminiDB FullAccess",
    "ModelArts CommonOperations",
  ]
}

# =====================
# Outputs
# =====================
output "input_bucket" {
  description = "Input OBS bucket name"
  value       = huaweicloud_obs_bucket.input.bucket
}

output "output_bucket" {
  description = "Output OBS bucket name"
  value       = huaweicloud_obs_bucket.output.bucket
}

output "conversion_function_urn" {
  description = "Conversion function URN"
  value       = huaweicloud_fgs_function.conversion.urn
}

output "sentiment_function_urn" {
  description = "Sentiment function URN"
  value       = huaweicloud_fgs_function.sentiment.urn
}

output "sentiment_db_connection" {
  description = "GaussDB connection info"
  value       = huaweicloud_gaussdb_cassandra_instance.sentiment_db.private_ips
}

output "lts_group_id" {
  description = "LTS log group ID"
  value       = huaweicloud_lts_group.main.id
}

output "rocketmq_instance_id" {
  description = "DMS RocketMQ instance ID"
  value       = huaweicloud_dms_rocketmq_instance.main.id
}
