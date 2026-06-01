# apps/accounts/management/commands/sync_accounts_neo4j.py
from django.core.management.base import BaseCommand

from apps.accounts.neo4j_sync import (
    setup_account_graph_schema,
    bulk_sync_accounts_to_neo4j,
)


class Command(BaseCommand):
    help = "Sync all MySQL accounts/users/profiles to Neo4j graph database."

    def add_arguments(self, parser):
        parser.add_argument(
            "--batch-size",
            type=int,
            default=500,
            help="Number of users per Neo4j batch write.",
        )

    def handle(self, *args, **options):
        batch_size = options["batch_size"]

        self.stdout.write(self.style.WARNING("Setting up Neo4j account schema..."))
        setup_account_graph_schema()

        self.stdout.write(self.style.WARNING("Syncing accounts to Neo4j..."))
        total = bulk_sync_accounts_to_neo4j(batch_size=batch_size)

        self.stdout.write(
            self.style.SUCCESS(f"Synced {total} accounts to Neo4j.")
        )