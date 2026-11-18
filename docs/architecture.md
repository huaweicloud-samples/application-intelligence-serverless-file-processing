# 架构说明：实时文件处理

## 架构图

```
用户上传 Markdown 文件
        ↓
  ┌─────────────────┐
  │   OBS 输入桶     │
  │ (obs-file-input) │
  └────────┬────────┘
           │ ObjectCreated 事件
           ↓
  ┌─────────────────┐
  │   SMN 消息通知   │
  │  (SMN Topic)    │
  └────────┬────────┘
           │ 路由分发
     ┌─────┴─────┐
     ↓           ↓
Conversion    Sentiment
  队列          队列
(RocketMQ)   (RocketMQ)
     │           │
     ↓           ↓
 ┌─────────────────────────┐
 │    FunctionGraph        │
 │  ┌─────────┬──────────┐ │
 │  │转换函数  │ 情感函数  │ │
 │  │(Python) │ (Python) │ │
 │  └────┬────┴────┬─────┘ │
 └───────┼─────────┼───────┘
         │         │
         ↓         ↓
   OBS 输出桶    GaussDB Tbase
   (HTML存储)   (情感结果存储)
```

## 核心组件

### 1. OBS 对象存储
- **输入桶**：接收用户上传的 Markdown 文件，配置 SMN 事件通知
- **输出桶**：存储 Markdown 转换后的 HTML 文件
- 生命周期策略：30天后自动清理输入桶文件

### 2. SMN 消息通知服务
- 接收 OBS 事件（ObjectCreated），发布到 Topic
- Topic 同时向两个 RocketMQ 队列订阅分发，实现并行处理

### 3. DMS RocketMQ 消息队列
- **ConversionQueue**：转换工作流队列，触发转换函数
- **SentimentQueue**：情感分析工作流队列，触发情感分析函数
- 每个队列配置死信队列（DLQ），失败消息保留最多5次重试

### 4. FunctionGraph 函数计算
- **转换函数**：从输入桶读取 Markdown，转换为 HTML，上传到输出桶
- **情感分析函数**：读取 Markdown 内容，调用 ModelArts NLP 进行情感分析，存入 GaussDB Tbase
- 均为 Python 3.9 运行时，256MB 内存，10秒超时

### 5. GaussDB Tbase
- Cassandra 架构，存储情感分析结果
- 3节点集群，保证高可用
- Keyspace: `sentiment_analysis`，表名: `document_sentiment`

### 6. LTS 日志服务
- 汇聚两个函数的日志
- 配置告警规则：DLQ 有消息时触发 SMN 邮件通知

## 技术指标

| 指标 | 值 |
|------|-----|
| 最大处理文件 | 100MB |
| 函数超时 | 10秒 |
| 函数内存 | 256MB |
| RocketMQ 重试次数 | 5次 |
| 日志保留 | 7天 |
| 输入桶生命周期 | 30天 |
