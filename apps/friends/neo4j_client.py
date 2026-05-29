from django.conf import settings
from neo4j import GraphDatabase


class Neo4jClient:
    """Small singleton wrapper around the official Neo4j Python driver."""

    _driver = None

    @classmethod
    def driver(cls):
        if cls._driver is None:
            cls._driver = GraphDatabase.driver(
                settings.NEO4J_URI,
                auth=(settings.NEO4J_USERNAME, settings.NEO4J_PASSWORD),
            )
        return cls._driver

    @classmethod
    def execute(cls, query: str, **params):
        records, _, _ = cls.driver().execute_query(
            query,
            **params,
            database_=getattr(settings, "NEO4J_DATABASE", "neo4j"),
        )
        return records

    @classmethod
    def close(cls):
        if cls._driver is not None:
            cls._driver.close()
            cls._driver = None
