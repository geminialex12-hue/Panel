import json
import time
import uuid

from redis.asyncio import Redis


QUEUE_KEY = "standknife:mm:solo"
MATCH_LOCK_KEY = "standknife:mm:lock"

INITIAL_RANGE = 50
RANGE_STEP = 50
MAX_RANGE = 300

MATCH_SIZE = 10


async def add_to_queue(
    redis: Redis,
    user_id: int,
    elo: int,
    region: str = "EU",
):
    player = {
        "user_id": user_id,
        "elo": elo,
        "region": region,
        "joined_at": time.time(),
    }

    # Удаляем старую запись игрока,
    # чтобы повторный запрос не создавал дубликат.
    await remove_from_queue(redis, user_id)

    await redis.hset(
        QUEUE_KEY,
        str(user_id),
        json.dumps(player),
    )

    return player


async def remove_from_queue(
    redis: Redis,
    user_id: int,
):
    await redis.hdel(
        QUEUE_KEY,
        str(user_id),
    )


async def get_queue(
    redis: Redis,
):
    players = await redis.hgetall(QUEUE_KEY)

    result = []

    for raw in players.values():
        try:
            player = json.loads(raw)
            result.append(player)
        except (TypeError, json.JSONDecodeError):
            continue

    result.sort(
        key=lambda player: player["joined_at"]
    )

    return result


def elo_range_for_wait(
    joined_at: float,
) -> int:
    waited = max(
        0,
        time.time() - joined_at,
    )

    expansion_steps = int(waited // 15)

    elo_range = (
        INITIAL_RANGE
        + expansion_steps * RANGE_STEP
    )

    return min(
        elo_range,
        MAX_RANGE,
    )


def find_candidates(
    players: list[dict],
    anchor: dict,
) -> list[dict]:
    allowed_range = elo_range_for_wait(
        anchor["joined_at"]
    )

    candidates = []

    for player in players:
        if player["user_id"] == anchor["user_id"]:
            continue

        if player["region"] != anchor["region"]:
            continue

        if abs(player["elo"] - anchor["elo"]) > allowed_range:
            continue

        candidates.append(player)

    candidates.sort(
        key=lambda player: (
            abs(player["elo"] - anchor["elo"]),
            player["joined_at"],
        )
    )

    return candidates


def build_match(
    players: list[dict],
) -> dict:
    players = sorted(
        players,
        key=lambda player: player["elo"],
        reverse=True,
    )

    team_a = []
    team_b = []

    # Чередуем игроков по рейтингу,
    # чтобы команды были приблизительно равными.
    for index, player in enumerate(players):
        if index % 2 == 0:
            team_a.append(player)
        else:
            team_b.append(player)

    return {
        "match_id": str(uuid.uuid4()),
        "team_a": team_a,
        "team_b": team_b,
        "status": "WAITING",
        "created_at": time.time(),
    }


async def try_create_match(
    redis: Redis,
):
    # Только один worker одновременно
    # может собирать матч.
    lock = redis.lock(
        MATCH_LOCK_KEY,
        timeout=5,
        blocking_timeout=1,
    )

    acquired = await lock.acquire()

    if not acquired:
        return None

    try:
        players = await get_queue(redis)

        if len(players) < MATCH_SIZE:
            return None

        for anchor in players:
            candidates = find_candidates(
                players,
                anchor,
            )

            if len(candidates) < MATCH_SIZE - 1:
                continue

            selected = [
                anchor,
                *candidates[:MATCH_SIZE - 1],
            ]

            selected_ids = {
                player["user_id"]
                for player in selected
            }

            # Повторно проверяем, что все ещё находятся
            # в очереди перед созданием матча.
            current = await get_queue(redis)

            current_ids = {
                player["user_id"]
                for player in current
            }

            if not selected_ids.issubset(current_ids):
                continue

            match = build_match(selected)

            for user_id in selected_ids:
                await remove_from_queue(
                    redis,
                    user_id,
                )

            return match

        return None

    finally:
        try:
            await lock.release()
        except Exception:
            pass
