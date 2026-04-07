"""Benchmark query path and websocket fanout path for realtime posts module."""

from __future__ import annotations

import json
import statistics
import time
import uuid

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db.models import Count

from apps.posts.models import Comment
from apps.posts.models import CommentReaction
from apps.posts.models import Post

User = get_user_model()


def _percentile(sorted_values: list[float], percentile: float) -> float:
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return sorted_values[0]

    rank = (len(sorted_values) - 1) * percentile
    lower = int(rank)
    upper = min(lower + 1, len(sorted_values) - 1)
    weight = rank - lower
    return sorted_values[lower] * (1 - weight) + sorted_values[upper] * weight


async def _fanout_case(channel_layer, *, subscribers: int, iterations: int) -> dict:
    group_name = f"bench_group_{uuid.uuid4().hex}"
    channel_names = []

    for _ in range(subscribers):
        channel_name = await channel_layer.new_channel("bench.")
        await channel_layer.group_add(group_name, channel_name)
        channel_names.append(channel_name)

    latencies_ms = []
    started_at = time.perf_counter()
    for index in range(iterations):
        t0 = time.perf_counter()
        await channel_layer.group_send(
            group_name,
            {
                "type": "benchmark.message",
                "payload": {"iteration": index},
            },
        )

        for channel_name in channel_names:
            await channel_layer.receive(channel_name)

        latencies_ms.append((time.perf_counter() - t0) * 1000)

    elapsed_seconds = time.perf_counter() - started_at

    for channel_name in channel_names:
        await channel_layer.group_discard(group_name, channel_name)

    latencies_ms.sort()
    total_messages = subscribers * iterations
    throughput = total_messages / elapsed_seconds if elapsed_seconds > 0 else 0.0

    return {
        "subscribers": subscribers,
        "iterations": iterations,
        "messages": total_messages,
        "elapsed_seconds": round(elapsed_seconds, 4),
        "throughput_msg_per_sec": round(throughput, 2),
        "latency_ms": {
            "p50": round(_percentile(latencies_ms, 0.50), 2),
            "p95": round(_percentile(latencies_ms, 0.95), 2),
            "avg": round(statistics.mean(latencies_ms), 2) if latencies_ms else 0.0,
        },
    }


class Command(BaseCommand):
    help = "Benchmark realtime query and websocket fanout paths"

    def add_arguments(self, parser):
        parser.add_argument("--subscribers", nargs="+", type=int, default=[50, 200])
        parser.add_argument("--iterations", type=int, default=10)
        parser.add_argument("--query-iterations", type=int, default=20)
        parser.add_argument("--query-limit", type=int, default=200)
        parser.add_argument("--json", action="store_true", dest="as_json")

    def _ensure_seed_data(self, minimum_comments: int = 300) -> Post:
        user, _ = User.objects.get_or_create(
            email="benchmark@example.com",
            defaults={
                "username": "benchmark-user",
                "is_active": True,
            },
        )
        if not user.is_active:
            user.is_active = True
            user.save(update_fields=["is_active"])

        post, _ = Post.objects.get_or_create(
            author=user,
            content="Benchmark post",
        )

        existing = Comment.objects.filter(post=post).count()
        missing = max(minimum_comments - existing, 0)
        if missing:
            Comment.objects.bulk_create(
                [
                    Comment(post=post, author=user, content=f"benchmark comment {index}")
                    for index in range(existing, existing + missing)
                ],
                batch_size=200,
            )
            Post.objects.filter(id=post.id).update(comments_count=Comment.objects.filter(post=post).count())

        return post

    def _run_query_benchmark(self, *, post: Post, iterations: int, limit: int) -> dict:
        latencies_ms = []

        for _ in range(iterations):
            t0 = time.perf_counter()
            list(
                Comment.objects.select_related("author")
                .filter(post=post)
                .order_by("created_at")[:limit]
            )
            list(
                CommentReaction.objects.filter(comment__post=post)
                .values("reaction_type")
                .annotate(count=Count("id"))
            )
            latencies_ms.append((time.perf_counter() - t0) * 1000)

        latencies_ms.sort()
        return {
            "iterations": iterations,
            "query_limit": limit,
            "latency_ms": {
                "p50": round(_percentile(latencies_ms, 0.50), 2),
                "p95": round(_percentile(latencies_ms, 0.95), 2),
                "avg": round(statistics.mean(latencies_ms), 2) if latencies_ms else 0.0,
            },
        }

    def handle(self, *args, **options):
        iterations = int(options["iterations"])
        query_iterations = int(options["query_iterations"])
        query_limit = int(options["query_limit"])
        subscriber_sizes = [value for value in options["subscribers"] if value > 0]

        if not subscriber_sizes:
            raise ValueError("At least one positive subscriber value is required")

        post = self._ensure_seed_data(minimum_comments=max(300, query_limit))
        query_metrics = self._run_query_benchmark(
            post=post,
            iterations=query_iterations,
            limit=query_limit,
        )

        channel_layer = get_channel_layer()
        if channel_layer is None:
            raise RuntimeError("Channel layer is not configured")

        fanout_metrics = []
        for subscribers in subscriber_sizes:
            metric = async_to_sync(_fanout_case)(
                channel_layer,
                subscribers=subscribers,
                iterations=iterations,
            )
            fanout_metrics.append(metric)

        report = {
            "query": query_metrics,
            "fanout": fanout_metrics,
        }

        if options["as_json"]:
            self.stdout.write(json.dumps(report, ensure_ascii=True, indent=2))
            return

        self.stdout.write("=== Query Benchmark ===")
        self.stdout.write(
            (
                f"iterations={query_metrics['iterations']} limit={query_metrics['query_limit']} "
                f"p50={query_metrics['latency_ms']['p50']}ms "
                f"p95={query_metrics['latency_ms']['p95']}ms "
                f"avg={query_metrics['latency_ms']['avg']}ms"
            )
        )

        self.stdout.write("=== Fanout Benchmark ===")
        for metric in fanout_metrics:
            self.stdout.write(
                (
                    f"subscribers={metric['subscribers']} iterations={metric['iterations']} "
                    f"throughput={metric['throughput_msg_per_sec']} msg/s "
                    f"p50={metric['latency_ms']['p50']}ms p95={metric['latency_ms']['p95']}ms"
                )
            )
