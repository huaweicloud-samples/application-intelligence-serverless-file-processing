-- GaussDB Cassandra (GeminiDB) initialization script
-- Run after terraform apply:
--   cqlsh <db_host> -u root -p <password> -f src/init-db.cql

CREATE KEYSPACE IF NOT EXISTS sentiment_analysis
  WITH replication = {'class': 'SimpleStrategy', 'replication_factor': 3};

USE sentiment_analysis;

CREATE TABLE IF NOT EXISTS document_sentiment (
    obs_object        TEXT PRIMARY KEY,
    last_modified     TEXT,
    overall_sentiment TEXT,
    positive          TEXT,
    negative          TEXT,
    neutral           TEXT,
    mixed             TEXT
);
