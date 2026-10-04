import asyncio
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

import aiosqlite

from bot import ApplicationBlockedError, ApplicationStore, decode_answers, encode_answers


class ApplicationStoreTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.store = ApplicationStore(str(root / "applications.db"), str(root / "backups"), 5)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_answers_round_trip_preserves_newlines(self) -> None:
        answers = ["16", "line one\nline two", "forum"]
        self.assertEqual(decode_answers(encode_answers(answers)), answers)
        self.assertEqual(decode_answers("old\nformat"), ["old", "format"])

    def test_pending_gate_and_single_decision(self) -> None:
        async def scenario() -> None:
            await self.store.init()
            app_id = await self.store.create(1, "user", "Steve", ["16", "because"])
            with self.assertRaises(ApplicationBlockedError):
                await self.store.create(1, "user", "Alex", ["16"])

            self.assertTrue(await self.store.decide(app_id, "approved", 9, "Admin"))
            self.assertFalse(await self.store.decide(app_id, "rejected", 8, "Other", "no"))
            saved = await self.store.get_by_id(app_id)
            assert saved is not None
            self.assertEqual(saved.status, "approved")

            await self.store.reopen_pending(app_id, 9)
            self.assertEqual(await self.store.get_latest_status(1), "pending")
            self.assertTrue(await self.store.decide(app_id, "rejected", 9, "Admin", "later"))
            saved = await self.store.get_by_id(app_id)
            assert saved is not None
            self.assertEqual(saved.answers, ["16", "because"])
            self.assertEqual(saved.decision_reason, "later")

        asyncio.run(scenario())

    def test_concurrent_decisions_apply_once(self) -> None:
        async def scenario() -> None:
            await self.store.init()
            app_id = await self.store.create(7, "user", "Steve", ["16"])
            first, second = await asyncio.gather(
                self.store.decide(app_id, "approved", 9, "Admin"),
                self.store.decide(app_id, "banned", 8, "Other"),
            )
            self.assertEqual(sorted([first, second]), [False, True])
            saved = await self.store.get_by_id(app_id)
            assert saved is not None
            self.assertIn(saved.status, {"approved", "banned"})

        asyncio.run(scenario())

    def test_multiline_answers_are_stored_as_one_field(self) -> None:
        async def scenario() -> None:
            await self.store.init()
            answers = ["18", "want to play\nwith friends"]
            app_id = await self.store.create(2, None, "Alex", answers)
            saved = await self.store.get_by_id(app_id)
            assert saved is not None
            self.assertEqual(saved.answers, answers)

        asyncio.run(scenario())

    def test_search_escapes_like_wildcards(self) -> None:
        async def scenario() -> None:
            await self.store.init()
            await self.store.create(3, "a_b", "a_b", ["1"])
            await self.store.create(4, "axb", "axb", ["1"])
            found = await self.store.search("a_b")
            self.assertEqual([item.nickname for item in found], ["a_b"])

        asyncio.run(scenario())

    def test_daily_counts_follow_local_day(self) -> None:
        async def scenario() -> None:
            await self.store.init()
            local_morning = datetime.now().astimezone().replace(
                hour=1, minute=0, second=0, microsecond=0
            )
            if local_morning.date() < datetime.now().date() - timedelta(days=13):
                self.skipTest("local morning is outside the chart window")
            utc_stamp = local_morning.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
            app_id = await self.store.create(5, None, "Notch", ["1"])
            async with aiosqlite.connect(self.store.db_path) as db:
                await db.execute(
                    "UPDATE applications SET created_at = ? WHERE id = ?",
                    (utc_stamp, app_id),
                )
                await db.commit()
            counts = dict(await self.store.daily_counts(14))
            local_day = local_morning.date().isoformat()
            utc_day = local_morning.astimezone(timezone.utc).date().isoformat()
            self.assertEqual(counts[local_day], 1)
            if local_day != utc_day:
                self.assertEqual(counts.get(utc_day, 0), 0)

        asyncio.run(scenario())


if __name__ == "__main__":
    unittest.main()
