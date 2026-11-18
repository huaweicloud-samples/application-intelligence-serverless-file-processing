# 部署指导书：实时文件处理

## 前置要求

- 华为云账号（已开通以下服务）：OBS、SMN、DMS RocketMQ、GaussDB Tbase、FunctionGraph、LTS
- Terraform >= 1.0.0
- Python 3.9+
- 函数代码打包工具（可选）

## 步骤 1：配置环境变量

```bash
export HUAWEI_ACCESS_KEY="your-access-key"
export HUAWEI_SECRET_KEY="your-secret-key"
export HUAWEI_REGION="cn-north-4"
```

## 步骤 2：初始化 Terraform

```bash
cd infra
terraform init
```

## 步骤 3：配置变量

创建 `terraform.tfvars`：

```hcl
region      = "cn-north-4"
stack_name  = "file-refarch"
alarm_email = "your-email@example.com"
```

## 步骤 4：部署

```bash
terraform plan
terraform apply
```

部署输出：
```
input_bucket           = "file-refarch-cn-north-4-input"
output_bucket          = "file-refarch-cn-north-4-output"
conversion_function_urn = "urn:fss:cn-north-4:xxx:function:default:file-refarch-conversion"
sentiment_function_urn  = "urn:fss:cn-north-4:xxx:function:default:file-refarch-sentiment"
sentiment_db_connection = "192.168.1.100:9042"
```

## 步骤 5：打包函数代码

```bash
# 打包转换函数
cd ../src
zip -r conversion.zip conversion/

# 打包情感分析函数（含适配器）
zip -r sentiment.zip sentiment/ adapter/

# 上传到 OBS（通过控制台或 obsutil）
obsutil upload conversion.zip obs://<output-bucket>/functions/
obsutil upload sentiment.zip obs://<output-bucket>/functions/
```

## 步骤 6：配置 ModelArts NLP

1. 在 ModelArts 控制台创建情感分析模型，或使用内置 NLP 服务
2. 获取 ModelArts Endpoint 和 Model ID
3. 在 FunctionGraph 环境变量中配置：
   ```
   MODELARTS_ENDPOINT=https://modelarts.cn-north-4.myhuaweicloud.com
   MODELARTS_MODEL_ID=your-model-id
   ```

## 步骤 7：验证部署

1. 上传测试文件到输入桶：
   ```bash
   echo "# Hello World\n\nThis is a **test** document." | tee test.md
   obsutil cp test.md obs://<input-bucket>/test.md
   ```

2. 检查转换函数输出（HTML 文件应在输出桶中）

3. 检查情感分析结果（登录 GaussDB Tbase 查询 `sentiment_analysis.document_sentiment` 表）

4. 查看 LTS 日志：
   ```bash
   open log stream --group-id <lts-group-id> --stream-name file-refarch-conversion
   ```

## 注意事项

- **凭证管理**：AK/SK 必须通过环境变量或 FunctionGraph 配置注入，不要硬编码
- **RocketMQ 触发器**：首次部署后需在控制台确认触发器绑定到函数
- **GaussDB 连接**：Cassandra contact points 从 Terraform 输出获取，填入函数环境变量 `CASSANDRA_CONTACT_POINTS`
- **ModelArts**：情感分析 API 按调用量结算，注意预算设置
