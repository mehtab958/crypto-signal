from whalebot.bot import Bot
from whalebot.commands import CommandListener, handle
from whalebot.config import Config


def make_bot(tmp_path):
    cfg = Config(database_path=str(tmp_path / "t.db"))
    cfg.secrets.telegram_bot_token = "TOKEN"
    cfg.secrets.telegram_chat_id = "111"
    return Bot(cfg)


def test_offline_commands(tmp_path):
    bot = make_bot(tmp_path)
    assert "/top" in handle(bot, "/help")
    assert "threshold set to 70" in handle(bot, "/threshold@MyBot 70")
    assert bot.cfg.scoring.alert_threshold == 70
    assert "paused" in handle(bot, "/pause") and bot.alerts_paused
    assert "resumed" in handle(bot, "/resume") and not bot.alerts_paused
    assert "No whale wallets" in handle(bot, "/whales")
    assert "No results yet" in handle(bot, "/report")
    assert "Unknown command" in handle(bot, "/nope")


def test_listener_ignores_other_chats(tmp_path):
    bot = make_bot(tmp_path)
    sent = []
    updates = {"ok": True, "result": [
        {"update_id": 5, "message": {"text": "/status", "chat": {"id": 999}}},
        {"update_id": 6, "message": {"text": "/status", "chat": {"id": 111}}},
    ]}
    bot.http.get = lambda url, **kw: updates
    bot.alerter.send_to = lambda chat_id, text: sent.append((chat_id, text))
    listener = CommandListener(bot)
    listener.poll_once()
    assert listener.offset == 7
    assert [c for c, _ in sent] == ["111"]
    assert "Status" in sent[0][1]
