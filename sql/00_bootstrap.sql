CREATE SCHEMA IF NOT EXISTS raw;
CREATE SCHEMA IF NOT EXISTS staging;
CREATE SCHEMA IF NOT EXISTS intermediate;
CREATE SCHEMA IF NOT EXISTS marts;

SELECT schema_name
FROM information_schema.schemata
WHERE schema_name IN ('raw','staging','intermediate','marts')
ORDER BY schema_name;
