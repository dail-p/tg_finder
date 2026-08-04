from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from src.db.models import Channel, ChannelPack, PackChannel, User
from src.packs import service as packs
from src.packs.service import (
    ChannelAlreadyInPackError,
    PackLimitError,
    PackNameTakenError,
    PackNotFoundError,
    RemoveChannelResult,
)


class _Scalars:
    def __init__(self, values: list[Any]) -> None:
        self._values = values

    def all(self) -> list[Any]:
        return self._values

    def first(self) -> Any:
        return self._values[0] if self._values else None


class _Result:
    def __init__(self, value: Any, scalar: Any = None) -> None:
        # For scalar_one_or_none()
        self._scalar = scalar
        # For .scalars().all()
        self._scalars = _Scalars(value if isinstance(value, list) else [value])

    def scalar_one_or_none(self) -> Any:
        return self._scalar

    def scalars(self) -> _Scalars:
        return self._scalars


class _DeleteResult:
    def __init__(self, rowcount: int) -> None:
        self.rowcount = rowcount


@dataclass
class FakeSession:
    """Async session stub used to exercise the packs service.

    `get_returns` maps (entity, pk) -> object for session.get().
    `execute_returns` is a FIFO of _Result/_DeleteResult returned by execute().
    `add`ed objects get an autoassigned id on `flush`.
    """

    get_returns: dict[tuple[type, int], Any] = field(default_factory=dict)
    execute_returns: list[Any] = field(default_factory=list)
    added: list[Any] = field(default_factory=list)
    deleted: list[Any] = field(default_factory=list)
    flushed: bool = False
    committed: bool = False
    rolled_back: bool = False
    _next_id: int = 100

    def _pop_result(self) -> Any:
        if not self.execute_returns:
            return _Result([], scalar=None)
        return self.execute_returns.pop(0)

    async def get(self, entity, pk):
        return self.get_returns.get((entity, pk))

    async def execute(self, stmt):
        return self._pop_result()

    def add(self, obj) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        for obj in self.added:
            if hasattr(obj, "id") and getattr(obj, "id", None) is None:
                obj.id = self._next_id
                self._next_id += 1
        self.flushed = True

    async def commit(self) -> None:
        self.committed = True

    async def rollback(self) -> None:
        self.rolled_back = True
        self.added.clear()

    async def delete(self, obj) -> None:
        self.deleted.append(obj)


@pytest.mark.asyncio
async def test_get_or_create_user_creates_new() -> None:
    session = FakeSession()
    user = await packs.get_or_create_user(session, 111, "alice")
    assert isinstance(user, User)
    assert user.id == 111
    assert user.username == "alice"
    assert user in session.added


@pytest.mark.asyncio
async def test_get_or_create_user_updates_username() -> None:
    existing = User(id=111, username="old")
    session = FakeSession(get_returns={(User, 111): existing})
    user = await packs.get_or_create_user(session, 111, "new")
    assert user is existing
    assert user.username == "new"
    assert session.added == []


@pytest.mark.asyncio
async def test_create_pack_and_list() -> None:
    session = FakeSession(execute_returns=[_Result([], scalar=None), _Result([], scalar=None)])
    # First list_packs (empty), then create_pack's internal list_packs also empty
    # Actually create_pack calls list_packs first.
    # We'll feed: list_packs (empty) for create, then list_packs again for the test.
    pack = await packs.create_pack(session, 111, "News")
    assert pack.name == "News"
    assert pack.owner_id == 111
    assert pack.id is not None


@pytest.mark.asyncio
async def test_create_pack_rejects_duplicate_name() -> None:
    existing = ChannelPack(id=5, owner_id=111, name="News")
    session = FakeSession(execute_returns=[_Result([existing], scalar=existing)])
    with pytest.raises(PackNameTakenError):
        await packs.create_pack(session, 111, "News")


@pytest.mark.asyncio
async def test_create_pack_empty_name_raises() -> None:
    session = FakeSession(execute_returns=[_Result([], scalar=None)])
    with pytest.raises(ValueError):
        await packs.create_pack(session, 111, "   ")


@pytest.mark.asyncio
async def test_get_pack_returns_none_for_other_owner() -> None:
    session = FakeSession(execute_returns=[_Result(None, scalar=None)])
    assert await packs.get_pack(session, 5, 999) is None


@pytest.mark.asyncio
async def test_rename_pack_changes_name() -> None:
    pack = ChannelPack(id=5, owner_id=111, name="Old")
    session = FakeSession(
        execute_returns=[
            _Result(pack, scalar=pack),  # get_pack
            _Result([], scalar=None),  # list_packs for uniqueness
        ]
    )
    renamed = await packs.rename_pack(session, 5, 111, "New")
    assert renamed.name == "New"


@pytest.mark.asyncio
async def test_rename_pack_duplicate_name_raises() -> None:
    pack = ChannelPack(id=5, owner_id=111, name="Old")
    sibling = ChannelPack(id=6, owner_id=111, name="Taken")
    session = FakeSession(
        execute_returns=[
            _Result(pack, scalar=pack),
            _Result([pack, sibling], scalar=pack),
        ]
    )
    with pytest.raises(PackNameTakenError):
        await packs.rename_pack(session, 5, 111, "Taken")


@pytest.mark.asyncio
async def test_rename_pack_not_found_raises() -> None:
    session = FakeSession(execute_returns=[_Result(None, scalar=None)])
    with pytest.raises(PackNotFoundError):
        await packs.rename_pack(session, 5, 111, "New")


@pytest.mark.asyncio
async def test_delete_pack_returns_true_and_deletes() -> None:
    pack = ChannelPack(id=5, owner_id=111, name="News")
    session = FakeSession(execute_returns=[_Result(pack, scalar=pack)])
    ok = await packs.delete_pack(session, 5, 111)
    assert ok is True
    assert session.deleted == [pack]


@pytest.mark.asyncio
async def test_delete_pack_missing_returns_false() -> None:
    session = FakeSession(execute_returns=[_Result(None, scalar=None)])
    assert await packs.delete_pack(session, 5, 111) is False
    assert session.deleted == []


@pytest.mark.asyncio
async def test_add_channel_to_pack_creates_link() -> None:
    pack = ChannelPack(id=5, owner_id=111, name="News")
    # get_pack, _pack_size (0), then existence check (None)
    session = FakeSession(
        execute_returns=[
            _Result(pack, scalar=pack),
            _Result([], scalar=None),
            _Result(None, scalar=None),
        ]
    )
    link = await packs.add_channel_to_pack(session, pack_id=5, channel_id=7, owner_id=111)
    assert isinstance(link, PackChannel)
    assert link.pack_id == 5
    assert link.channel_id == 7
    assert link in session.added


@pytest.mark.asyncio
async def test_add_channel_to_pack_rejects_duplicate() -> None:
    pack = ChannelPack(id=5, owner_id=111, name="News")
    existing = PackChannel(pack_id=5, channel_id=7)
    session = FakeSession(
        execute_returns=[
            _Result(pack, scalar=pack),
            _Result([], scalar=None),
            _Result(existing, scalar=existing),
        ]
    )
    with pytest.raises(ChannelAlreadyInPackError):
        await packs.add_channel_to_pack(session, 5, 7, 111)


@pytest.mark.asyncio
async def test_add_channel_to_pack_rejects_foreign_pack() -> None:
    session = FakeSession(execute_returns=[_Result(None, scalar=None)])

    with pytest.raises(PackNotFoundError):
        await packs.add_channel_to_pack(session, 5, 7, owner_id=999)

    assert session.added == []


@pytest.mark.asyncio
async def test_get_pack_channel_ids_returns_ints() -> None:
    session = FakeSession(execute_returns=[_Result([1, 2, 3], scalar=None)])
    ids = await packs.get_pack_channel_ids(session, 5, owner_id=111)
    assert ids == [1, 2, 3]
    assert all(isinstance(x, int) for x in ids)


@pytest.mark.asyncio
async def test_remove_channel_from_pack_returns_bool() -> None:
    pack = ChannelPack(id=5, owner_id=111, name="News")
    session = FakeSession(
        execute_returns=[
            _Result(pack, scalar=pack),
            _Result([7, 8], scalar=None),
            _DeleteResult(rowcount=1),
        ]
    )

    result = await packs.remove_channel_from_pack(session, 5, 7, owner_id=111)

    assert result == RemoveChannelResult(removed=True, pack_deleted=False)


@pytest.mark.asyncio
async def test_remove_last_channel_deletes_empty_pack() -> None:
    pack = ChannelPack(id=5, owner_id=111, name="News")
    session = FakeSession(
        execute_returns=[
            _Result(pack, scalar=pack),
            _Result([7], scalar=None),
        ]
    )

    result = await packs.remove_channel_from_pack(session, 5, 7, owner_id=111)

    assert result == RemoveChannelResult(removed=True, pack_deleted=True)
    assert session.deleted == [pack]


@pytest.mark.asyncio
async def test_remove_channel_rejects_foreign_pack() -> None:
    session = FakeSession(execute_returns=[_Result(None, scalar=None)])

    with pytest.raises(PackNotFoundError):
        await packs.remove_channel_from_pack(session, 5, 7, owner_id=999)

    assert session.deleted == []


@pytest.mark.asyncio
async def test_ensure_channel_creates_new_with_username_as_title() -> None:
    session = FakeSession(execute_returns=[_Result(None, scalar=None)])
    ch = await packs.ensure_channel(session, "@news", username="news")
    assert ch.telegram_id == "@news"
    assert ch.title == "@news"
    assert ch.username == "news"
    assert ch in session.added


@pytest.mark.asyncio
async def test_ensure_channel_returns_existing() -> None:
    existing = Channel(id=1, telegram_id="@news", title="News", username="news")
    session = FakeSession(execute_returns=[_Result(existing, scalar=existing)])
    ch = await packs.ensure_channel(session, "@news", title="ignored", username="news")
    assert ch is existing
    assert session.added == []


@pytest.mark.asyncio
async def test_ensure_channel_updates_placeholder_title() -> None:
    existing = Channel(id=1, telegram_id="@news", title="@news", username=None)
    session = FakeSession(execute_returns=[_Result(existing, scalar=existing)])
    ch = await packs.ensure_channel(session, "@news", title="Real News", username="news")
    assert ch.title == "Real News"
    assert ch.username == "news"


def test_normalize_username_variants() -> None:
    assert packs.normalize_username("@foo") == "@foo"
    assert packs.normalize_username("foo") == "@foo"
    assert packs.normalize_username("https://t.me/foo") == "@foo"
    assert packs.normalize_username("https://t.me/foo/42") is None  # post link, not channel
    assert packs.normalize_username("t.me/foo") == "@foo"
    assert packs.normalize_username("") is None
    assert packs.normalize_username("  ") is None
    assert packs.normalize_username("foo bar") is None


@pytest.mark.asyncio
async def test_create_pack_enforces_max_packs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(packs, "MAX_PACKS_PER_USER", 2)
    existing = [
        ChannelPack(id=1, owner_id=111, name="A"),
        ChannelPack(id=2, owner_id=111, name="B"),
    ]
    session = FakeSession(execute_returns=[_Result(existing, scalar=existing[0])])
    with pytest.raises(PackLimitError):
        await packs.create_pack(session, 111, "C")
