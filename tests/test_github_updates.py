import hashlib
import io
import json
import time
import zipfile

from pchub.core import github_updates


def release(tag, assets, body="", draft=False):
    return {"tag_name": tag, "draft": draft, "prerelease": False, "body": body, "html_url": f"https://x/{tag}",
            "assets": [{"name": name, "browser_download_url": f"https://dl/{name}", "size": size,
                        "digest": digest} for name, size, digest in assets]}


def test_parse_and_plan():
    releases = [
        release("v1.2.0", [("PCHub-update-1.2.0.zip", 10, None)], "<!-- hubVersion: 1.2.0 -->\n<!-- buildLevel: 2 -->"),
        release("v1.3.0", [("PCHub-Setup-1.3.0.exe", 10, None)], "<!-- buildLevel: 3 -->", draft=True),
        release("plugin-oled_saver-2.3.0", [("PCHub-plugin-oled_saver-2.3.0.zip", 5, None)], "<!-- hubVersion: 1.1.6 -->"),
        release("plugin-oled_saver-2.2.5", [("PCHub-plugin-oled_saver-2.2.5.zip", 5, None)], "<!-- hubVersion: 1.1.5 -->"),
        release("random-tag", []),
    ]
    parsed = github_updates.parseReleases(releases)
    assert [entry["version"] for entry in parsed["app"]] == ["1.2.0"], "drafts are ignored"
    plan = github_updates.planUpdates(parsed, "1.1.6", 2, {"oled_saver": "2.2.0"})
    assert plan["app"]["version"] == "1.2.0" and not plan["plugins"], "app update first, plugins after"
    parsed["app"] = []
    plan = github_updates.planUpdates(parsed, "1.1.6", 2, {"oled_saver": "2.2.0"})
    assert [entry["version"] for entry in plan["plugins"]] == ["2.3.0"]
    plan = github_updates.planUpdates(parsed, "1.1.6", 2, {"oled_saver": "2.3.0"})
    assert not plan["plugins"], "already installed"
    plan = github_updates.planUpdates(parsed, "1.1.7", 2, {"oled_saver": "2.2.0"})
    assert not plan["plugins"], "plugin releases for another PC Hub version are ignored"
    needsBuild = github_updates.parseReleases([release("v2.0.0", [("PCHub-update-2.0.0.zip", 1, None),
                                                                  ("PCHub-Setup-2.0.0.exe", 1, None)],
                                                       "<!-- buildLevel: 3 -->")])
    plan = github_updates.planUpdates(needsBuild, "1.1.6", 2, {})
    assert plan["app"] is None and plan["needsInstaller"]["version"] == "2.0.0"


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def makeUpdateZip(version):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("update.json", json.dumps({"version": version, "buildLevel": 2}))
        archive.writestr("pchub/__init__.py", f'VERSION = "{version}"\n')
    return buffer.getvalue()


def test_check_downloads_verifies_and_queues(qtApp, dataDir):
    payload = makeUpdateZip("9.9.9")
    digest = "sha256:" + hashlib.sha256(payload).hexdigest()
    releases = [release("v9.9.9", [("PCHub-update-9.9.9.zip", len(payload), digest)], "<!-- buildLevel: 2 -->")]
    updater = github_updates.GitHubUpdater("me/PcHub", "1.1.6", 2)
    requested = []

    def opener(request, timeout=30):
        requested.append(request.full_url)
        if request.full_url.endswith("releases?per_page=30"):
            return FakeResponse(json.dumps(releases).encode())
        return FakeResponse(payload)

    updater.opener = opener
    results = []
    updater.checkFinished.connect(results.append)
    assert updater.check({}, install=True)
    deadline = time.monotonic() + 5
    while not results and time.monotonic() < deadline:
        qtApp.processEvents()
        time.sleep(0.01)
    assert results and results[0]["status"] == "downloaded", results
    assert (dataDir / "updates" / "pending.zip").read_bytes() == payload
    assert requested[0] == "https://api.github.com/repos/me/PcHub/releases?per_page=30"
    updater.thread.join(2)

    releases[0]["assets"][0]["digest"] = "sha256:" + "0" * 64
    results.clear()
    updater.check({}, install=True)
    deadline = time.monotonic() + 5
    while not results and time.monotonic() < deadline:
        qtApp.processEvents()
        time.sleep(0.01)
    assert results[0]["status"] == "error" and "checksum" in results[0]["error"]
    updater.thread.join(2)


def test_alert_cards_count_down_and_leave(qtApp):
    from pchub.ui.alerts import AlertManager
    settings = {"notifications.seconds": 1, "notifications.keepImportant": False}
    manager = AlertManager(lambda key, default=None: settings.get(key, default))
    card = manager.show("Hi", "there")
    sticky = manager.show("Stay", timeoutSeconds=-1)
    withActions = manager.show("Act", actions=[("Ok", lambda: None)])
    assert card.duration == 1 and sticky.duration == 0 and withActions.duration == 2
    deadline = time.monotonic() + 3
    while card in manager.cards and time.monotonic() < deadline:
        qtApp.processEvents()
        time.sleep(0.01)
    assert card not in manager.cards and sticky in manager.cards, "timed cards leave by themselves"
    pass
    settings["notifications.keepImportant"] = True
    assert manager.resolveTimeout(0, [("x", None)]) == 0
    manager.closeAll()
    from PySide6.QtCore import QCoreApplication, QEvent
    for _ in range(30):
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        qtApp.processEvents()
        time.sleep(0.01)
