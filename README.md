# Real-time File Processing: Huawei Cloud Best Practice

![License](https://img.shields.io/badge/license-MIT--0-blue.svg)

[中文版](./README.cn.md)
![Huawei Cloud](https://img.shields.io/badge/Huawei%20Cloud-Best%20Practice-ff4d00.svg)
![Terraform](https://img.shields.io/badge/Terraform->=1.5-7B42BC.svg)

> A same-shaped architecture landing on Huawei Cloud.

---

## Overview

An event-driven real-time file processing architecture. When a Markdown file is uploaded to OBS, two processing workflows are automatically triggered in parallel: **Markdown-to-HTML conversion** and **sentiment analysis**. Conversion results are stored in OBS, and sentiment analysis results are stored in GaussDB Cassandra. Suitable for content processing platforms, sentiment analysis, and document workflow automation.

---

## Table of Contents

- [Architecture](#architecture)
- [Highlights](#highlights)
- [Cloud Services and Costs](#cloud-services-and-costs)
- [Prerequisites](#prerequisites)
- [Quick Start](#quick-start)
- [Step-by-Step Deployment](#step-by-step-deployment)
- [Usage and Verification](#usage-and-verification)
- [Cleanup](#cleanup)
- [Detailed Documentation](#detailed-documentation)
- [Dependencies and Credits](#dependencies-and-credits)
- [FAQ / Troubleshooting](#faq--troubleshooting)
- [Contributing](#contributing)
- [License](#license)
- [Contact](#contact)

---

## Architecture

```
User uploads Markdown file
        ↓
┌───────────────────────┐
│   OBS Input Bucket    │
│  (obs-file-input)     │
└──────────┬────────────┘
           │ ObjectCreated Event
           ↓
┌───────────────────────┐
│      SMN Topic        │
│ (obs-notification)    │
└──────────┬────────────┘
           │ Route & Fan-out
     ┌─────┴─────┐
     ↓           ↓
Conversion   Sentiment
  Queue        Queue
(RocketMQ)  (RocketMQ)
     │           │
     ↓           ↓
┌─────────────────────────────┐
│      FunctionGraph          │
│  ┌─────────┬──────────┐    │
│  │Converter│ Sentiment │    │
│  │ Function│ Function  │    │
│  │Python3.9│Python3.9  │    │
│  └────┬────┴────┬─────┘    │
└───────┼─────────┼──────────┘
        │         │
        ↓         ↓
  OBS Output  GaussDB Cassandra
  (HTML files)(Sentiment data)
```

> Requests are routed via SMN to two RocketMQ queues, triggering the conversion and sentiment analysis functions in FunctionGraph. Results are written to OBS and GaussDB respectively.

---

## Highlights

- **Fully Serverless**: FunctionGraph executes on demand — no server management
- **Event-Driven**: OBS events trigger processing automatically, naturally decoupled
- **Parallel Processing**: Two independent workflows run concurrently without blocking
- **Resource Efficiency**: OBS auto-expires input files after 30 days; functions are settled per invocation volume
- **High Availability**: GaussDB Cassandra 3-node cluster + RocketMQ queue persistence


---

## Prerequisites

- Huawei Cloud account (verified, with permissions for OBS, SMN, DMS, GaussDB, FunctionGraph, LTS)
- `HW_ACCESS_KEY` / `HW_SECRET_KEY` environment variables configured (**never write credentials to files**, constraint C8)
- Tools: `terraform >= 1.5`, `huaweicloud` Terraform Provider `>= 1.60`
- Python >= 3.9 (for packaging function code locally)
- obsutil (optional, OBS CLI tool, [Download](https://support.huaweicloud.com/utiltg-obs/obs_11_0003.html))
- Region: This practice uses `cn-north-4` (Beijing 4) as an example

---

## Quick Start

```bash
# 1. Clone the repository
git clone <repo-url>
cd iaas-file-processing-example

# 2. Configure credentials
export HW_ACCESS_KEY="your-access-key"
export HW_SECRET_KEY="your-secret-key"
export HW_REGION="cn-north-4"

# 3. Initialize and preview
cd infra
terraform init
terraform plan -var="db_password=YourStrongPass123!"

# 4. Deploy (confirm costs before apply)
terraform apply -var="db_password=YourStrongPass123!"
```

---

## Step-by-Step Deployment

### Step 1: Configure Variables

Create `infra/terraform.tfvars`:

```hcl
region             = "cn-north-4"
stack_name         = "file-refarch"
db_password        = "YourStrongPass123!"
modelarts_endpoint = "https://modelarts.cn-north-4.myhuaweicloud.com"
```

### Step 2: Initialize Terraform

```bash
cd infra
terraform init
# Expected: Terraform has been successfully initialized!
```

### Step 3: Preview Resources

```bash
terraform plan
# Expected: Plan: 22 to add, 0 to change, 0 to destroy.
```

### Step 4: Deploy

```bash
terraform apply
# Type yes to confirm
# Expected: Apply complete! Resources: 22 added.
```

### Step 5: Initialize Database

```bash
# Get GaussDB connection address
terraform output sentiment_db_connection

# Run table creation script
cqlsh <db_host> -u root -p <password> -f ../src/init-db.cql
```

### Step 6: Package and Upload Function Code

```bash
cd ../src

# Package converter function
zip -r conversion.zip conversion/

# Package sentiment function (with adapter)
zip -r sentiment.zip sentiment/ adapter/

# Upload to OBS output bucket
obsutil cp conversion.zip obs://<output-bucket>/functions/
obsutil cp sentiment.zip obs://<output-bucket>/functions/
```

### Step 7: Configure ModelArts

1. Get the sentiment analysis model Endpoint and Model ID from the ModelArts console
2. Configure `MODELARTS_MODEL_ID` as a function environment variable in the FunctionGraph console

---

## Usage and Verification

### Upload a Test File

```bash
echo "# Product Review\n\nThis is an **amazing** product. I love it!" > test.md
obsutil cp test.md obs://<input-bucket>/test.md
```

### Verify HTML Conversion (~10 seconds)

```bash
obsutil ls obs://<output-bucket>/
# Expected: test.html generated
obsutil cat obs://<output-bucket>/test.html
```

### Verify Sentiment Analysis

```bash
cqlsh <db_host> -u root -p <password>
# Query
SELECT * FROM sentiment_analysis.document_sentiment LIMIT 10;
```

Expected result:

| obs_object | overall_sentiment | positive | negative |
|-----------|------------------|----------|----------|
| obs://.../test.md | POSITIVE | 0.95 | 0.02 |

### View LTS Logs

Console → LTS → Log Group → View `file-refarch-conversion` and `file-refarch-sentiment` log streams.

---

## Cleanup

```bash
cd infra
terraform destroy -var="db_password=YourStrongPass123!"
# Expected: Destroy complete! Resources: 22 destroyed.
```

> ⚠️ **Must execute** — GaussDB Cassandra and RocketMQ will keep incurring charges otherwise. Verify no residual resources in the console after destruction.

---

## Detailed Documentation

See `docs/architecture.md` and `docs/deployment-guide.md` for details.

### Configuration

| Variable | Description | Default |
|----------|-------------|---------|
| `region` | Deployment region | `cn-north-4` |
| `stack_name` | Resource name prefix | `file-refarch` |
| `db_password` | GaussDB admin password (required) | - |
| `modelarts_endpoint` | ModelArts API endpoint | `https://modelarts.cn-north-4.myhuaweicloud.com` |
| `alarm_email` | Alarm notification email (optional) | - |

### Environment Variables

| Variable | Converter | Sentiment | Description |
|----------|-----------|-----------|-------------|
| `TARGET_BUCKET` | ✅ | - | OBS output bucket |
| `CONVERSION_QUEUE` | ✅ | - | RocketMQ conversion queue |
| `SENTIMENT_QUEUE` | - | ✅ | RocketMQ sentiment queue |
| `ROCKETMQ_INSTANCE_ID` | ✅ | ✅ | RocketMQ instance ID |
| `MODELARTS_ENDPOINT` | - | ✅ | ModelArts API |
| `SENTIMENT_TABLE` | - | ✅ | GaussDB table name |

### API Interfaces

This solution is a pure event-driven backend processing system with no standalone REST API. To expose an external API, add an APIG gateway layer in front of OBS.

---

## Dependencies and Credits

Key dependencies:
- `huaweicloud` Terraform Provider (v1.96.1)
- `markdown` Python library (Markdown → HTML conversion)
- `huaweicloudsdkobs` Python SDK (OBS object operations)
- `huaweicloudsdkcore` Python SDK (Huawei Cloud API signing)

Credits: This practice is adapted from an open-source reference architecture, replicated with architectural equivalence for Huawei Cloud.

---

## FAQ / Troubleshooting

**Q: Functions are not triggered after deployment?**

A: Troubleshoot in this order:
1. Verify the Kafka trigger is bound (Console → FunctionGraph → Triggers)
2. Verify SMN correctly subscribes to the RocketMQ topics
3. Check LTS logs to confirm messages reached the function
4. Verify function environment variables are configured correctly

**Q: GaussDB connection fails?**

A: Confirm:
1. Function and GaussDB are in the same VPC subnet
2. Security group allows inbound port 9042
3. `sentiment_db_connection` output value is correct

**Q: ModelArts NLP call fails?**

A: Check:
1. `MODELARTS_ENDPOINT` and `MODELARTS_MODEL_ID` are configured
2. Function has ModelArts CommonOperations permission via IAM agency
3. ModelArts service is available in the target region

**Q: Can I enable only one workflow?**

A: Yes. Remove the unwanted queue subscription from the SMN topic, or only consume from one RocketMQ queue.

---

## Contributing

Contributions are welcome! Please read [CONTRIBUTING.md](./CONTRIBUTING.md) before submitting pull requests.

---

## License

This project is open-sourced under the [MIT No Attribution (MIT-0)](./LICENSE) license.

---

## Contact

- Maintainer: Huawei Cloud Architect Team
- Issue Tracker: [GitHub Issues](https://github.com/huaweicloud-samples/iaas-file-processing-example/issues)
- Huawei Cloud Docs: [https://support.huaweicloud.com](https://support.huaweicloud.com)
