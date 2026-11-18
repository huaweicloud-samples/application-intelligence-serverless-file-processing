# 实时文件处理：华为云最佳实践

![License](https://img.shields.io/badge/license-MIT--0-blue.svg)

[English](./README.md)
![Huawei Cloud](https://img.shields.io/badge/华为云-最佳实践-ff4d00.svg)
![Terraform](https://img.shields.io/badge/Terraform->=1.5-7B42BC.svg)

> 华为云最佳实践（同构架构，非代码平移）

---

## 简介

事件驱动的实时文件处理架构。当 Markdown 文件上传到 OBS 后，自动触发两条并行处理流水线：**Markdown 转 HTML** 和 **情感分析**。转换结果存入 OBS，情感分析结果存入 GaussDB Cassandra。适用于内容处理平台、舆情分析、文档工作流自动化等场景。

---

## 目录

- [架构图](#架构图)
- [方案亮点](#方案亮点)
- [涉及云服务与费用](#涉及云服务与费用)
- [前置条件](#前置条件)
- [快速开始](#快速开始)
- [分步部署](#分步部署)
- [使用方法与验证](#使用方法与验证)
- [清理资源](#清理资源)
- [详细说明](#详细说明)
- [参考实现](#参考实现)
- [FAQ / 故障排除](#faq--故障排除)
- [贡献指南](#贡献指南)
- [许可证](#许可证)
- [联系方式 / 维护者](#联系方式--维护者)

---

## 架构图

```
用户上传 Markdown 文件
        ↓
┌───────────────────────┐
│     OBS 输入桶         │
│   (obs-file-input)     │
└──────────┬────────────┘
           │ ObjectCreated 事件
           ↓
┌───────────────────────┐
│       SMN Topic       │
│  (obs-notification)   │
└──────────┬────────────┘
           │ 路由分发
     ┌─────┴─────┐
     ↓           ↓
  转换队列      情感队列
 (RocketMQ)   (RocketMQ)
     │           │
     ↓           ↓
┌─────────────────────────────┐
│      FunctionGraph          │
│  ┌─────────┬──────────┐    │
│  │ 转换函数 │ 情感函数  │    │
│  │Python3.9│Python3.9 │    │
│  └────┬────┴────┬─────┘    │
└───────┼─────────┼──────────┘
        │         │
        ↓         ↓
  OBS 输出桶   GaussDB Cassandra
  (HTML文件)   (情感分析结果)
```

> 请求经 SMN 事件路由进入两条 RocketMQ 队列，分别触发 FunctionGraph 转换函数和情感分析函数，结果分别写入 OBS 和 GaussDB。

---

## 方案亮点

- **全 Serverless 架构**：FunctionGraph 按需执行，无需管理服务器
- **事件驱动**：OBS 事件自动触发处理，天然解耦
- **并行处理**：两条独立工作流并发执行，互不阻塞
- **资源优化**：OBS 输入桶 30 天自动过期；函数按调用量结算
- **高可用**：GaussDB Cassandra 3 节点集群 + RocketMQ 队列持久化

---

## 前置条件

- 华为云账号（已实名，具备 OBS、SMN、DMS、GaussDB、FunctionGraph、LTS 创建权限）
- 已配置 `HW_ACCESS_KEY` / `HW_SECRET_KEY` 环境变量（**禁止写入任何文件**）
- 工具版本：`terraform >= 1.5`、`huaweicloud` Terraform Provider `>= 1.60`
- Python >= 3.9（用于本地打包函数代码）
- obsutil（可选，OBS 命令行工具，[下载地址](https://support.huaweicloud.com/utiltg-obs/obs_11_0003.html)）
- 区域约束：本实践以 `cn-north-4`（北京四）为例

---

## 快速开始

```bash
# 1. 克隆仓库
git clone <repo-url>
cd iaas-file-processing-example

# 2. 配置凭证
export HW_ACCESS_KEY="your-access-key"
export HW_SECRET_KEY="your-secret-key"
export HW_REGION="cn-north-4"

# 3. 初始化并预览
cd infra
terraform init
terraform plan -var="db_password=YourStrongPass123!"

# 4. 部署（apply 前请确认费用）
terraform apply -var="db_password=YourStrongPass123!"
```

---

## 分步部署

### 步骤 1: 配置变量

创建 `infra/terraform.tfvars`：

```hcl
region          = "cn-north-4"
stack_name      = "file-refarch"
db_password     = "YourStrongPass123!"
modelarts_endpoint = "https://modelarts.cn-north-4.myhuaweicloud.com"
```

### 步骤 2: 初始化 Terraform

```bash
cd infra
terraform init
# 预期：Terraform has been successfully initialized!
```

### 步骤 3: 预览资源

```bash
terraform plan
# 预期：Plan: 22 to add, 0 to change, 0 to destroy.
```

### 步骤 4: 部署

```bash
terraform apply
# 输入 yes 确认
# 预期：Apply complete! Resources: 22 added.
```

### 步骤 5: 初始化数据库

```bash
# 获取 GaussDB 连接地址
terraform output sentiment_db_connection

# 执行建表脚本
cqlsh <db_host> -u root -p <password> -f ../src/init-db.cql
```

### 步骤 6: 打包并上传函数代码

```bash
cd ../src

# 打包转换函数
zip -r conversion.zip conversion/

# 打包情感分析函数（含适配器）
zip -r sentiment.zip sentiment/ adapter/

# 上传到 OBS 输出桶
obsutil cp conversion.zip obs://<output-bucket>/functions/
obsutil cp sentiment.zip obs://<output-bucket>/functions/
```

### 步骤 7: 配置 ModelArts

1. 在 ModelArts 控制台获取情感分析模型 Endpoint 和 Model ID
2. 在 FunctionGraph 控制台为情感函数配置环境变量 `MODELARTS_MODEL_ID`

---

## 使用方法与验证

### 上传测试文件

```bash
echo "# 产品评价\n\n这是一个**非常好**的产品，我非常喜欢！" > test.md
obsutil cp test.md obs://<input-bucket>/test.md
```

### 验证 HTML 转换（约 10 秒内）

```bash
obsutil ls obs://<output-bucket>/
# 预期：test.html 已生成
obsutil cat obs://<output-bucket>/test.html
```

### 验证情感分析结果

```bash
cqlsh <db_host> -u root -p <password>
# 查询
SELECT * FROM sentiment_analysis.document_sentiment LIMIT 10;
```

预期结果：

| obs_object | overall_sentiment | positive | negative |
|-----------|------------------|----------|----------|
| obs://.../test.md | POSITIVE | 0.95 | 0.02 |

### 查看 LTS 日志

控制台 → LTS → 日志组 → 查看 `file-refarch-conversion` 和 `file-refarch-sentiment` 日志流。

---

## 清理资源

```bash
cd infra
terraform destroy -var="db_password=YourStrongPass123!"
# 预期：Destroy complete! Resources: 22 destroyed.
```

> ⚠️ **必须执行**，否则 GaussDB Cassandra 和 RocketMQ 将持续产生费用。销毁后请到控制台确认无残留资源。

---

## 详细说明

详见 `docs/architecture.md` 与 `docs/deployment-guide.md`。

### 配置项

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `region` | 部署区域 | `cn-north-4` |
| `stack_name` | 资源名前缀 | `file-refarch` |
| `db_password` | GaussDB 管理员密码（必填） | - |
| `modelarts_endpoint` | ModelArts API 地址 | `https://modelarts.cn-north-4.myhuaweicloud.com` |
| `alarm_email` | 告警通知邮箱（可选） | - |

### 环境变量

| 变量 | 转换函数 | 情感函数 | 说明 |
|------|---------|---------|------|
| `TARGET_BUCKET` | ✅ | - | OBS 输出桶 |
| `CONVERSION_QUEUE` | ✅ | - | RocketMQ 转换队列 |
| `SENTIMENT_QUEUE` | - | ✅ | RocketMQ 情感队列 |
| `ROCKETMQ_INSTANCE_ID` | ✅ | ✅ | RocketMQ 实例 ID |
| `MODELARTS_ENDPOINT` | - | ✅ | ModelArts API |
| `SENTIMENT_TABLE` | - | ✅ | GaussDB 表名 |

### 接口说明

本方案为纯事件驱动后端处理系统，不暴露独立 REST API。如需外部 API，可在 OBS 前增加 APIG 网关层。

---

## 参考实现

主要依赖：
- `huaweicloud` Terraform Provider (v1.96.1)
- `markdown` Python 库（Markdown → HTML 转换）
- `huaweicloudsdkobs` Python SDK（OBS 对象操作）
- `huaweicloudsdkcore` Python SDK（华为云 API 签名）

本实践改编自开源参考架构，以同构架构落地到华为云。

---

## FAQ / 故障排除

**Q：部署后函数没有被触发？**

A：按以下顺序排查：
1. 确认 Kafka 触发器已绑定（控制台 → FunctionGraph → 触发器）
2. 确认 SMN 正确订阅了 RocketMQ Topic
3. 查看 LTS 日志确认消息是否到达函数
4. 确认函数环境变量配置正确

**Q：GaussDB 连接失败？**

A：确认：
1. 函数和 GaussDB 在同一 VPC 子网
2. 安全组放通 9042 端口入站
3. `sentiment_db_connection` 输出值正确

**Q：ModelArts NLP 调用失败？**

A：检查：
1. `MODELARTS_ENDPOINT` 和 `MODELARTS_MODEL_ID` 已配置
2. 函数已通过 IAM 委托获得 ModelArts CommonOperations 权限
3. ModelArts 服务在目标区域可用

**Q：如何只启用一条工作流？**

A：从 SMN Topic 取消不需要的队列订阅，或只消费一个 RocketMQ 队列。

---

## 贡献指南

欢迎提交 Issue 与 PR。贡献规范见 [CONTRIBUTING.md](./CONTRIBUTING.md)。

---

## 许可证

本项目基于 [MIT No Attribution (MIT-0)](./LICENSE) 许可证开源。

---

## 联系方式 / 维护者

- 维护者：华为云架构团队
- Issue 反馈：[GitHub Issues](https://github.com/huaweicloud-samples/iaas-file-processing-example/issues)
- 华为云文档：[https://support.huaweicloud.com](https://support.huaweicloud.com)
