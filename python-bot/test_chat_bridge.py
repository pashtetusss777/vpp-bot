import unittest

from chat_bridge import (
    ChatBridgeSettings,
    apply_prefix,
    format_server_event,
    load_chat_bridge_settings,
    take_new_events,
)


def settings(**overrides: object) -> ChatBridgeSettings:
    raw = {"CHAT_BRIDGE": overrides}
    return load_chat_bridge_settings(raw, -100)


class ChatBridgeFormatTest(unittest.TestCase):
    def test_status_and_chat_topics_are_separate(self) -> None:
        loaded = load_chat_bridge_settings(
            {"CHAT_BRIDGE": {"STATUS_TOPIC_ID": 4, "CHAT_TOPIC_ID": 9}},
            -100,
        )
        self.assertEqual(loaded.status_topic_id, 4)
        self.assertEqual(loaded.chat_topic_id, 9)
        from chat_bridge import topic_for_event

        self.assertEqual(topic_for_event("server_start", loaded), 4)
        self.assertEqual(topic_for_event("server_stop", loaded), 4)
        for kind in ("chat", "join", "leave", "death", "advancement"):
            self.assertEqual(topic_for_event(kind, loaded), 9)
        empty = load_chat_bridge_settings({}, -100)
        self.assertIsNone(empty.status_topic_id)
        self.assertIsNone(empty.chat_topic_id)
        chat_id = load_chat_bridge_settings(
            {"CHAT_BRIDGE": {"STATUS_TOPIC_ID": "-1003933312845", "CHAT_TOPIC_ID": 7}},
            -100,
        )
        self.assertIsNone(chat_id.status_topic_id)
        self.assertEqual(chat_id.chat_topic_id, 7)

    def test_formats_are_configurable_and_escaped(self) -> None:
        custom = settings(FORMAT={"JOIN": "<b>+</b> {name}", "LEAVE": "", "CHAT": "[{name}] {text}"})
        self.assertEqual(format_server_event({"type": "join", "username": "Steve"}, custom), "<b>+</b> Steve")
        self.assertIsNone(format_server_event({"type": "leave", "username": "Steve"}, custom))
        self.assertEqual(
            format_server_event({"type": "chat", "username": "A<b>", "text": "1 < 2 {x}"}, custom),
            "[A&lt;b&gt;] 1 &lt; 2 {x}",
        )

    def test_startup_skips_events_already_queued(self) -> None:
        cursor, primed, fresh = take_new_events([{"id": 1}, {"id": 4}], 0, False)
        self.assertEqual(cursor, 4)
        self.assertTrue(primed)
        self.assertEqual(fresh, [])
        cursor, primed, fresh = take_new_events([{"id": 5, "type": "chat"}], cursor, primed)
        self.assertEqual(fresh, [{"id": 5, "type": "chat"}])
    def test_prefix_is_required_and_can_be_kept(self) -> None:
        self.assertIsNone(apply_prefix("hello", "!", False))
        self.assertEqual(apply_prefix("! hello", "!", False), "hello")
        self.assertEqual(apply_prefix("!hello", "!", True), "!hello")

    def test_join_modes_and_advancement_types(self) -> None:
        base = settings()
        self.assertIn("зашёл", format_server_event({"type": "join", "username": "Steve"}, base) or "")
        self.assertIn(
            "Steve was slain",
            format_server_event({"type": "death", "username": "Steve", "text": "Steve was slain"}, base) or "",
        )
        self.assertIn(
            "погиб",
            format_server_event({"type": "death", "username": "Steve", "text": "death.attack.generic"}, base) or "",
        )
        first_only = settings(EVENTS={"JOIN": "first_join_only"})
        self.assertIsNone(format_server_event({"type": "join", "username": "Steve", "first_join": False}, first_only))
        self.assertIn("первый раз", format_server_event({"type": "join", "username": "Steve", "first_join": True}, first_only) or "")

        no_goals = settings(EVENTS={"ADVANCEMENT_GOAL": False})
        goal = {"type": "advancement", "username": "Steve", "advancement_type": "goal", "title": "Цель"}
        task = {"type": "advancement", "username": "Steve", "advancement_type": "task", "title": "Камень", "description": "Добудь"}
        self.assertIsNone(format_server_event(goal, no_goals))
        rendered = format_server_event(task, base) or ""
        self.assertIn("Камень", rendered)
        self.assertIn("Добудь", rendered)

    def test_custom_formats(self) -> None:
        base = settings()
        plain = format_server_event({"type": "custom", "format": "plain", "text": "<b>x</b>"}, base)
        self.assertEqual(plain, "&lt;b&gt;x&lt;/b&gt;")
        html_text = format_server_event({"type": "custom", "format": "html", "text": "<b>x</b>"}, base)
        self.assertEqual(html_text, "<b>x</b>")
        mm = format_server_event({"type": "custom", "format": "mm", "text": "<red>Привет</red>"}, base)
        self.assertEqual(mm, "Привет")
        json_text = format_server_event(
            {"type": "custom", "format": "json", "text": '{"text":"A","extra":[{"text":"B"}]}'},
            base,
        )
        self.assertEqual(json_text, "AB")

    def test_chat_prefix_blocks_unmarked_messages(self) -> None:
        marked = settings(REQUIRE_PREFIX_MINECRAFT="!")
        self.assertIsNone(format_server_event({"type": "chat", "username": "Steve", "text": "hi"}, marked))
        sent = format_server_event({"type": "chat", "username": "Steve", "text": "!hi"}, marked)
        self.assertEqual(sent, "<b>Steve</b>: hi")


if __name__ == "__main__":
    unittest.main()
