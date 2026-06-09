-- Runs once when the postgres container first initialises.
-- kb_app is already created by POSTGRES_DB in docker-compose.yml.
CREATE DATABASE kb_search    OWNER kb_user;
CREATE DATABASE kb_langgraph OWNER kb_user;
