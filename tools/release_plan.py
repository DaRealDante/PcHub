"""Decides what to publish after a push to main (used by .github/workflows/release.yml).

- New pchub.VERSION (no tag `v<VERSION>` yet)            -> app release `v<VERSION>`; every built-in plugin's current
                                                            version is only marked as shipped (tag, no release).
- Same app version, a plugin's `version` went up (no tag) -> plugin release `plugin-<id>-<version>`.

Prints JSON: {"app": "v1.2.3" | null, "plugins": [...tags to release], "mark": [...tags to create without a release]}.
"""
import json
import subprocess
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
sys.path.insert(0, str(root / "tools"))
from pchub import VERSION  # noqa: E402
from pchub.plugins import BUILTIN_PLUGINS  # noqa: E402
import make_update  # noqa: E402


def existingTags():
    output = subprocess.run(["git", "tag", "-l"], cwd=root, capture_output=True, text=True, check=True).stdout
    return set(output.split())


def pluginTags():
    tags = []
    for moduleName in BUILTIN_PLUGINS:
        pluginId = moduleName.split(".")[2]
        tags.append(f"plugin-{pluginId}-{make_update.pluginVersion(pluginId)}")
    return tags


def plan(tags):
    result = {"app": None, "plugins": [], "mark": []}
    appTag = f"v{VERSION}"
    if appTag not in tags:
        result["app"] = appTag
        result["mark"] = [tag for tag in pluginTags() if tag not in tags]
    else:
        result["plugins"] = [tag for tag in pluginTags() if tag not in tags]
    return result


if __name__ == "__main__":
    print(json.dumps(plan(existingTags())))
