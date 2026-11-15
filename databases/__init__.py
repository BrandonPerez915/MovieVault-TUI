"""
Database access and connection management for MovieVault.
Provides thread-safe Singleton access to:
- MongoConnection: MongoDB document store (movies, reviews, users, lists, actors, directors)
- CassandraConnection: Apache Cassandra time-series logs & activity events
- DgraphConnection: Dgraph graph database for social and recommendation graphs
"""
from typing import Dict

from databases.mongodb.connection import MongoConnection
from databases.cassandra.connection import CassandraConnection
from databases.dgraph.connection import DgraphConnection
from databases.connection import BaseConnection


def get_databases_status() -> Dict[str, str]:
    """Returns the health status of all connected database engines."""
    status: Dict[str, str] = {}

    # MongoDB
    try:
        mongo = MongoConnection()
        status["mongodb"] = "INITIALIZED" if mongo.initialized else "STANDBY (Not initialized)"
    except Exception as e:
        status["mongodb"] = f"STANDBY ({type(e).__name__})"

    # Cassandra
    try:
        cass = CassandraConnection()
        status["cassandra"] = "INITIALIZED" if cass.initialized else "STANDBY (Not initialized)"
    except Exception as e:
        status["cassandra"] = f"STANDBY ({type(e).__name__})"

    # Dgraph
    try:
        dg = DgraphConnection()
        status["dgraph"] = "INITIALIZED" if dg.initialized else "STANDBY (Not initialized)"
    except Exception as e:
        status["dgraph"] = f"STANDBY ({type(e).__name__})"

    return status


def close_all_connections() -> None:
    """Closes all active database connections."""
    for conn_cls in (MongoConnection, CassandraConnection, DgraphConnection):
        try:
            conn_cls().close()
        except Exception:
            pass


__all__ = [
    "MongoConnection",
    "CassandraConnection",
    "DgraphConnection",
    "BaseConnection",
    "get_databases_status",
    "close_all_connections",
]
